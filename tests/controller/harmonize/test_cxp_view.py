"""Unit tests for CXR projection/rotation (cxp_view)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.harmonize.cxp_view.cache import CxpViewModelStatus, probe_cxp_view_models
from anonymizer.controller.ai.harmonize.cxp_view.fuse import fuse_xr_view
from anonymizer.controller.ai.harmonize.cxp_view.labels import (
    CXP_PROJECTION_LABELS,
    map_projection_to_playbook_view,
)
from anonymizer.controller.ai.harmonize.cxp_view.predict import CxpViewPrediction
from anonymizer.controller.ai.harmonize.cxp_view.preprocess import upright_array
from anonymizer.controller.ai.harmonize.playbook_planar import (
    build_planar_playbook_attributes,
    planar_harmonize_analysis_rows,
)


def _pred(
    projection: str,
    proj_conf: float,
    *,
    rotation: str = "Upright",
    rot_conf: float = 0.95,
) -> CxpViewPrediction:
    proj_probs = [0.0] * 3
    proj_probs[CXP_PROJECTION_LABELS.index(projection)] = proj_conf
    rem = max(0.0, 1.0 - proj_conf) / 2
    for i, name in enumerate(CXP_PROJECTION_LABELS):
        if name != projection:
            proj_probs[i] = rem
    return CxpViewPrediction(
        projection=projection,
        projection_confidence=proj_conf,
        rotation=rotation,
        rotation_confidence=rot_conf,
        projection_probs=tuple(proj_probs),
        rotation_probs=(rot_conf, 0.0, 0.0, 0.0),
    )


def test_map_lateral_to_lat() -> None:
    assert map_projection_to_playbook_view("Lateral") == "Lat"
    assert map_projection_to_playbook_view("AP") == "AP"


def test_upright_array_rotations() -> None:
    arr = np.arange(12, dtype=np.uint8).reshape(3, 4)
    assert np.array_equal(upright_array(arr, "Upright"), arr)
    assert upright_array(arr, "Inverted").shape == (3, 4)
    assert upright_array(arr, "Left-rotation").shape == (4, 3)
    assert upright_array(arr, "Right-rotation").shape == (4, 3)


def test_fuse_keeps_dicom_multiview() -> None:
    fused = fuse_xr_view(
        dicom_view="2V",
        dicom_evidence="keyword:2V",
        pixel_pred=_pred("AP", 0.99),
    )
    assert fused.view_code == "2V"
    assert fused.source == "DICOM"


def test_fuse_high_conf_overrides_view() -> None:
    fused = fuse_xr_view(
        dicom_view="PA",
        dicom_evidence="ViewPosition=PA",
        pixel_pred=_pred("AP", 0.91),
    )
    assert fused.view_code == "AP"
    assert fused.source == "pixel"


def test_fuse_agree_and_pixel_only() -> None:
    agree = fuse_xr_view(
        dicom_view="AP",
        dicom_evidence="ViewPosition=AP",
        pixel_pred=_pred("AP", 0.8),
    )
    assert agree.source == "fused"
    only = fuse_xr_view(dicom_view=None, dicom_evidence=None, pixel_pred=_pred("Lateral", 0.7))
    assert only.view_code == "Lat"
    assert only.source == "pixel"


def test_probe_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.cxp_view.cache.CXP_VIEW_WEIGHT_PATH",
        tmp_path / "cxp_projection_rotation.pt",
    )
    status, _ = probe_cxp_view_models()
    assert status == CxpViewModelStatus.MISSING


def _dx_dataset(*, body_part: str = "CHEST", view: str = "PA") -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.Modality = "DX"
    ds.BodyPartExamined = body_part
    ds.ViewPosition = view
    return ds


def test_build_attributes_fuses_chest_view() -> None:
    ds = _dx_dataset(body_part="CHEST", view="PA")
    attrs = build_planar_playbook_attributes(
        ds, pixel_view_pred=_pred("AP", 0.93, rotation="Inverted", rot_conf=0.9)
    )
    assert attrs.view_code == "AP"
    assert attrs.view_source == "pixel"
    assert attrs.rotation_label == "Inverted"
    rows = planar_harmonize_analysis_rows(attrs)
    view_row = next(row for row in rows if row[0] == "View")
    assert "CXp-Projection-Rotation" in view_row[4]
    assert "confidence" in view_row[3]
    rot_row = next(row for row in rows if row[0] == "Rotation")
    assert rot_row[4] == "CXp-Projection-Rotation"
    assert "Inverted" in rot_row[3] and "confidence" in rot_row[3]
    assert not any(row[0] == "Pixel view" for row in rows)


def test_knee_without_view_pred_unchanged() -> None:
    ds = _dx_dataset(body_part="KNEE", view="AP")
    attrs = build_planar_playbook_attributes(ds)
    assert attrs.body_part_label == "Knee"
    assert attrs.view_code == "AP"
    assert attrs.view_source == "DICOM"
    assert attrs.rotation_label == ""


def _stub_planar_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    series: Path,
    ds: Dataset,
) -> MagicMock:
    from anonymizer.controller.ai.harmonize import pipeline as pipe

    monkeypatch.setattr(pipe, "_load_planar_series_dataset", lambda _p: ds)
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.cxp_view.cxp_view_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.xp_bodypart.xp_bodypart_ready",
        lambda: False,
    )
    called = MagicMock(return_value=_pred("AP", 0.95))
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.cxp_view.predict_cxp_view",
        called,
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.dicom_geometry.sorted_dicom_paths",
        lambda _p: [series / "slice.dcm"],
    )
    fake_ds = MagicMock()
    fake_ds.pixel_array = np.zeros((32, 32), dtype=np.uint8)
    monkeypatch.setattr(pipe, "dcmread", lambda *_a, **_k: fake_ds)
    return called


def test_pipeline_skips_cxp_for_non_chest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from anonymizer.controller.ai.harmonize import pipeline as pipe

    series = tmp_path / "knee"
    series.mkdir()
    called = _stub_planar_pipeline(
        monkeypatch, series=series, ds=_dx_dataset(body_part="KNEE", view="AP")
    )
    result = pipe._harmonize_one_planar_series(
        series,
        progress=None,
        started=0.0,
        cancelled=None,
        timing_collector=None,
    )
    assert result is not None
    assert result.error is None
    called.assert_not_called()


def test_pipeline_chest_calls_cxp_and_fuses_view(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from anonymizer.controller.ai.harmonize import pipeline as pipe

    series = tmp_path / "chest"
    series.mkdir()
    called = _stub_planar_pipeline(
        monkeypatch, series=series, ds=_dx_dataset(body_part="CHEST", view="PA")
    )
    result = pipe._harmonize_one_planar_series(
        series,
        progress=None,
        started=0.0,
        cancelled=None,
        timing_collector=None,
    )
    assert result is not None
    assert result.error is None
    called.assert_called_once()
    assert result.planar is not None
    assert result.planar.view_code == "AP"
    assert result.planar.view_source == "pixel"
    assert "Chest AP" in result.radlex_series_description
