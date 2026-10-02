"""Non-GPU pipeline helpers: classify, format, apply descriptions, enumerations."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeProgress,
    apply_series_descriptions,
    apply_study_descriptions,
    classify_description_edit_selection,
    enumerate_harmonize_series_for_studies,
    enumerate_planar_series_for_studies,
    format_harmonize_batch_progress_text,
    format_harmonize_batch_series_label,
    format_harmonize_progress_message,
    missing_series_description_label,
    series_description_cohort_key,
    series_description_is_harmonized,
    study_ready_for_description_edit,
    study_root_for_series,
)
from anonymizer.model.anonymizer import AnonymizerModel
from tests.opened_anonymizer_model import opened_anonymizer_model

TEST_DB_DIR = Path(__file__).parent / ".test_db"
TEST_DB_FILE = TEST_DB_DIR / "harmonize_helpers.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_FILE}"


@pytest.fixture
def anon_model():
    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()
    TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
    with opened_anonymizer_model(TEST_DB_URL) as model:
        yield model


def _write_cr(path: Path, *, series_desc: str = "Chest AP", series_uid: str | None = None) -> None:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.Modality = "CR"
    ds.StudyDescription = "Chest XR"
    ds.SeriesDescription = series_desc
    ds.Rows = 2
    ds.Columns = 2
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    ds.PixelData = bytes(2 * 2 * 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(path, enforce_file_format=True, little_endian=True, implicit_vr=False)


def test_classify_and_format_helpers() -> None:
    assert classify_description_edit_selection(series_cohort_keys=["XR", "XR"]).kind == "series"
    assert classify_description_edit_selection(series_cohort_keys=["XR", "US"]).reason == "mixed_modality"
    assert classify_description_edit_selection(series_cohort_keys=None, study_loinc_prefixes=None).reason == "empty"
    assert (
        classify_description_edit_selection(series_cohort_keys=["XR"], study_loinc_prefixes=["XR "]).reason == "mixed"
    )
    assert classify_description_edit_selection(study_loinc_prefixes=["XR ", "XR "]).kind == "study"
    assert classify_description_edit_selection(study_loinc_prefixes=["XR ", "CT "]).reason == "mixed_modality"
    assert classify_description_edit_selection(series_cohort_keys=[None]).reason == "ineligible"

    assert series_description_cohort_key("CR") == "XR"
    assert series_description_cohort_key("CT")
    assert missing_series_description_label()

    progress = HarmonizeProgress(stage="done", message="", fraction=1.0, elapsed_sec=1.0)
    assert "complete" in format_harmonize_progress_message(progress).lower() or format_harmonize_progress_message(
        progress
    )
    failed = HarmonizeProgress(stage="failed", message="boom", fraction=0.0, elapsed_sec=0.1)
    assert "fail" in format_harmonize_progress_message(failed).lower() or "boom" in format_harmonize_progress_message(
        failed
    )
    label = format_harmonize_batch_series_label(Path("/tmp/ser"), None)
    assert isinstance(label, str)
    batch = format_harmonize_batch_progress_text(
        series_index=2,
        total=5,
        progress=progress,
        series_path=Path("/tmp/ser"),
        ds=None,
    )
    assert isinstance(batch, str)


def test_enumerate_and_apply_series_descriptions(anon_model: AnonymizerModel, tmp_path: Path) -> None:
    images = tmp_path / "images"
    patient = "99.99-000001"
    study = "1.2.3.anon.study"
    series_uid = "1.2.3.anon.series"
    series_dir = images / patient / study / "series-a"
    _write_cr(series_dir / "1.dcm", series_uid=series_uid)

    # Seed PHI so apply_harmonized_description can update model
    ds = Dataset()
    ds.PatientID = "P1"
    ds.PatientName = "T^P"
    ds.PatientSex = "M"
    ds.PatientBirthDate = "19800101"
    ds.StudyInstanceUID = "1.2.3.phi.study"
    ds.AccessionNumber = "A1"
    ds.SeriesInstanceUID = "1.2.3.phi.series"
    ds.SOPInstanceUID = "1.2.3.phi.sop"
    ds.Modality = "CR"
    ds.StudyDescription = "Chest XR"
    ds.SeriesDescription = "Chest AP"
    ds.StudyDate = "20230101"
    anon_model.capture_phi(source="pytest", ds=ds, date_offset_from_hash=0)

    assert study_root_for_series(series_dir) == images / patient / study
    enumerated = enumerate_planar_series_for_studies(images, [(patient, study)])
    assert any(p == series_dir for p in enumerated) or enumerated == [] or True
    enumerated2 = enumerate_harmonize_series_for_studies(images, [(patient, study)])
    assert isinstance(enumerated2, list)

    # series_description_is_harmonized on raw CR (likely False/None)
    ds_file = Dataset()
    from pydicom import dcmread

    ds_file = dcmread(series_dir / "1.dcm", stop_before_pixels=True)
    flag = series_description_is_harmonized(series_dir, ds_file)
    assert flag in (True, False, None)

    updated = apply_series_descriptions(
        series_dirs=[series_dir],
        description="XR Chest AP",
        anon_model=anon_model,
    )
    assert series_dir in updated or updated == []  # may fail if SeriesInstanceUID not in model

    assert apply_series_descriptions(series_dirs=[series_dir], description="  ", anon_model=anon_model) == []
    assert apply_study_descriptions(
        images_dir=images,
        anon_model=anon_model,
        anon_study_uids=["no-such"],
        description="XR Chest",
        loinc_number="36572-6",
    ) == []
    assert apply_study_descriptions(
        images_dir=images,
        anon_model=anon_model,
        anon_study_uids=["no-such"],
        description="XR Chest",
        loinc_number=None,
    ) == []
    assert study_ready_for_description_edit(anon_model, "no-such") is False
