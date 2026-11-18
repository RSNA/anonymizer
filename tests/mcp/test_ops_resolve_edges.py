"""Bounded mcp.ops resolve / inventory / preview gate unit tests (mocked controller)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.mcp.ops import (
    HeadlessOpsError,
    _inventory_study_keys,
    _lookup_series_meta,
    export_series_preview,
    harmonize_studies,
    resolve_series,
)
from anonymizer.model.anonymizer import AnonymizerModel


def _phi_tree(
    *,
    patient_id: str,
    anon_patient_id: str,
    anon_study_uid: str,
    anon_series_uid: str,
    modality: str = "CT",
    series_description: str = "Chest",
) -> SimpleNamespace:
    series = SimpleNamespace(
        anon_series_uid=anon_series_uid,
        modality=modality,
        description=series_description,
        harmonized_description="",
        embedded_phi_scanned=False,
    )
    study = SimpleNamespace(
        anon_study_uid=anon_study_uid,
        description="Study",
        harmonized_description="",
        series=[series],
    )
    return SimpleNamespace(
        patient_id=patient_id,
        anon_patient_id=anon_patient_id,
        studies=[study],
    )


def test_lookup_series_meta_from_orm_and_path_fallback(tmp_path: Path) -> None:
    controller = MagicMock()
    images = tmp_path / "images"
    series_dir = images / "990001-000001" / "study1" / "series1"
    series_dir.mkdir(parents=True)
    controller.model.images_dir.return_value = images
    controller.anonymizer.model.load_phi_with_studies_series_no_instances.return_value = [
        _phi_tree(
            patient_id="P1",
            anon_patient_id="990001-000001",
            anon_study_uid="study1",
            anon_series_uid="series1",
            modality="MR",
            series_description="Brain",
        )
    ]
    meta = _lookup_series_meta(controller, "series1")
    assert meta["modality"] == "MR"
    assert meta["series_description"] == "Brain"
    assert meta["anon_patient_id"] == "990001-000001"

    controller.anonymizer.model.load_phi_with_studies_series_no_instances.return_value = []
    meta2 = _lookup_series_meta(controller, "missing", series_path=series_dir)
    assert meta2["anon_patient_id"] == "990001-000001"
    assert meta2["modality"] == ""


def test_inventory_study_keys_skips_default_phi() -> None:
    controller = MagicMock()
    controller.anonymizer.model.load_phi_with_studies_series_no_instances.return_value = [
        _phi_tree(
            patient_id=AnonymizerModel.DEFAULT_PHI_PATIENT_ID_PK_VALUE,
            anon_patient_id="990001-000000",
            anon_study_uid="s0",
            anon_series_uid="ser0",
        ),
        _phi_tree(
            patient_id="P1",
            anon_patient_id="990001-000001",
            anon_study_uid="studyA",
            anon_series_uid="serA",
        ),
    ]
    assert _inventory_study_keys(controller) == [("990001-000001", "studyA")]


def test_resolve_series_empty_inventory() -> None:
    controller = MagicMock()
    with patch("anonymizer.mcp.ops.list_inventory", return_value={"series": []}):
        with pytest.raises(HeadlessOpsError, match="No series in inventory"):
            resolve_series(controller, patient="1", series="1")


def test_resolve_series_patient_all_rejected() -> None:
    controller = MagicMock()
    with patch(
        "anonymizer.mcp.ops.list_inventory",
        return_value={"series": [{"anon_patient_id": "p1", "anon_study_uid": "s", "anon_series_uid": "x"}]},
    ):
        with pytest.raises(HeadlessOpsError, match='patient="all"'):
            resolve_series(controller, patient="all", series="1")


def test_resolve_series_by_anon_uid(tmp_path: Path) -> None:
    images = tmp_path / "images"
    series_dir = images / "pat" / "stu" / "serUID"
    series_dir.mkdir(parents=True)
    controller = MagicMock()
    controller.model.images_dir.return_value = images
    controller.anonymizer.model.load_phi_with_studies_series_no_instances.return_value = []

    resolved = resolve_series(controller, anon_series_uid="serUID")
    assert resolved["anon_series_uid"] == "serUID"
    assert resolved["series_path"] == str(series_dir)


def test_export_series_preview_requires_scan_gate() -> None:
    controller = MagicMock()
    controller.anonymizer.model.series_embedded_phi_scanned.return_value = False
    with patch(
        "anonymizer.mcp.ops.resolve_series",
        return_value={"series_path": "/images/p/s/ser"},
    ):
        with pytest.raises(HeadlessOpsError, match="not been scanned"):
            export_series_preview(
                controller,
                anon_series_uid="ser",
                require_pixel_phi_scanned=True,
            )


def test_harmonize_studies_unknown_uid() -> None:
    controller = MagicMock()
    with patch(
        "anonymizer.mcp.ops._inventory_study_keys",
        return_value=[("p1", "known")],
    ):
        with pytest.raises(HeadlessOpsError, match="Unknown anon_study_uid"):
            harmonize_studies(controller, anon_study_uids=["missing"])
