# UNIT TESTS for controller/anonymize.py
# use pytest from terminal to show full logging output

import os
from pathlib import Path
from copy import deepcopy
from time import sleep
from queue import Queue
from pydicom import dcmread
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset
from controller.project import ProjectController
from controller.anonymizer import AnonymizerController

from tests.controller.helpers import (
    pacs_storage_dir,
    local_storage_dir,
)

from tests.controller.dicom_test_files import (
    cr1_filename,
    ct_small_filename,
    mr_small_filename,
    mr_small_implicit_filename,
    mr_small_bigendian_filename,
    CR_STUDY_3_SERIES_3_IMAGES,
    CT_STUDY_1_SERIES_4_IMAGES,
    MR_STUDY_3_SERIES_11_IMAGES,
)
from tests.controller.dicom_test_nodes import LocalSCU


# Test a valid date before 19000101
def test_valid_date_before_19000101(controller):
    anon = controller.anonymizer
    input_date = "18991231"
    assert not anon.valid_date(input_date)
    assert anon._hash_date(input_date, "12345") == (0, anon.DEFAULT_ANON_DATE)


# Test a valid date on or after 19000101
def test_valid_date_on_or_after_19000101(controller):
    anon = controller.anonymizer
    assert anon.valid_date("19010101")
    assert anon.valid_date("19801228")
    assert anon.valid_date("19660307")
    assert anon.valid_date("20231212")
    assert anon.valid_date("20220101")


# Test an invalid date format
def test_invalid_date_format(controller):
    anon = controller.anonymizer
    assert not anon.valid_date("01-01-2022")
    assert not anon.valid_date("2001-01-02")
    assert not anon.valid_date("01/01/2022")
    assert not anon.valid_date("0101192")


# Test an invalid date value (not a valid date)
def test_invalid_date_value(controller):
    anon = controller.anonymizer
    assert not anon.valid_date("20220230")
    assert not anon.valid_date("20220231")
    assert not anon.valid_date("20220431")
    assert not anon.valid_date("20220631")
    assert not anon.valid_date("99991232")


# Test with a known date and PatientID
def test_valid_date_hashing(controller):
    anon = controller.anonymizer
    assert "20220921" == anon._hash_date("20220101", "12345")[1]
    assert "20250815" == anon._hash_date("20220101", "67890")[1]
    assert "19080814" == anon._hash_date("19000101", "123456789")[1]
    assert "19080412" == anon._hash_date("19000101", "1234567890")[1]


def test_valid_date_hash_patient_id_range(controller):
    anon = controller.anonymizer
    for i in range(100):
        _, hdate = anon._hash_date("20100202", str(i))
        assert anon.valid_date(hdate)


def test_anonymize_dataset_without_PatientID(temp_dir: str, controller):
    anonymizer: AnonymizerController = controller.anonymizer
    anon_Q = Queue()
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    # Remove PatientID field
    del ds.PatientID
    phi_ds = deepcopy(ds)
    anonymizer.anonymize_dataset_ex(LocalSCU, ds)
    sleep(0.5)
    store_dir = local_storage_dir(temp_dir)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]

    SITEID = controller.model.site_id
    UIDROOT = controller.model.uid_root

    anon_pt_id = SITEID + "-000000"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    anon_filename = anonymizer.local_storage_path(local_storage_dir(temp_dir), ds)
    anon_ds = dcmread(anon_filename)
    assert isinstance(anon_ds, Dataset)
    assert anon_ds.PatientID == anon_pt_id
    assert anon_ds.PatientName == anon_pt_id
    assert anon_ds.AccessionNumber == "1"
    assert anon_ds.StudyDate != phi_ds.StudyDate
    assert anon_ds.StudyDate == anonymizer.DEFAULT_ANON_DATE
    assert anon_ds.SOPClassUID == phi_ds.SOPClassUID

    assert anon_ds.StudyInstanceUID == f"{UIDROOT}.{SITEID}.1"
    assert anon_ds.SeriesInstanceUID == f"{UIDROOT}.{SITEID}.2"
    assert anon_ds.SOPInstanceUID == f"{UIDROOT}.{SITEID}.3"
    assert controller.anonymizer.model.get_phi_name(anon_pt_id) == ""
    assert controller.anonymizer.model.get_phi(anon_pt_id).patient_id == ""


def test_anonymize_dataset_with_blank_PatientID_1_study(temp_dir: str, controller):
    anonymizer: AnonymizerController = controller.anonymizer
    anon_Q = Queue()
    ds1 = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds1, Dataset)
    assert ds1
    assert ds1.PatientID
    # Set Blank PatientID
    ds1.PatientID = ""
    phi_ds1 = deepcopy(ds1)
    anonymizer.anonymize_dataset_ex(LocalSCU, ds1)
    sleep(0.5)

    ds2 = get_testdata_file(ct_small_filename, read=True)
    assert isinstance(ds2, Dataset)
    assert ds2
    assert ds2.PatientID
    # Delete PatientID attribute
    del ds2.PatientID
    phi_ds2 = deepcopy(ds2)
    anonymizer.anonymize_dataset_ex(LocalSCU, ds2)

    sleep(0.5)
    store_dir = local_storage_dir(temp_dir)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]

    SITEID = controller.model.site_id
    UIDROOT = controller.model.uid_root

    # 1 Patient directory with 2 Studies:
    anon_pt_id = SITEID + "-000000"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id

    anon_filename1 = anonymizer.local_storage_path(local_storage_dir(temp_dir), ds1)
    anon_ds1 = dcmread(anon_filename1)
    assert isinstance(anon_ds1, Dataset)
    assert anon_ds1.PatientID == anon_pt_id
    assert anon_ds1.PatientName == anon_pt_id
    assert anon_ds1.AccessionNumber == "1"
    assert anon_ds1.StudyDate != phi_ds1.StudyDate
    assert anon_ds1.StudyDate == anonymizer.DEFAULT_ANON_DATE
    assert anon_ds1.SOPClassUID == phi_ds1.SOPClassUID
    assert anon_ds1.file_meta.TransferSyntaxUID == phi_ds1.file_meta.TransferSyntaxUID
    assert f"{UIDROOT}.{SITEID}." in anon_ds1.StudyInstanceUID
    assert f"{UIDROOT}.{SITEID}." in anon_ds1.SeriesInstanceUID
    assert f"{UIDROOT}.{SITEID}." in anon_ds1.SOPInstanceUID

    anon_filename2 = anonymizer.local_storage_path(local_storage_dir(temp_dir), ds2)
    anon_ds2 = dcmread(anon_filename2)
    assert isinstance(anon_ds2, Dataset)
    assert anon_ds2.PatientID == anon_pt_id
    assert anon_ds2.PatientName == anon_pt_id
    assert anon_ds2.AccessionNumber == "2"
    assert anon_ds2.StudyDate != phi_ds2.StudyDate
    assert anon_ds2.StudyDate == anonymizer.DEFAULT_ANON_DATE
    assert anon_ds2.SOPClassUID == phi_ds2.SOPClassUID
    assert anon_ds2.file_meta.TransferSyntaxUID == phi_ds2.file_meta.TransferSyntaxUID
    assert f"{UIDROOT}.{SITEID}." in anon_ds2.StudyInstanceUID
    assert f"{UIDROOT}.{SITEID}." in anon_ds2.SeriesInstanceUID
    assert f"{UIDROOT}.{SITEID}." in anon_ds2.SOPInstanceUID

    anon_pt_dir = Path(store_dir, anon_pt_id).as_posix()
    anon_ptid_dirlist = [d for d in os.listdir(anon_pt_dir) if os.path.isdir(os.path.join(anon_pt_dir, d))]
    assert len(anon_ptid_dirlist) == 2
    assert anon_ds1.StudyInstanceUID in anon_ptid_dirlist
    assert anon_ds2.StudyInstanceUID in anon_ptid_dirlist

    assert controller.anonymizer.model.get_phi_name(anon_pt_id) == ""
    assert controller.anonymizer.model.get_phi(anon_pt_id).patient_id == ""


def test_anonymize_dataset_with_blank_PatientID_2_studies(temp_dir: str, controller):
    anonymizer: AnonymizerController = controller.anonymizer
    anon_Q = Queue()
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    # Set Blank PatientID
    ds.PatientID = ""
    phi_ds = deepcopy(ds)
    anonymizer.anonymize_dataset_ex(LocalSCU, ds)
    sleep(0.5)
    store_dir = local_storage_dir(temp_dir)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]

    SITEID = controller.model.site_id
    UIDROOT = controller.model.uid_root

    anon_pt_id = SITEID + "-000000"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    anon_filename = anonymizer.local_storage_path(local_storage_dir(temp_dir), ds)
    anon_ds = dcmread(anon_filename)
    assert isinstance(anon_ds, Dataset)
    assert anon_ds.PatientID == anon_pt_id
    assert anon_ds.PatientName == anon_pt_id
    assert anon_ds.AccessionNumber == "1"
    assert anon_ds.StudyDate != phi_ds.StudyDate
    assert anon_ds.StudyDate == anonymizer.DEFAULT_ANON_DATE
    assert anon_ds.SOPClassUID == phi_ds.SOPClassUID
    assert anon_ds.StudyInstanceUID == f"{UIDROOT}.{SITEID}.1"
    assert anon_ds.SeriesInstanceUID == f"{UIDROOT}.{SITEID}.2"
    assert anon_ds.SOPInstanceUID == f"{UIDROOT}.{SITEID}.3"
    assert controller.anonymizer.model.get_phi_name(anon_pt_id) == ""
    assert controller.anonymizer.model.get_phi(anon_pt_id).patient_id == ""


def test_anonymize_dataset_with_PatientID(temp_dir: str, controller):
    anonymizer: AnonymizerController = controller.anonymizer
    anon_Q = Queue()
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    phi_ds = deepcopy(ds)
    anonymizer.anonymize_dataset_ex(LocalSCU, ds)
    sleep(0.5)
    store_dir = local_storage_dir(temp_dir)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]

    SITEID = controller.model.site_id
    UIDROOT = controller.model.uid_root

    anon_pt_id = SITEID + "-000001"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    anon_filename = anonymizer.local_storage_path(local_storage_dir(temp_dir), ds)
    anon_ds = dcmread(anon_filename)
    assert isinstance(anon_ds, Dataset)
    assert anon_ds.PatientID == anon_pt_id
    assert anon_ds.PatientID != phi_ds.PatientID
    assert anon_ds.PatientName == anon_pt_id
    assert anon_ds.AccessionNumber == "1"
    assert anon_ds.StudyDate != phi_ds.StudyDate
    assert anon_ds.StudyDate == anonymizer._hash_date(phi_ds.StudyDate, phi_ds.PatientID)[1]
    assert anon_ds.SOPClassUID == phi_ds.SOPClassUID
    assert anon_ds.StudyInstanceUID == f"{UIDROOT}.{SITEID}.1"
    assert anon_ds.SeriesInstanceUID == f"{UIDROOT}.{SITEID}.2"
    assert anon_ds.SOPInstanceUID == f"{UIDROOT}.{SITEID}.3"


# QUARANTINE Tests:
def test_anonymize_file_not_found(temp_dir: str, controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer

    error_msg, ds = anonymizer.anonymize_file(Path("unknown_file.dcm"))

    assert "No such file" in error_msg
    assert ds is None

    error_msg, ds = anonymizer.anonymize_file(temp_dir)

    assert "Is a directory" in error_msg
    assert ds is None

    # TODO: simulate file permission error


def test_anonymize_invalid_dicom_file(temp_dir: str, controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer

    test_filename = "test_file.txt"
    test_file_path = Path(temp_dir, test_filename)
    with open(test_file_path, "w") as f:
        f.write("Testing Anonymizer")

    error_msg, ds = anonymizer.anonymize_file(test_file_path)

    assert "File is missing DICOM File Meta" in error_msg
    assert ds is None

    # Ensure file is moved to correct quarantine directory:
    qpath = Path(anonymizer.get_quarantine_path(), anonymizer.QUARANTINE_INVALID_DICOM, test_filename)
    assert qpath.exists()


def test_anonymize_dicom_missing_attributes(temp_dir: str, controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer

    cr1: Dataset = get_testdata_file(cr1_filename, read=True)
    assert isinstance(cr1, Dataset)
    assert cr1
    assert cr1.SOPClassUID
    del cr1.SOPClassUID  # remove required attribute
    test_filename = "test.dcm"
    test_dcm_file_path = Path(temp_dir, test_filename)
    cr1.save_as(test_dcm_file_path)

    error_msg, ds = anonymizer.anonymize_file(test_dcm_file_path)

    assert "Missing Attributes" in error_msg
    assert ds == cr1

    # Ensure file is moved to correct quarantine directory:
    qpath = Path(anonymizer.get_quarantine_path(), anonymizer.QUARANTINE_MISSING_ATTRIBUTES, test_filename)
    assert qpath.exists()


def test_anonymize_dicom_missing_attributes(temp_dir: str, controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer

    cr1: Dataset = get_testdata_file(cr1_filename, read=True)
    assert isinstance(cr1, Dataset)
    assert cr1
    assert cr1.SOPClassUID
    del cr1.SOPClassUID  # remove required attribute
    test_filename = "test.dcm"
    test_dcm_file_path = Path(temp_dir, test_filename)
    cr1.save_as(test_dcm_file_path)

    error_msg, ds = anonymizer.anonymize_file(test_dcm_file_path)

    assert "Missing Attributes" in error_msg
    assert ds == cr1

    # Ensure file is moved to correct quarantine directory:
    qpath = Path(anonymizer.get_quarantine_path(), anonymizer.QUARANTINE_MISSING_ATTRIBUTES, test_filename)
    assert qpath.exists()


def test_anonymize_storage_error(temp_dir: str, controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer

    cr1: Dataset = get_testdata_file(cr1_filename, read=True)
    assert isinstance(cr1, Dataset)
    assert cr1
    assert cr1.SOPClassUID
    del cr1.file_meta  # remove file_meta

    error_msg = anonymizer.anonymize("Unit Testing", cr1)

    assert "Storage Error" in error_msg

    # Ensure file is moved to correct quarantine directory:

    qpath = Path(anonymizer.get_quarantine_path(), anonymizer.QUARANTINE_STORAGE_ERROR)
    assert qpath.exists()
    filename: Path = anonymizer.local_storage_path(qpath, cr1)
    assert filename.exists()


# TODO: Transcoding tests here
