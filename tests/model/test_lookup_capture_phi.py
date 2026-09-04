"""Tests for lookup-aware capture_phi and Study.anon_date_delta."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from pydicom import Dataset

from anonymizer.model.anonymizer import AnonymizerModel, LookupPatient
from tests.controller.dicom.support.test_nodes import TEST_SITEID, TEST_UIDROOT
from tests.paths import DEFAULT_ANONYMIZER_SCRIPT

TEST_DB_DIALECT = "sqlite"
TEST_DB_NAME = "anonymizer_lookup_capture_test.db"
TEST_DB_DIR = Path(__file__).parent / ".test_db"
TEST_DB_FILE = TEST_DB_DIR / TEST_DB_NAME
TEST_DB_URL = f"{TEST_DB_DIALECT}:///{TEST_DB_FILE}"


@pytest.fixture(scope="function")
def anonymizer_model() -> AnonymizerModel:
    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()

    TEST_DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    return AnonymizerModel(
        site_id=TEST_SITEID,
        uid_root=TEST_UIDROOT,
        script_path=DEFAULT_ANONYMIZER_SCRIPT,
        db_url=TEST_DB_URL,
    )


@pytest.fixture
def mock_dataset() -> Dataset:
    ds = Dataset()
    ds.PatientID = "123456"
    ds.PatientName = "Doe^John"
    ds.StudyDate = "20200101"
    ds.StudyInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.1"
    ds.AccessionNumber = "ACC123456"
    ds.SeriesInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.2"
    ds.SOPInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.3"
    ds.Modality = "CT"
    return ds


def _enable_lookup(model: AnonymizerModel, rows: list[LookupPatient]) -> None:
    model._lookup_required = True
    model.replace_lookup_patients(rows)


def test_capture_phi_non_lookup_uses_hash_date_offset(anonymizer_model: AnonymizerModel, mock_dataset: Dataset) -> None:
    hash_offset = 42
    _, _, _, date_offset = anonymizer_model.capture_phi(
        source="pytest", ds=mock_dataset, date_offset_from_hash=hash_offset
    )

    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset.PatientID)
    assert phi is not None
    study = phi.studies[0]
    assert date_offset == hash_offset
    assert study.anon_date_delta == hash_offset


def test_capture_phi_lookup_with_date_offset_uses_lookup_value(
    anonymizer_model: AnonymizerModel, mock_dataset: Dataset
) -> None:
    _enable_lookup(
        anonymizer_model,
        [LookupPatient(patient_id="123456", anon_patient_id="LOOKUP-001", date_offset=127)],
    )

    _, anon_ptid, _, date_offset = anonymizer_model.capture_phi(
        source="pytest", ds=mock_dataset, date_offset_from_hash=42
    )

    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset.PatientID)
    assert phi is not None
    study = phi.studies[0]
    assert anon_ptid == "LOOKUP-001"
    assert phi.date_offset == 127
    assert date_offset == 127
    assert study.anon_date_delta == 127


def test_capture_phi_lookup_without_date_offset_falls_back_to_hash(
    anonymizer_model: AnonymizerModel, mock_dataset: Dataset
) -> None:
    _enable_lookup(
        anonymizer_model,
        [LookupPatient(patient_id="123456", anon_patient_id="LOOKUP-001", date_offset=None)],
    )
    hash_offset = 55

    _, _, _, date_offset = anonymizer_model.capture_phi(
        source="pytest", ds=mock_dataset, date_offset_from_hash=hash_offset
    )

    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset.PatientID)
    assert phi is not None
    study = phi.studies[0]
    assert phi.date_offset is None
    assert date_offset == hash_offset
    assert study.anon_date_delta == hash_offset


def test_capture_phi_second_study_reuses_phi_date_offset(
    anonymizer_model: AnonymizerModel, mock_dataset: Dataset
) -> None:
    _enable_lookup(
        anonymizer_model,
        [LookupPatient(patient_id="123456", anon_patient_id="LOOKUP-001", date_offset=127)],
    )

    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset, date_offset_from_hash=42)

    second_study = deepcopy(mock_dataset)
    second_study.StudyInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957064.4"
    second_study.SeriesInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957064.5"
    second_study.SOPInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957064.6"

    _, _, _, date_offset = anonymizer_model.capture_phi(
        source="pytest", ds=second_study, date_offset_from_hash=99
    )

    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset.PatientID)
    assert phi is not None
    assert len(phi.studies) == 2
    studies_by_uid = {study.study_uid: study for study in phi.studies}
    assert studies_by_uid[second_study.StudyInstanceUID].anon_date_delta == 127
    assert date_offset == 127


def test_capture_phi_lookup_miss_raises_not_found(anonymizer_model: AnonymizerModel, mock_dataset: Dataset) -> None:
    anonymizer_model._lookup_required = True

    with pytest.raises(KeyError, match="123456"):
        anonymizer_model.capture_phi(source="pytest", ds=mock_dataset, date_offset_from_hash=0)


def test_capture_phi_existing_study_returns_stored_date_delta(
    anonymizer_model: AnonymizerModel, mock_dataset: Dataset
) -> None:
    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset, date_offset_from_hash=33)

    _, _, _, date_offset = anonymizer_model.capture_phi(
        source="pytest", ds=mock_dataset, date_offset_from_hash=99
    )

    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset.PatientID)
    assert phi is not None
    assert phi.studies[0].anon_date_delta == 33
    assert date_offset == 33


def test_load_script_sets_lookup_required(anonymizer_model: AnonymizerModel, tmp_path: Path) -> None:
    assert anonymizer_model._lookup_required is False

    lookup_script = tmp_path / "lookup.script"
    lookup_script.write_text(
        '<?xml version="1.0"?>\n<anonymizer-script>\n'
        '  <e t="00100020">@lookup(this,ptid)</e>\n'
        '  <e t="00080020">@lookup(this,dateoffset)</e>\n'
        "</anonymizer-script>\n",
        encoding="utf-8",
    )
    anonymizer_model.reload_script(lookup_script)

    assert anonymizer_model._lookup_required is True
