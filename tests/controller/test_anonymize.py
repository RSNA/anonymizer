# UNIT TESTS for controller/anonymize.py
# use pytest from terminal to show full logging output

import os
from copy import deepcopy
import logging
from time import sleep
from queue import Queue
from pydicom import dcmread
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset
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
from utils.storage import local_storage_path

logger = logging.getLogger(__name__)


# Test a valid date before 19000101
def test_valid_date_before_19000101(controller):
    anon = controller.anonymizer
    input_date = "18991231"
    assert not anon.valid_date(input_date)
    assert anon._hash_date(input_date, "12345") == (0, anon.default_anon_date)


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


def test_anonymize_dataset(temp_dir: str, controller):
    anonymizer: AnonymizerController = controller.anonymizer
    anon_Q = Queue()
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    phi_ds = deepcopy(ds)
    anonymizer.anonymize_dataset_and_store(LocalSCU, ds, local_storage_dir(temp_dir))
    sleep(0.5)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    SITEID = controller.model.site_id
    UIDROOT = controller.model.uid_root

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
    assert (
        anon_ds.StudyDate
        == anonymizer._hash_date(phi_ds.StudyDate, phi_ds.PatientID)[1]
    )
    assert anon_ds.SOPClassUID == phi_ds.SOPClassUID
    assert anon_ds.SOPInstanceUID == f"{UIDROOT}.{SITEID}.1"
    assert anon_ds.StudyInstanceUID == f"{UIDROOT}.{SITEID}.2"
    assert anon_ds.SeriesInstanceUID == f"{UIDROOT}.{SITEID}.3"
