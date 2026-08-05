"""End-to-end pixel PHI tests using synthetic CT with burnt-in sample annotations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pydicom
import pytest

from anonymizer.controller.ai_batch_process import AiBatchAlgorithm, _apply_remove_pixel_phi_series
from anonymizer.controller.remove_pixel_phi import (
    PixelPhiRemovalMode,
    detect_text,
    remove_pixel_phi,
)
from anonymizer.model.anonymizer import AnonymizerModel, Instance
from tests.controller.dicom.support.test_nodes import TEST_SITEID, TEST_UIDROOT
from tests.controller.support.pixel_phi_test_support import (
    build_synthetic_chest_ct_series_with_two_phi_slices,
    easyocr_results_for_default_phi,
    easyocr_results_for_lines,
    register_series_with_anonymizer,
)
from tests.controller.tseg.support.synthetic_ct import (
    DEFAULT_BURNED_IN_PHI_LINES,
    apply_burned_in_phi_to_dicom,
    build_synthetic_ct_series_with_burned_in_phi,
    build_synthetic_single_slice_ct_series,
    list_dcm_files,
)


@pytest.fixture
def anonymizer_model(tmp_path: Path) -> AnonymizerModel:
    db_path = tmp_path / "pixel_phi_synthetic.db"
    return AnonymizerModel(
        site_id=TEST_SITEID,
        uid_root=TEST_UIDROOT,
        script_path=Path("src/anonymizer/assets/scripts/default-anonymizer.script"),
        db_url=f"sqlite:///{db_path}",
    )


class _DirectOcrService:
    """Run remove_pixel_phi on the calling thread (no OCR worker)."""

    def process_dicom_path(self, path: Path, **kwargs):
        return remove_pixel_phi(path, MagicMock(), whitelist=[], **kwargs)


def _phi_slice_path(series_dir: Path, *, burn_slice_index: int = 0) -> Path:
    return list_dcm_files(series_dir)[burn_slice_index]


def _overlay_region_changed(before: np.ndarray, after: np.ndarray) -> bool:
    region = (slice(20, 120), slice(20, 280))
    return not np.array_equal(before[region], after[region])


@patch("anonymizer.controller.remove_pixel_phi._easyocr_readtext")
def test_remove_pixel_phi_detects_and_blackouts_synthetic_phi(
    mock_readtext: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_ct_series_with_burned_in_phi(tmp_path / "phi_ct")
    dcm_path = _phi_slice_path(series_dir)
    before = pydicom.dcmread(dcm_path).pixel_array.copy()
    overlay = (slice(20, 120), slice(20, 280))

    mock_readtext.return_value = easyocr_results_for_default_phi()

    modified, texts, pixels_changed = remove_pixel_phi(
        dcm_path,
        MagicMock(),
        whitelist=[],
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )

    assert modified is True
    assert texts == list(DEFAULT_BURNED_IN_PHI_LINES)
    assert pixels_changed > 0

    after = pydicom.dcmread(dcm_path).pixel_array
    assert _overlay_region_changed(before, after)
    assert np.count_nonzero(before[overlay] > 2500) > np.count_nonzero(after[overlay] > 2500)


@patch("anonymizer.controller.remove_pixel_phi._easyocr_readtext")
def test_detect_text_returns_filtered_phi_from_synthetic_ct(
    mock_readtext: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_single_slice_ct_series(tmp_path / "single")
    apply_burned_in_phi_to_dicom(_phi_slice_path(series_dir))
    pixels = pydicom.dcmread(_phi_slice_path(series_dir)).pixel_array
    display = np.clip(pixels.astype(np.int32), 0, None).astype(np.uint8)

    mock_readtext.return_value = easyocr_results_for_default_phi() + [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], ";", 0.95),
    ]

    results = detect_text(display, MagicMock(), whitelist=[])

    assert results is not None
    assert [item.text for item in results] == list(DEFAULT_BURNED_IN_PHI_LINES)


@patch("anonymizer.controller.remove_pixel_phi._easyocr_readtext")
def test_batch_pixel_phi_pipeline_updates_model_and_phi_index(
    mock_readtext: MagicMock,
    anonymizer_model: AnonymizerModel,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_ct_series_with_burned_in_phi(tmp_path / "batch_phi")
    phi_path = _phi_slice_path(series_dir)
    before_phi = pydicom.dcmread(phi_path).pixel_array.copy()
    overlay = (slice(20, 120), slice(20, 280))
    anon_series_uid, _ = register_series_with_anonymizer(series_dir, anonymizer_model)
    slice_count = len(list_dcm_files(series_dir))

    mock_readtext.side_effect = [easyocr_results_for_default_phi()] + [[]] * (slice_count - 1)

    outcome = _apply_remove_pixel_phi_series(
        series_dir,
        anon_model=anonymizer_model,
        ocr_service=_DirectOcrService(),
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )

    assert outcome.status == "ok"
    assert outcome.algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI

    ds = pydicom.dcmread(phi_path)
    phi = anonymizer_model.get_phi_by_anon_patient_id(ds.PatientID)
    assert phi is not None
    study = next(item for item in phi.studies if item.anon_study_uid == ds.StudyInstanceUID)
    series = next(item for item in study.series if item.anon_series_uid == anon_series_uid)
    instance = next(item for item in series.instances if item.anon_sop_instance_uid == ds.SOPInstanceUID)

    expected_digest = "SMITH^JOHN, 01-Jan-2024"
    with anonymizer_model._get_session(read_only=True) as session:
        row = session.get(Instance, instance.sop_instance_uid)
        assert row is not None
        assert row.pixel_phi == expected_digest

    records = anonymizer_model.get_phi_index()
    assert records is not None
    record = next(item for item in records if item.anon_study_uid == study.anon_study_uid)
    assert record.pixel_phi_removed is True
    assert record.pixel_phi == expected_digest

    after_phi = pydicom.dcmread(phi_path).pixel_array
    assert np.count_nonzero(before_phi[overlay] > 2500) > np.count_nonzero(after_phi[overlay] > 2500)


@patch("anonymizer.controller.remove_pixel_phi._easyocr_readtext")
def test_batch_pixel_phi_leaves_unmarked_slices_unchanged(
    mock_readtext: MagicMock,
    anonymizer_model: AnonymizerModel,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_ct_series_with_burned_in_phi(tmp_path / "mixed")
    register_series_with_anonymizer(series_dir, anonymizer_model)

    paths = list_dcm_files(series_dir)
    clean_path = paths[1]
    clean_before = pydicom.dcmread(clean_path).pixel_array.copy()

    mock_readtext.return_value = []

    outcome = _apply_remove_pixel_phi_series(
        series_dir,
        anon_model=anonymizer_model,
        ocr_service=_DirectOcrService(),
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )

    assert outcome.status == "complete"
    assert "No burnt-in text detected" in outcome.message
    assert np.array_equal(pydicom.dcmread(clean_path).pixel_array, clean_before)


@patch("anonymizer.controller.remove_pixel_phi._easyocr_readtext")
def test_phi_index_digest_deduplicates_across_instances(
    mock_readtext: MagicMock,
    anonymizer_model: AnonymizerModel,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_chest_ct_series_with_two_phi_slices(tmp_path / "dedupe")
    register_series_with_anonymizer(series_dir, anonymizer_model)

    slice_count = len(list_dcm_files(series_dir))
    mock_readtext.side_effect = [
        easyocr_results_for_lines(("SMITH^JOHN", "01-Jan-2024")),
        easyocr_results_for_lines(("SMITH^JOHN", "ACC12345")),
        *([[]] * (slice_count - 2)),
    ]

    outcome = _apply_remove_pixel_phi_series(
        series_dir,
        anon_model=anonymizer_model,
        ocr_service=_DirectOcrService(),
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )

    assert outcome.status == "ok"
    records = anonymizer_model.get_phi_index()
    assert records is not None
    assert records[0].pixel_phi == "SMITH^JOHN, 01-Jan-2024, ACC12345"
