import os
from pathlib import Path

import pydicom
import pytest
from pydicom import Dataset
from pydicom.data import get_testdata_file

from src.anonymizer.model.anonymizer import PHI, UID, AnonymizerModel, Series, Study
from tests.controller.dicom_test_files import ct_small_filename, mr_brain_filename

TEST_DB_DIALECT = "sqlite"  # Database dialect
TEST_DB_NAME = "anonymizer_test.db"  # Name of the test database file
TEST_DB_DIR = Path(__file__).parent / ".test_dbs"  # In tests/model/.test_dbs
TEST_DB_FILE = TEST_DB_DIR / TEST_DB_NAME
TEST_DB_URL = f"{TEST_DB_DIALECT}:///{TEST_DB_FILE}"


@pytest.fixture
def model_fixture() -> AnonymizerModel:
    """
    Provides a fresh, initialized AnonymizerModel instance using an
    in-memory SQLite database for each test.
    """
    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()  # Delete old DB file to ensure fresh start

    # Ensure directory exists
    TEST_DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    model = AnonymizerModel(
        site_id="TEST_SITE",
        uid_root="1.2.3.4.5",
        script_path=Path("src/anonymizer/assets/scripts/default-anonymizer.script"),
        db_url=TEST_DB_URL,  # db_url = "sqlite:///:memory:"
    )

    return model


@pytest.fixture
def mock_dataset1():
    ds = Dataset()
    ds.PatientID = "123456"
    ds.PatientName = "Doe^John"
    ds.PatientSex = "M"
    ds.PatientBirthDate = "19800101"
    ds.EthnicGroup = "Hispanic"
    ds.StudyInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.1"
    ds.SeriesInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.2"
    ds.SOPInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.3"
    ds.Modality = "CT"
    ds.SeriesDescription = "Chest CT Scan"
    return ds


@pytest.fixture
def mock_dataset2():
    ds = Dataset()
    ds.PatientID = "654321"
    ds.PatientName = "Davis^Susan"
    ds.PatientSex = "F"
    ds.PatientBirthDate = "19601230"
    ds.EthnicGroup = "Caucasian"
    ds.StudyInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957064.4"
    ds.SeriesInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957064.5"
    ds.SOPInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957064.6"
    ds.Modality = "MR"
    ds.SeriesDescription = "Brain Contrast MRI"
    return ds


def test_anonymizer_model_initialization(anonymizer_model: AnonymizerModel):
    assert anonymizer_model is not None
    assert anonymizer_model._get_class_name() == "AnonymizerModel"

    with anonymizer_model._get_session() as session:
        assert session.bind is not None
        assert session.bind.engine is not None
        assert anonymizer_model._db_url == TEST_DB_URL
        assert session.bind.engine.url.drivername == TEST_DB_DIALECT
        assert session.bind.engine.url.database is not None
        assert session.bind.engine.url.database.split("/")[-1] == TEST_DB_NAME
        default_phi = session.get(PHI, "")
        assert default_phi is not None
        assert anonymizer_model._tag_keep is not None


def test_capture_phi_creates_phi(anonymizer_model, mock_dataset1):
    anonymizer_model.capture_phi(source="TestSource", ds=mock_dataset1, date_delta=0)

    with anonymizer_model.get_session() as session:
        phi_record = session.query(PHI).filter_by(patient_id="123456").first()
        assert phi_record is not None
        assert phi_record.patient_name == "Doe^John"
        assert phi_record.sex == "M"
        assert phi_record.dob == "19800101"
        assert phi_record.ethnic_group == "Hispanic"


def test_capture_phi_creates_study(anonymizer_model, mock_dataset):
    """Test that capture_phi creates a Study record when it does not exist."""
    anonymizer_model.capture_phi(source="TestSource", ds=mock_dataset, date_delta=10)

    with anonymizer_model.get_session() as session:
        study_record = session.query(Study).filter_by(study_uid=mock_dataset.StudyInstanceUID).first()
        assert study_record is not None
        assert study_record.accession_number is None  # Since accession number is not in dataset
        assert study_record.study_uid == mock_dataset.StudyInstanceUID
        assert study_record.anon_date_delta == 10
        assert study_record.source == "TestSource"


def test_capture_phi_creates_series(anonymizer_model, mock_dataset):
    """Test that capture_phi creates a Series record when it does not exist."""
    anonymizer_model.capture_phi(source="TestSource", ds=mock_dataset, date_delta=0)

    with anonymizer_model.get_session() as session:
        series_record = session.query(Series).filter_by(series_uid=mock_dataset.SeriesInstanceUID).first()
        assert series_record is not None
        assert series_record.series_desc == "Chest CT Scan"
        assert series_record.modality == "CT"
        assert series_record.instance_count == 1


def test_capture_phi_ct_small(anonymizer_model):
    """Tests that capture_phi correctly inserts PHI, Study, and Series data from a DICOM file."""

    # Load test DICOM dataset
    dcm_file_path = str(get_testdata_file(ct_small_filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)
    ds = pydicom.dcmread(dcm_file_path)

    anonymizer_model.add_default()

    # Capture PHI
    anonymizer_model.capture_phi(source="TEST_SOURCE", ds=ds, date_delta=5)

    # Verify database entries
    with anonymizer_model.get_session() as session:
        # Check PHI
        phi = session.query(PHI).filter_by(patient_id=ds.PatientID).first()
        assert phi is not None, "PHI record not created"
        assert phi.anon_patient_id.startswith("TEST_SITE-"), "Anon patient ID incorrect"

        # Check Study
        study = session.query(Study).filter_by(study_uid=ds.StudyInstanceUID).first()
        assert study is not None, "Study record not created"
        assert study.phi_pk == phi.phi_pk, "Study not linked to correct PHI"

        # Check Series
        series = session.query(Series).filter_by(series_uid=ds.SeriesInstanceUID).first()
        assert series is not None, "Series record not created"
        assert series.study_uid == study.study_uid, "Series not linked to correct Study"

        # Check Series instance count
        assert series.instance_count == 1

        # Check UID mapping
        uid = session.query(UID).filter_by(phi_uid=ds.SOPInstanceUID).first()
        assert uid is not None, "UID mapping not created"
        assert uid.anon_uid.startswith("1.2.3.TEST_SITE."), "Anonymized UID incorrect"


def test_capture_phi_mr_brain(anonymizer_model):
    """Tests that capture_phi correctly inserts PHI, Study, and Series data from a DICOM file."""

    # Load test DICOM dataset
    dcm_file_path = str(get_testdata_file(mr_brain_filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)
    ds = pydicom.dcmread(dcm_file_path)

    anonymizer_model.add_default()

    # Capture PHI
    anonymizer_model.capture_phi(source="TEST_SOURCE", ds=ds, date_delta=5)

    # Verify database entries
    with anonymizer_model.get_session() as session:
        # Check PHI
        phi = session.query(PHI).filter_by(patient_id=ds.PatientID).first()
        assert phi is not None, "PHI record not created"
        assert phi.anon_patient_id.startswith("TEST_SITE-"), "Anon patient ID incorrect"

        # Check Study
        study = session.query(Study).filter_by(study_uid=ds.StudyInstanceUID).first()
        assert study is not None, "Study record not created"
        assert study.phi_pk == phi.phi_pk, "Study not linked to correct PHI"

        # Check Series
        series = session.query(Series).filter_by(series_uid=ds.SeriesInstanceUID).first()
        assert series is not None, "Series record not created"
        assert series.study_uid == study.study_uid, "Series not linked to correct Study"

        # Check Series instance count
        assert series.instance_count == 1

        # Check UID mapping
        uid = session.query(UID).filter_by(phi_uid=ds.SOPInstanceUID).first()
        assert uid is not None, "UID mapping not created"
        assert uid.anon_uid.startswith("1.2.3.TEST_SITE."), "Anonymized UID incorrect"
