# UNIT TESTS for controller/anonymize.py
# use pytest from terminal to show full logging output

import os
from copy import deepcopy
import logging
from time import sleep
from pydicom import dcmread
from model.project import SITEID, UIDROOT
from queue import Queue
from controller.anonymize import (
    _hash_date,
    valid_date,
    default_anon_date,
    anonymize_dataset_and_store,
)
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset

from tests.controller.helpers import (
    pacs_storage_dir,
    start_pacs_simulator_scp,
    start_local_storage_scp,
    local_storage_dir,
    send_file_to_scp,
    send_files_to_scp,
    verify_files_sent_to_pacs_simulator,
    export_patients_from_local_storage_to_test_pacs,
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
from utils.storage import local_storage_path

logger = logging.getLogger(__name__)


# Test a valid date before 19000101
def test_valid_date_before_19000101():
    input_date = "18991231"
    assert not valid_date(input_date)
    assert _hash_date(input_date, "12345") == default_anon_date


# Test a valid date on or after 19000101
def test_valid_date_on_or_after_19000101():
    assert valid_date("19010101")
    assert valid_date("19801228")
    assert valid_date("19660307")
    assert valid_date("20231212")
    assert valid_date("20220101")


# Test an invalid date format
def test_invalid_date_format():
    assert not valid_date("01-01-2022")
    assert not valid_date("2001-01-02")
    assert not valid_date("01/01/2022")
    assert not valid_date("0101192")


# Test an invalid date value (not a valid date)
def test_invalid_date_value():
    assert not valid_date("20220230")
    assert not valid_date("20220231")
    assert not valid_date("20220431")
    assert not valid_date("20220631")
    assert not valid_date("99991232")


# Test with a known date and PatientID
def test_valid_date_hashing():
    assert "20220921" == _hash_date("20220101", "12345")
    assert "20250815" == _hash_date("20220101", "67890")
    assert "19080814" == _hash_date("19000101", "123456789")
    assert "19080412" == _hash_date("19000101", "1234567890")


def test_valid_date_hash_patient_id_range():
    for i in range(100):
        assert valid_date(_hash_date("20100202", str(i)))


def test_anonymize_dataset(temp_dir: str):
    anon_Q = Queue()
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    phi_ds = deepcopy(ds)
    anonymize_dataset_and_store(LocalSCU, ds, local_storage_dir(temp_dir))
    sleep(0.5)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    anon_pt_id = SITEID + "-000001"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    anon_filename = local_storage_path(local_storage_dir(temp_dir), anon_pt_id, ds)
    anon_ds = dcmread(anon_filename)
    assert isinstance(anon_ds, Dataset)
    assert anon_ds.PatientID == anon_pt_id
    assert anon_ds.PatientID != phi_ds.PatientID
    assert anon_ds.PatientName == anon_pt_id
    assert anon_ds.AccessionNumber == "1"
    assert anon_ds.StudyDate != phi_ds.StudyDate
    assert anon_ds.StudyDate == _hash_date(phi_ds.StudyDate, phi_ds.PatientID)
    assert anon_ds.SOPClassUID == phi_ds.SOPClassUID
    assert anon_ds.SOPInstanceUID == f"{UIDROOT}.{SITEID}.1"
    assert anon_ds.StudyInstanceUID == f"{UIDROOT}.{SITEID}.2"
    assert anon_ds.SeriesInstanceUID == f"{UIDROOT}.{SITEID}.3"
