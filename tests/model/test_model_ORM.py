from pathlib import Path

import pytest
from pydicom import Dataset
from pydicom.data import get_testdata_file

from src.anonymizer.model.anonymizer import PHI, AnonymizerModel, Series, Study
from tests.controller.dicom.support.test_files import ct_small_filename, mr_brain_filename
from tests.controller.dicom.support.test_nodes import (
    TEST_SITEID,
    TEST_UIDROOT,
)

TEST_DB_DIALECT = "sqlite"  # Database dialect
TEST_DB_NAME = "anonymizer_model_test.db"  # Name of the test database file
TEST_DB_DIR = Path(__file__).parent / ".test_db"
TEST_DB_FILE = TEST_DB_DIR / TEST_DB_NAME
TEST_DB_URL = f"{TEST_DB_DIALECT}:///{TEST_DB_FILE}"


@pytest.fixture(scope="function")
def anonymizer_model() -> AnonymizerModel:
    """
    Provides a fresh, initialized AnonymizerModel instance using an
    in-memory SQLite database for each test.
    """
    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()  # Delete old DB file to ensure fresh start

    # Ensure directory exists
    TEST_DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    model = AnonymizerModel(
        site_id=TEST_SITEID,
        uid_root=TEST_UIDROOT,
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
    ds.AccessionNumber = "ACC123456"
    ds.SeriesInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.2"
    ds.SOPInstanceUID = "1.2.840.113619.2.5.1762583153.17482.978957063.3"
    ds.Modality = "CT"
    ds.StudyDescription = "Chest CT Scan"
    ds.SeriesDescription = "Chest CT Scan Contrast"
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
    ds.StudyDescription = "Brain MRI"
    ds.SeriesDescription = "Brain Contrast MRI"
    return ds


def test_anonymizer_model_initialization(anonymizer_model: AnonymizerModel):
    assert anonymizer_model is not None
    assert anonymizer_model._get_class_name() == "AnonymizerModel"

    with anonymizer_model._get_session(read_only=True) as session:
        assert session.bind is not None
        assert session.bind.engine is not None
        assert anonymizer_model._db_url == TEST_DB_URL
        assert session.bind.engine.url.drivername == TEST_DB_DIALECT
        assert session.bind.engine.url.database is not None
        assert session.bind.engine.url.database.split("/")[-1] == TEST_DB_NAME
        assert anonymizer_model._tag_keep is not None

    # Ensure default PHI entry has been created:
    default_phi = anonymizer_model.get_phi_by_phi_patient_id(AnonymizerModel.DEFAULT_PHI_PATIENT_ID_PK_VALUE)
    assert default_phi is not None
    assert default_phi.anon_patient_id == TEST_SITEID + "-000000"


def test_capture_phi_with_mock_ds1(anonymizer_model: AnonymizerModel, mock_dataset1: Dataset):
    # Store:
    ptid, anon_ptid, acc_no = anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_delta=0)
    assert ptid == mock_dataset1.PatientID
    assert anon_ptid == TEST_SITEID + "-000001"
    assert acc_no
    assert len(acc_no) == 18

    # Lookup
    phi: PHI | None = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    assert phi.patient_name == mock_dataset1.PatientName
    assert phi.patient_id == mock_dataset1.PatientID
    assert phi.anon_patient_id == TEST_SITEID + "-000001"
    assert phi.sex == mock_dataset1.PatientSex
    assert phi.dob == mock_dataset1.PatientBirthDate
    assert phi.ethnic_group == mock_dataset1.EthnicGroup
    assert phi.studies is not None
    assert len(phi.studies) == 1
    assert isinstance(phi.studies[0], Study)
    study: Study = phi.studies[0]
    assert study.study_uid == mock_dataset1.StudyInstanceUID
    assert study.description == mock_dataset1.StudyDescription
    assert study.series is not None
    assert len(study.series) == 1
    assert isinstance(study.series[0], Series)
    series: Series = study.series[0]
    assert series.series_uid == mock_dataset1.SeriesInstanceUID
    assert series.modality == mock_dataset1.Modality
    assert series.description == mock_dataset1.SeriesDescription


def test_capture_phi_with_mock_ds2(anonymizer_model: AnonymizerModel, mock_dataset2: Dataset):
    # Store:
    ptid, anon_ptid, anon_acc_no = anonymizer_model.capture_phi(source="pytest", ds=mock_dataset2, date_delta=0)
    assert ptid == mock_dataset2.PatientID
    assert anon_ptid == TEST_SITEID + "-000001"
    assert anon_acc_no is None

    # Lookup
    phi: PHI | None = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset2.PatientID)
    assert phi is not None
    assert phi.patient_name == mock_dataset2.PatientName
    assert phi.patient_id == mock_dataset2.PatientID
    assert phi.anon_patient_id == TEST_SITEID + "-000001"
    assert phi.sex == mock_dataset2.PatientSex
    assert phi.dob == mock_dataset2.PatientBirthDate
    assert phi.ethnic_group == mock_dataset2.EthnicGroup
    assert phi.studies is not None
    assert len(phi.studies) == 1
    assert isinstance(phi.studies[0], Study)
    study: Study = phi.studies[0]
    assert study.study_uid == mock_dataset2.StudyInstanceUID
    assert study.description == mock_dataset2.StudyDescription
    assert study.series is not None
    assert len(study.series) == 1
    assert isinstance(study.series[0], Series)
    series: Series = study.series[0]
    assert series.series_uid == mock_dataset2.SeriesInstanceUID
    assert series.modality == mock_dataset2.Modality
    assert series.description == mock_dataset2.SeriesDescription


def test_capture_phi_with_mock_ds1_and_ds2(
    anonymizer_model: AnonymizerModel, mock_dataset1: Dataset, mock_dataset2: Dataset
):
    # Store:
    ptid1, anon_ptid1, anon_acc_no1 = anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_delta=0)
    assert ptid1 == mock_dataset1.PatientID
    assert anon_ptid1 == TEST_SITEID + "-000001"
    assert anon_acc_no1
    assert len(anon_acc_no1) == 18

    ptid2, anon_ptid2, anon_acc_no2 = anonymizer_model.capture_phi(source="pytest", ds=mock_dataset2, date_delta=0)
    assert ptid2 == mock_dataset2.PatientID
    assert anon_ptid2 == TEST_SITEID + "-000002"
    assert anon_acc_no2 is None

    # Lookup 1
    phi1: PHI | None = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi1 is not None
    assert phi1.patient_name == mock_dataset1.PatientName
    assert phi1.patient_id == mock_dataset1.PatientID
    assert phi1.anon_patient_id == TEST_SITEID + "-000001"
    assert phi1.sex == mock_dataset1.PatientSex
    assert phi1.dob == mock_dataset1.PatientBirthDate
    assert phi1.ethnic_group == mock_dataset1.EthnicGroup
    assert phi1.studies is not None
    assert len(phi1.studies) == 1
    assert isinstance(phi1.studies[0], Study)
    study: Study = phi1.studies[0]
    assert study.study_uid == mock_dataset1.StudyInstanceUID
    assert study.description == mock_dataset1.StudyDescription
    assert study.series is not None
    assert len(study.series) == 1
    assert isinstance(study.series[0], Series)
    series: Series = study.series[0]
    assert series.series_uid == mock_dataset1.SeriesInstanceUID
    assert series.modality == mock_dataset1.Modality
    assert series.description == mock_dataset1.SeriesDescription

    # Lookup 2
    phi2: PHI | None = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset2.PatientID)
    assert phi2 is not None
    assert phi2.patient_name == mock_dataset2.PatientName
    assert phi2.patient_id == mock_dataset2.PatientID
    assert phi2.anon_patient_id == TEST_SITEID + "-000002"
    assert phi2.sex == mock_dataset2.PatientSex
    assert phi2.dob == mock_dataset2.PatientBirthDate
    assert phi2.ethnic_group == mock_dataset2.EthnicGroup
    assert phi2.studies is not None
    assert len(phi2.studies) == 1
    assert isinstance(phi2.studies[0], Study)
    study: Study = phi2.studies[0]
    assert study.study_uid == mock_dataset2.StudyInstanceUID
    assert study.description == mock_dataset2.StudyDescription
    assert study.series is not None
    assert len(study.series) == 1
    assert isinstance(study.series[0], Series)
    series: Series = study.series[0]
    assert series.series_uid == mock_dataset2.SeriesInstanceUID
    assert series.modality == mock_dataset2.Modality
    assert series.description == mock_dataset2.SeriesDescription


def test_capture_phi_with_ct_small_filename(anonymizer_model: AnonymizerModel):
    # Load:
    ct1_ds = get_testdata_file(ct_small_filename, read=True)
    assert isinstance(ct1_ds, Dataset)
    assert ct1_ds
    assert ct1_ds.PatientID
    # Store:
    ptid1, anon_ptid1, anon_acc_no1 = anonymizer_model.capture_phi(source="pytest", ds=ct1_ds, date_delta=0)
    assert ptid1 == ct1_ds.PatientID
    assert anon_ptid1 == TEST_SITEID + "-000001"
    assert anon_acc_no1 is None
    # Lookup:
    phi1: PHI | None = anonymizer_model.get_phi_by_phi_patient_id(ct1_ds.PatientID)
    assert phi1 is not None
    assert phi1.patient_name == ct1_ds.PatientName
    assert phi1.patient_id == ct1_ds.PatientID
    assert phi1.anon_patient_id == TEST_SITEID + "-000001"
    assert phi1.sex == ct1_ds.PatientSex
    assert phi1.dob == ct1_ds.PatientBirthDate
    assert phi1.studies is not None
    assert len(phi1.studies) == 1
    assert isinstance(phi1.studies[0], Study)
    study: Study = phi1.studies[0]
    assert study.study_uid == ct1_ds.StudyInstanceUID
    if hasattr(ct1_ds, "StudyDescription"):
        assert study.description == ct1_ds.StudyDescription
    assert study.series is not None
    assert len(study.series) == 1
    assert isinstance(study.series[0], Series)
    series: Series = study.series[0]
    assert series.series_uid == ct1_ds.SeriesInstanceUID
    assert series.modality == ct1_ds.Modality
    if hasattr(ct1_ds, "SeriesDescription"):
        assert series.description == ct1_ds.SeriesDescription


def test_capture_phi_with_mr_brain_filename(anonymizer_model: AnonymizerModel):
    # Load:
    mr1_ds = get_testdata_file(mr_brain_filename, read=True)
    assert isinstance(mr1_ds, Dataset)
    assert mr1_ds
    assert mr1_ds.PatientID
    # Store:
    ptid1, anon_ptid1, anon_acc_no1 = anonymizer_model.capture_phi(source="pytest", ds=mr1_ds, date_delta=0)
    assert ptid1 == mr1_ds.PatientID
    assert anon_ptid1 == TEST_SITEID + "-000001"
    assert anon_acc_no1
    assert len(anon_acc_no1) == 18
    # Lookup:
    phi1: PHI | None = anonymizer_model.get_phi_by_phi_patient_id(mr1_ds.PatientID)
    assert phi1 is not None
    assert phi1.patient_name == mr1_ds.PatientName
    assert phi1.patient_id == mr1_ds.PatientID
    assert phi1.anon_patient_id == TEST_SITEID + "-000001"
    assert phi1.sex == mr1_ds.PatientSex
    assert phi1.dob == mr1_ds.PatientBirthDate
    assert phi1.studies is not None
    assert len(phi1.studies) == 1
    assert isinstance(phi1.studies[0], Study)
    study: Study = phi1.studies[0]
    assert study.study_uid == mr1_ds.StudyInstanceUID
    if hasattr(mr1_ds, "StudyDescription"):
        assert study.description == mr1_ds.StudyDescription
    assert study.series is not None
    assert len(study.series) == 1
    assert isinstance(study.series[0], Series)
    series: Series = study.series[0]
    assert series.series_uid == mr1_ds.SeriesInstanceUID
    assert series.modality == mr1_ds.Modality
    if hasattr(mr1_ds, "SeriesDescription"):
        assert series.description == mr1_ds.SeriesDescription


def test_capture_phi_with_ct_small_and_mr_brain_filename(anonymizer_model: AnonymizerModel):
    # Load:
    ct1_ds = get_testdata_file(ct_small_filename, read=True)
    assert isinstance(ct1_ds, Dataset)
    assert ct1_ds
    assert ct1_ds.PatientID
    mr1_ds = get_testdata_file(mr_brain_filename, read=True)
    assert isinstance(mr1_ds, Dataset)
    assert mr1_ds
    assert mr1_ds.PatientID
    # Store:
    ptid1, anon_ptid1, anon_acc_no1 = anonymizer_model.capture_phi(source="pytest", ds=ct1_ds, date_delta=10)
    assert ptid1 == ct1_ds.PatientID
    assert anon_ptid1 == TEST_SITEID + "-000001"
    assert anon_acc_no1 is None
    ptid2, anon_ptid2, anon_acc_no2 = anonymizer_model.capture_phi(source="pytest", ds=mr1_ds, date_delta=20)
    assert ptid2 == mr1_ds.PatientID
    assert anon_ptid2 == TEST_SITEID + "-000002"
    assert anon_acc_no2
    assert len(anon_acc_no2) == 18
    # Lookup:
    phi1: PHI | None = anonymizer_model.get_phi_by_phi_patient_id(ct1_ds.PatientID)
    phi2: PHI | None = anonymizer_model.get_phi_by_phi_patient_id(mr1_ds.PatientID)
    assert phi1 is not None
    assert phi1.patient_name == ct1_ds.PatientName
    assert phi1.patient_id == ct1_ds.PatientID
    assert phi2 is not None
    assert phi1.patient_name == ct1_ds.PatientName
    assert phi1.patient_id == ct1_ds.PatientID

    totals = anonymizer_model.get_totals()
    assert totals.patients == 2
    assert totals.studies == 2
    assert totals.series == 2
    assert totals.instances == 2

    assert anonymizer_model.instance_received(ct1_ds.SOPInstanceUID) is True
    assert anonymizer_model.instance_received(mr1_ds.SOPInstanceUID) is True
    assert anonymizer_model.instance_received("non_existent_uid") is False


def test_update_series_description_by_anon_uid(anonymizer_model: AnonymizerModel, mock_dataset1: Dataset):
    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_delta=0)
    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    assert phi.studies is not None
    series = phi.studies[0].series[0]
    assert series.description == mock_dataset1.SeriesDescription

    new_description = "CT Head Neck Without Contrast"
    assert anonymizer_model.update_series_description_by_anon_uid(series.anon_series_uid, new_description) is True

    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    assert phi.studies is not None
    assert phi.studies[0].series[0].description == new_description

    assert anonymizer_model.update_series_description_by_anon_uid("nonexistent-anon-uid", "x") is False


def test_set_series_harmonized_description(anonymizer_model: AnonymizerModel, mock_dataset1: Dataset):
    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_delta=0)
    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    series = phi.studies[0].series[0]
    harmonized = "CT Head Neck Without Contrast"

    records = anonymizer_model.get_phi_index()
    assert records is not None
    assert records[0].harmonize is False

    assert anonymizer_model.set_series_harmonized_description(series.anon_series_uid, harmonized) is True
    assert anonymizer_model.series_is_harmonized(series.anon_series_uid) is True

    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    updated = phi.studies[0].series[0]
    assert updated.description == harmonized
    assert updated.harmonized_description == harmonized

    records = anonymizer_model.get_phi_index()
    assert records is not None
    assert records[0].harmonize is True


def test_get_phi_index_harmonize_false_for_mr_only_study(anonymizer_model: AnonymizerModel, mock_dataset2: Dataset):
    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset2, date_delta=0)

    records = anonymizer_model.get_phi_index()
    assert records is not None
    assert records[0].harmonize is False


def test_set_series_face_blur_algorithm(anonymizer_model: AnonymizerModel, mock_dataset1: Dataset):
    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_delta=0)
    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    series = phi.studies[0].series[0]

    assert anonymizer_model.series_has_face_blur(series.anon_series_uid) is False
    assert anonymizer_model.set_series_face_blur_algorithm(series.anon_series_uid, "gaussian") is True
    assert anonymizer_model.series_has_face_blur(series.anon_series_uid) is True


def test_set_instance_pixel_phi(anonymizer_model: AnonymizerModel, mock_dataset1: Dataset):
    from anonymizer.model.anonymizer import Instance, _format_pixel_phi

    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_delta=0)
    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    instance = phi.studies[0].series[0].instances[0]

    assert _format_pixel_phi(["  foo ", "bar", "foo"]) == "foo, bar"
    assert anonymizer_model.set_instance_pixel_phi(instance.anon_sop_instance_uid, []) is False
    assert anonymizer_model.set_instance_pixel_phi("missing-uid", ["text"]) is False

    texts = ["Patient", "Patient", " Name "]
    assert anonymizer_model.set_instance_pixel_phi(instance.anon_sop_instance_uid, texts) is True

    with anonymizer_model._get_session(read_only=True) as session:
        row = session.get(Instance, instance.sop_instance_uid)
        assert row is not None
        assert row.pixel_phi == "Patient, Name"


def test_clear_series_tseg_metadata(anonymizer_model: AnonymizerModel, mock_dataset1: Dataset):
    from anonymizer.model.anonymizer import format_series_processing_status

    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_delta=0)
    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    series = phi.studies[0].series[0]
    instance = series.instances[0]

    harmonized = "CT Head Without Contrast"
    anonymizer_model.set_series_harmonized_description(series.anon_series_uid, harmonized)
    anonymizer_model.set_series_face_blur_algorithm(series.anon_series_uid, "gaussian")
    anonymizer_model.set_instance_pixel_phi(instance.anon_sop_instance_uid, ["Name"])

    assert anonymizer_model.clear_series_tseg_metadata(series.anon_series_uid) is True

    status = anonymizer_model.get_series_processing_status(series.anon_series_uid)
    assert status is not None
    assert status.harmonized_description is None
    assert status.face_blur_algorithm == "gaussian"
    assert status.pixel_phi_applied_count == 1
    assert format_series_processing_status(status) == (
        "Pixel PHI: Applied · Harmonized: None · Face blur: Gaussian"
    )

    assert anonymizer_model.clear_series_tseg_metadata("missing-uid") is False


def test_get_series_processing_status(anonymizer_model: AnonymizerModel, mock_dataset1: Dataset):
    from anonymizer.model.anonymizer import format_series_processing_status

    anonymizer_model.capture_phi(source="pytest", ds=mock_dataset1, date_delta=0)
    phi = anonymizer_model.get_phi_by_phi_patient_id(mock_dataset1.PatientID)
    assert phi is not None
    series = phi.studies[0].series[0]
    instance = series.instances[0]

    assert anonymizer_model.get_series_processing_status("missing-uid") is None

    status = anonymizer_model.get_series_processing_status(series.anon_series_uid)
    assert status is not None
    assert status.pixel_phi_applied_count == 0
    assert status.pixel_phi_total_count == 1
    assert status.harmonized_description is None
    assert status.face_blur_algorithm is None
    assert format_series_processing_status(status) == (
        "Pixel PHI: None removed · Harmonized: None · Face blur: None"
    )

    harmonized = "CT Head Without Contrast"
    anonymizer_model.set_series_harmonized_description(series.anon_series_uid, harmonized)
    anonymizer_model.set_series_face_blur_algorithm(series.anon_series_uid, "gaussian")
    anonymizer_model.set_instance_pixel_phi(instance.anon_sop_instance_uid, ["Name"])

    status = anonymizer_model.get_series_processing_status(series.anon_series_uid)
    assert status is not None
    assert status.pixel_phi_applied_count == 1
    assert status.pixel_phi_total_count == 1
    assert status.harmonized_description == harmonized
    assert status.face_blur_algorithm == "gaussian"
    assert format_series_processing_status(status) == (
        f"Pixel PHI: Applied · Harmonized: {harmonized} · Face blur: Gaussian"
    )
