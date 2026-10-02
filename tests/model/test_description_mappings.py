"""Tests for per-project description mapping memory."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydicom import Dataset

from anonymizer.model.anonymizer import AnonymizerModel
from tests.opened_anonymizer_model import opened_anonymizer_model

TEST_DB_DIR = Path(__file__).parent / ".test_db"
TEST_DB_FILE = TEST_DB_DIR / "description_mappings_test.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_FILE}"


@pytest.fixture(scope="function")
def anonymizer_model():
    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()
    TEST_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with opened_anonymizer_model(TEST_DB_URL) as model:
        yield model


@pytest.fixture
def mock_dataset1():
    ds = Dataset()
    ds.PatientID = "123456"
    ds.PatientName = "Doe^John"
    ds.PatientSex = "M"
    ds.PatientBirthDate = "19800101"
    ds.EthnicGroup = "Hispanic"
    ds.StudyInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.1"
    ds.AccessionNumber = "ACC123456"
    ds.SeriesInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.2"
    ds.SOPInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.3"
    ds.Modality = "CT"
    ds.StudyDescription = "Chest CT Scan"
    ds.SeriesDescription = "Chest CT Scan Contrast"
    ds.StudyDate = "20230101"
    return ds


def test_description_mapping_upsert_lookup_delete(
    anonymizer_model: AnonymizerModel, mock_dataset1: Dataset
) -> None:
    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_offset_from_hash=0)

    assert anonymizer_model.upsert_description_mapping(
        kind="series",
        original="chest ax porto venous",
        harmonized="CT Chest Ax PortVen",
        modality="CT",
    )
    hit = anonymizer_model.lookup_description_mapping(
        kind="series",
        original="Chest Ax Porto Venous",
        modality="CT",
    )
    assert hit is not None
    assert hit.harmonized_description == "CT Chest Ax PortVen"
    assert hit.origin == "Manual"
    assert hit.similarity >= 0.90

    rows = anonymizer_model.list_description_mappings(kind="series")
    assert len(rows) == 1
    assert rows[0].origin == "Manual"
    assert anonymizer_model.delete_description_mapping(rows[0].mapping_pk) is True
    assert anonymizer_model.list_description_mappings(kind="series") == []


def test_study_mapping_requires_loinc(anonymizer_model: AnonymizerModel) -> None:
    assert (
        anonymizer_model.upsert_description_mapping(
            kind="study",
            original="CT CHEST",
            harmonized="CT Chest",
            modality="CT",
        )
        is False
    )
    assert anonymizer_model.upsert_description_mapping(
        kind="study",
        original="CHEST CT W/O",
        harmonized="CT Chest",
        modality="CT",
        loinc="24627-2",
    )
    hit = anonymizer_model.lookup_description_mapping(
        kind="study",
        original="chest ct w/o",
        modality="CT",
    )
    assert hit is not None
    assert hit.loinc == "24627-2"
    assert hit.harmonized_description == "CT Chest"


def test_upsert_rejects_identical_strings(anonymizer_model: AnonymizerModel) -> None:
    """Do not store identity mappings (same text after normalize), study or series."""
    assert (
        anonymizer_model.upsert_description_mapping(
            kind="series",
            original="CT Chest Ax",
            harmonized="ct  chest  ax",
            modality="CT",
        )
        is False
    )
    assert (
        anonymizer_model.upsert_description_mapping(
            kind="study",
            original="CT Chest",
            harmonized="ct chest",
            modality="CT",
            loinc="24627-2",
        )
        is False
    )
    assert anonymizer_model.list_description_mappings() == []


def test_description_mapping_origin_ai_process(anonymizer_model: AnonymizerModel) -> None:
    """Origin stores Manual or a succinct AI model/process label."""
    assert anonymizer_model.upsert_description_mapping(
        kind="series",
        original="chest ax",
        harmonized="CT Chest Ax",
        modality="CT",
        origin="TS 1.5mm+brain",
    )
    hit = anonymizer_model.lookup_description_mapping(
        kind="series",
        original="chest ax",
        modality="CT",
    )
    assert hit is not None
    assert hit.origin == "TS 1.5mm+brain"
    assert hit.harmonized_description == "CT Chest Ax"


def test_remember_series_skips_blank_original(
    anonymizer_model: AnonymizerModel, mock_dataset1: Dataset
) -> None:
    """Blank sticky SeriesDescription must not create a series mapping."""
    mock_dataset1.SeriesDescription = ""
    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_offset_from_hash=0)
    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    series_uid = phi.studies[0].series[0].anon_series_uid
    assert (
        anonymizer_model.remember_series_description_mapping(
            series_uid=series_uid,
            modality="CT",
            harmonized="CT Head Ax",
            origin="TS 1.5mm+brain",
        )
        is False
    )
    assert anonymizer_model.list_description_mappings() == []



def test_sticky_description_after_harmonize(
    anonymizer_model: AnonymizerModel, mock_dataset1: Dataset
) -> None:
    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_offset_from_hash=0)
    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    series = phi.studies[0].series[0]
    original = series.description
    assert anonymizer_model.set_series_harmonized_description(series.anon_series_uid, "CT Head")
    assert anonymizer_model.get_series_description(series.anon_series_uid) == original
    assert anonymizer_model.get_series_harmonized_description(series.anon_series_uid) == "CT Head"
