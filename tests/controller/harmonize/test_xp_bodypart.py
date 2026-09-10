"""Unit tests for XR pixel body-part preprocess, fusion, and cache probe."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.harmonize.playbook_planar import (
    build_planar_playbook_attributes,
    planar_harmonize_analysis_rows,
)
from anonymizer.controller.ai.harmonize.xp_bodypart.cache import (
    XpBodypartModelStatus,
    probe_xp_bodypart_models,
)
from anonymizer.controller.ai.harmonize.xp_bodypart.fuse import fuse_planar_anatomy
from anonymizer.controller.ai.harmonize.xp_bodypart.labels import (
    XP_BODYPART_LABELS,
    map_xp_label_to_planar_anatomy,
)
from anonymizer.controller.ai.harmonize.xp_bodypart.predict import XpBodypartPrediction
from anonymizer.controller.ai.harmonize.xp_bodypart.preprocess import (
    pad_to_square_256,
    tensor_from_grayscale_array,
    uint8_grayscale_from_array,
)


def test_map_incomplete_chest_to_chest() -> None:
    assert map_xp_label_to_planar_anatomy("Incomplete Chest") == "Chest"
    assert map_xp_label_to_planar_anatomy("Chest") == "Chest"
    assert len(XP_BODYPART_LABELS) == 7


def test_preprocess_pad_and_tensor_shape() -> None:
    arr = np.arange(120 * 80, dtype=np.uint16).reshape(120, 80)
    gray = uint8_grayscale_from_array(arr)
    assert gray.dtype == np.uint8
    assert gray.shape == (120, 80)
    pil = pad_to_square_256(Image.fromarray(gray, mode="L"))
    assert pil.size == (256, 256)
    tensor = tensor_from_grayscale_array(arr)
    assert tuple(tensor.shape) == (1, 1, 256, 256)


def _pred(label: str, conf: float) -> XpBodypartPrediction:
    probs = [0.0] * 7
    probs[XP_BODYPART_LABELS.index(label if label != "Incomplete Chest" else "Incomplete Chest")] = conf
    # fill remainder so softmax-like
    rem = max(0.0, 1.0 - conf) / 6
    for i, name in enumerate(XP_BODYPART_LABELS):
        if name != label:
            probs[i] = rem
    return XpBodypartPrediction(label=label, confidence=conf, probs=tuple(probs))


def test_fuse_prefers_dicom_fine_extremity() -> None:
    fused = fuse_planar_anatomy(
        dicom_label="Hand",
        dicom_evidence="BodyPartExamined=HAND",
        pixel_pred=_pred("Extremities", 0.95),
    )
    assert fused.label == "Hand"
    assert fused.source == "fused"


def test_fuse_high_conf_pixel_overrides_conflict() -> None:
    fused = fuse_planar_anatomy(
        dicom_label="Abdomen",
        dicom_evidence="BodyPartExamined=ABDOMEN",
        pixel_pred=_pred("Chest", 0.91),
    )
    assert fused.label == "Chest"
    assert fused.source == "pixel"


def test_fuse_medium_conf_keeps_dicom() -> None:
    fused = fuse_planar_anatomy(
        dicom_label="Abdomen",
        dicom_evidence="BodyPartExamined=ABDOMEN",
        pixel_pred=_pred("Chest", 0.6),
    )
    assert fused.label == "Abdomen"
    assert fused.source == "DICOM"
    assert "model secondary" in fused.evidence
    assert "60.00% confidence" in fused.evidence


def test_fuse_incomplete_chest_maps_to_chest() -> None:
    fused = fuse_planar_anatomy(
        dicom_label="Chest",
        dicom_evidence="BodyPartExamined=CHEST",
        pixel_pred=_pred("Incomplete Chest", 0.88),
    )
    assert fused.label == "Chest"
    assert fused.pixel_label == "Incomplete Chest"


def test_fuse_pixel_only_when_dicom_missing() -> None:
    fused = fuse_planar_anatomy(
        dicom_label=None,
        dicom_evidence=None,
        pixel_pred=_pred("Pelvis", 0.7),
    )
    assert fused.label == "Pelvis"
    assert fused.source == "pixel"


def test_probe_missing_without_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.xp_bodypart.cache.XP_BODYPART_WEIGHT_PATH",
        tmp_path / "xp_bodypart.pt",
    )
    status, _ = probe_xp_bodypart_models()
    assert status == XpBodypartModelStatus.MISSING


def _dx_dataset(*, body_part: str = "CHEST") -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.Modality = "DX"
    ds.BodyPartExamined = body_part
    ds.ViewPosition = "AP"
    return ds


def test_build_planar_attributes_fuses_pixel() -> None:
    ds = _dx_dataset(body_part="ABDOMEN")
    attrs = build_planar_playbook_attributes(ds, pixel_pred=_pred("Chest", 0.92))
    assert attrs.body_part_label == "Chest"
    assert attrs.body_part_source == "pixel"
    assert attrs.pixel_body_part_label == "Chest"
    rows = planar_harmonize_analysis_rows(attrs)
    body_row = next(row for row in rows if row[0] == "Body Part")
    assert "Xp-Bodypart" in body_row[4]
    assert "confidence" in body_row[3]
    assert not any(row[0] == "Pixel body part" for row in rows)


def test_build_planar_attributes_without_pixel_unchanged() -> None:
    ds = _dx_dataset(body_part="CHEST")
    attrs = build_planar_playbook_attributes(ds)
    assert attrs.body_part_label == "Chest"
    assert attrs.body_part_source == "DICOM"
