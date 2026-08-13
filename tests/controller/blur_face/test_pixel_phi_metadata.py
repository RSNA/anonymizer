"""Tests for pixel PHI metadata helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydicom import Dataset

from anonymizer.controller.ai.remove_pixel_phi import (
    OCRText,
    OverlayData,
    UserRectangle,
    _dedupe_texts,
    apply_instance_pixel_phi,
    apply_instance_pixel_phi_for_dcm,
    apply_series_view_pixel_phi,
    collect_series_view_pixel_phi_texts,
    remove_pixel_phi,
)
from anonymizer.model.anonymizer import Instance
from tests.controller.dicom.support.test_nodes import TEST_SITEID, TEST_UIDROOT


@pytest.fixture
def mock_dataset() -> Dataset:
    ds = Dataset()
    ds.PatientID = "123456"
    ds.PatientName = "Doe^John"
    ds.StudyInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.1"
    ds.SeriesInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.2"
    ds.SOPInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.3"
    ds.Modality = "CT"
    return ds


def test_dedupe_texts_preserves_order() -> None:
    assert _dedupe_texts(["  foo ", "bar", "foo", "", "  bar  "]) == ["foo", "bar"]


@patch("anonymizer.controller.ai.remove_pixel_phi.dcmread")
def test_remove_pixel_phi_returns_empty_tuple_when_no_text(mock_dcmread: MagicMock) -> None:
    import numpy as np

    pixels = np.zeros((64, 64), dtype=np.uint8)
    ds = MagicMock()
    ds.get.side_effect = lambda key, default=None: {
        "PhotometricInterpretation": "MONOCHROME2",
        "SamplesPerPixel": 1,
        "Rows": 64,
        "Columns": 64,
        "BitsAllocated": 8,
        "BitsStored": 8,
        "HighBit": 7,
        "PixelRepresentation": 0,
        "NumberOfFrames": 1,
    }.get(key, default)
    ds.pixel_array = pixels
    ds.PixelData = b"\x00"
    ds.file_meta.TransferSyntaxUID.is_compressed = False
    mock_dcmread.return_value = ds

    ocr_reader = MagicMock()
    ocr_reader.readtext.return_value = []

    modified, texts, pixels_changed = remove_pixel_phi(Path("/tmp/test.dcm"), ocr_reader)

    assert modified is False
    assert texts == []
    assert pixels_changed == 0


def test_apply_instance_pixel_phi_delegates_to_model(mock_dataset: Dataset, tmp_path: Path) -> None:
    db_path = tmp_path / "pixel_phi.db"
    from anonymizer.model.anonymizer import AnonymizerModel

    model = AnonymizerModel(
        site_id=TEST_SITEID,
        uid_root=TEST_UIDROOT,
        script_path=Path("src/anonymizer/assets/scripts/default-anonymizer.script"),
        db_url=f"sqlite:///{db_path}",
    )
    model.capture_phi(source="pytest", ds=mock_dataset, date_delta=0)
    phi = model.get_phi_by_phi_patient_id(mock_dataset.PatientID)
    assert phi is not None
    instance = phi.studies[0].series[0].instances[0]

    assert apply_instance_pixel_phi(model, instance.anon_sop_instance_uid, ["Burned", "Burned", " Name"]) is True

    with model._get_session(read_only=True) as session:
        row = session.get(Instance, instance.sop_instance_uid)
        assert row is not None
        assert row.pixel_phi == "Burned, Name"


@patch("anonymizer.controller.ai.remove_pixel_phi.dcmread")
def test_apply_instance_pixel_phi_for_dcm_reads_sop_uid(
    mock_dcmread: MagicMock,
    mock_dataset: Dataset,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pixel_phi_for_dcm.db"
    from anonymizer.model.anonymizer import AnonymizerModel

    model = AnonymizerModel(
        site_id=TEST_SITEID,
        uid_root=TEST_UIDROOT,
        script_path=Path("src/anonymizer/assets/scripts/default-anonymizer.script"),
        db_url=f"sqlite:///{db_path}",
    )
    model.capture_phi(source="pytest", ds=mock_dataset, date_delta=0)
    phi = model.get_phi_by_phi_patient_id(mock_dataset.PatientID)
    assert phi is not None
    instance = phi.studies[0].series[0].instances[0]

    dcm_path = tmp_path / "slice.dcm"
    dcm_path.write_bytes(b"")
    mock_ds = Dataset()
    mock_ds.SOPInstanceUID = instance.anon_sop_instance_uid
    mock_dcmread.return_value = mock_ds

    assert apply_instance_pixel_phi_for_dcm(model, dcm_path, ["Left", "Right"]) is True

    with model._get_session(read_only=True) as session:
        row = session.get(Instance, instance.sop_instance_uid)
        assert row is not None
        assert row.pixel_phi == "Left, Right"


def test_collect_series_view_pixel_phi_texts() -> None:
    viewer = MagicMock()
    viewer.overlay_data = {
        0: OverlayData(
            ocr_texts=[
                OCRText(text="  A ", top_left=(0, 0), bottom_right=(1, 1), prob=0.9),
                OCRText(text="B", top_left=(2, 2), bottom_right=(3, 3), prob=0.8),
            ]
        ),
        1: OverlayData(ocr_texts=[]),
        2: OverlayData(
            ocr_texts=[OCRText(text="A", top_left=(0, 0), bottom_right=(1, 1), prob=0.9)],
            user_rects=[UserRectangle(top_left=(0, 0), bottom_right=(5, 5))],
        ),
    }

    assert collect_series_view_pixel_phi_texts(viewer) == {0: ["A", "B"], 2: ["A"]}


@patch("anonymizer.controller.ai.remove_pixel_phi.apply_instance_pixel_phi_for_dcm")
def test_apply_series_view_pixel_phi_skips_projection_frames(mock_apply: MagicMock) -> None:
    slice_paths = [Path("/tmp/s0.dcm"), Path("/tmp/s1.dcm")]
    texts_by_frame = {0: ["proj"], 3: ["slice0"], 4: ["slice1"]}
    anon_model = MagicMock()

    apply_series_view_pixel_phi(
        anon_model,
        slice_paths,
        texts_by_frame,
        projection_frame_count=3,
    )

    assert mock_apply.call_count == 2
    mock_apply.assert_any_call(anon_model, slice_paths[0], ["slice0"])
    mock_apply.assert_any_call(anon_model, slice_paths[1], ["slice1"])
