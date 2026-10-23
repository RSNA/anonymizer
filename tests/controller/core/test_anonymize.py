# UNIT TESTS for controller/anonymize.py
# use pytest from terminal to show full logging output

import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import sleep

import pytest
from pydicom import dcmread
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset

from anonymizer.controller.anonymizer import AnonymizerController, QuarantineDirectories
from anonymizer.controller.dates import (
    DEFAULT_ANON_DATE,
    apply_day_delta,
    hash_date,
    rebase_days,
    resolve_date_delta,
    stamp_dates_modified,
    stamp_rebase_registration,
    valid_date,
)
from anonymizer.controller.project import ProjectController
from anonymizer.utils.dicom import DeidMethodCode
from tests.controller.dicom.support.test_files import (
    cr1_filename,
    ct_small_filename,
    # mr_small_filename,
    # mr_small_implicit_filename,
    # mr_small_bigendian_filename,
    # CR_STUDY_3_SERIES_3_IMAGES,
    # CT_STUDY_1_SERIES_4_IMAGES,
    # MR_STUDY_3_SERIES_11_IMAGES,
    hash_cr1_SeriesInstanceUID,
    hash_cr1_SOPInstanceUID,
    hash_cr1_StudyInstanceUID,
)

REBASE_DELTA = resolve_date_delta(
    "@rebasedate(this,19600101)", patient_id="MRN1", days_from_lookup=0, base_date="20180327"
)
from tests.controller.dicom.support.test_nodes import LocalSCU


# Test a valid date before 19000101
def test_valid_date_before_19000101(controller):
    input_date = "18991231"
    assert not valid_date(input_date)
    assert hash_date(input_date, "12345") == (0, DEFAULT_ANON_DATE)


# Test a valid date on or after 19000101
def test_valid_date_on_or_after_19000101(controller):
    assert valid_date("19010101")
    assert valid_date("19801228")
    assert valid_date("19660307")
    assert valid_date("20231212")
    assert valid_date("20220101")


# Test an invalid date format
def test_invalid_date_format(controller):
    assert not valid_date("01-01-2022")
    assert not valid_date("2001-01-02")
    assert not valid_date("01/01/2022")
    assert not valid_date("0101192")


# Test an invalid date value (not a valid date)
def test_invalid_date_value(controller):
    assert not valid_date("20220230")
    assert not valid_date("20220231")
    assert not valid_date("20220431")
    assert not valid_date("20220631")
    assert not valid_date("99991232")


# Test with a known date and PatientID
def test_valid_date_hashing(controller):
    assert hash_date("20220101", "12345")[1] == "20220921"
    assert hash_date("20220101", "67890")[1] == "20250815"
    assert hash_date("19000101", "123456789")[1] == "19080814"
    assert hash_date("19000101", "1234567890")[1] == "19080412"


def test_valid_date_hash_patient_id_range(controller):
    for i in range(100):
        _, hdate = hash_date("20100202", str(i))
        assert valid_date(hdate)


def test_uid_hashing_is_deterministic_and_unique(controller: ProjectController):
    """
    Tests the core idempotent property:
    1. The same input always produces the same output.
    2. A different input produces a different output.
    """
    model = controller.anonymizer.model
    orig_uid_1 = "1.2.3.4.5"
    orig_uid_2 = "1.2.3.4.5.6"  # A different UID

    # Call the function twice with the same input
    hash_1a = model._create_anon_uid(orig_uid_1)
    hash_1b = model._create_anon_uid(orig_uid_1)

    # Call with the different input
    hash_2 = model._create_anon_uid(orig_uid_2)

    # Test for idempotency
    assert hash_1a == hash_1b

    # Test for uniqueness
    assert hash_1a != hash_2


def test_uid_hash_format_and_length(controller: ProjectController):
    """
    Tests that the generated UID is always compliant:
    1. Starts with the correct prefix.
    2. Is 64 characters or less.
    3. The hashed part is numeric.
    """
    model = controller.anonymizer.model
    orig_uid = "1.2.840.113619.1.2.3.4.5.6.7.8.9.10"
    hashed_uid = model._create_anon_uid(orig_uid)

    expected_prefix = f"{model._uid_prefix}.2."

    # 1. Check prefix
    assert hashed_uid.startswith(expected_prefix)

    # 2. Check max length
    assert len(hashed_uid) <= model.DICOM_UID_MAX_LEN

    # 3. Check that the hash part is numeric
    hash_part = hashed_uid.replace(expected_prefix, "")
    assert hash_part.isnumeric()
    assert len(hash_part) > 0  # Ensure it's not empty


def test_uid_hashing_raises_error_if_prefix_too_long(controller: ProjectController):
    """
    Tests the ValueError check. If the project prefix is so long
    that it's impossible to generate a valid UID, it must fail.
    """
    # `uid_root` = `self._uid_prefix` + ".1" (adds 2 chars)
    # `prefix` = `uid_root` + "." (adds 1 char)
    # Total added: 3 chars.

    # A prefix of 61 chars will work (61 + 3 = 64).
    # `len(prefix)` will be 64. `max_len <= len(prefix)` will be `64 <= 64`,
    # which is True, so it will raise the error.

    # Let's test the boundary:
    # A prefix of 60 chars. `prefix` length = 63. `max_len <= 63` is False. OK.
    model = controller.anonymizer.model
    prefix_60_chars = "1." * 30
    model._uid_prefix = prefix_60_chars
    model._create_anon_uid("1.2.3")  # Should not raise

    # A prefix of 61 chars. `prefix` length = 64. `max_len <= 64` is True. Raise.
    prefix_61_chars = "1.2" + ("." * 59)
    assert len(prefix_61_chars) == 62
    model._uid_prefix = prefix_61_chars

    with pytest.raises(ValueError, match="is too short to accommodate"):
        model._create_anon_uid("1.2.3")


def test_anonymize_dataset_without_PatientID(controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    # Remove PatientID field
    del ds.PatientID
    phi_ds = deepcopy(ds)
    anonymizer.anonymize_dataset_ex(LocalSCU, ds)
    sleep(1)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]

    SITEID = controller.model.site_id
    UIDROOT = controller.model.uid_root

    anon_pt_id = SITEID + "-000000"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    anon_filename = anonymizer.local_storage_path(store_dir, ds)
    anon_ds = dcmread(anon_filename)
    assert isinstance(anon_ds, Dataset)
    assert anon_ds.PatientID == anon_pt_id
    assert anon_ds.PatientName == anon_pt_id
    assert len(anon_ds.AccessionNumber) == 18
    assert anon_ds.StudyDate != phi_ds.StudyDate
    assert anon_ds.StudyDate == anonymizer.DEFAULT_ANON_DATE
    assert anon_ds.SOPClassUID == phi_ds.SOPClassUID

    assert anon_ds.StudyInstanceUID == hash_cr1_StudyInstanceUID
    assert anon_ds.SeriesInstanceUID == hash_cr1_SeriesInstanceUID
    assert anon_ds.SOPInstanceUID == hash_cr1_SOPInstanceUID
    assert controller.anonymizer.model.get_phi_name_by_anon_patient_id(anon_pt_id) is None
    phi = controller.anonymizer.model.get_phi_by_anon_patient_id(anon_pt_id)
    if phi:
        assert phi.patient_id == ""


def test_anonymize_dataset_with_blank_PatientID_1_study(controller):
    anonymizer: AnonymizerController = controller.anonymizer
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    # Set Blank PatientID
    ds.PatientID = ""
    phi_ds = deepcopy(ds)
    anonymizer.anonymize_dataset_ex(LocalSCU, ds)
    sleep(0.5)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]

    SITEID = controller.model.site_id
    UIDROOT = controller.model.uid_root

    anon_pt_id = SITEID + "-000000"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    anon_filename = anonymizer.local_storage_path(store_dir, ds)
    anon_ds = dcmread(anon_filename)
    assert isinstance(anon_ds, Dataset)
    assert anon_ds.PatientID == anon_pt_id
    assert anon_ds.PatientName == anon_pt_id
    assert len(anon_ds.AccessionNumber) == 18
    assert anon_ds.StudyDate != phi_ds.StudyDate
    assert anon_ds.StudyDate == anonymizer.DEFAULT_ANON_DATE
    assert anon_ds.SOPClassUID == phi_ds.SOPClassUID
    assert anon_ds.StudyInstanceUID == hash_cr1_StudyInstanceUID
    assert anon_ds.SeriesInstanceUID == hash_cr1_SeriesInstanceUID
    assert anon_ds.SOPInstanceUID == hash_cr1_SOPInstanceUID
    assert controller.anonymizer.model.get_phi_name_by_anon_patient_id(anon_pt_id) is None

    phi = controller.anonymizer.model.get_phi_by_anon_patient_id(anon_pt_id)
    if phi:
        assert phi.patient_id == ""


def test_anonymize_dataset_with_blank_PatientID_2_studies(controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer
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
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]

    SITEID = controller.model.site_id
    UIDROOT = controller.model.uid_root

    # 1 Patient directory with 2 Studies:
    anon_pt_id = SITEID + "-000000"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id

    anon_filename1 = anonymizer.local_storage_path(store_dir, ds1)
    anon_ds1 = dcmread(anon_filename1)
    assert isinstance(anon_ds1, Dataset)
    assert anon_ds1.PatientID == anon_pt_id
    assert anon_ds1.PatientName == anon_pt_id
    assert len(anon_ds1.AccessionNumber) == 18
    assert anon_ds1.StudyDate != phi_ds1.StudyDate
    assert anon_ds1.StudyDate == anonymizer.DEFAULT_ANON_DATE
    assert anon_ds1.SOPClassUID == phi_ds1.SOPClassUID
    assert anon_ds1.file_meta.TransferSyntaxUID == phi_ds1.file_meta.TransferSyntaxUID
    assert f"{UIDROOT}.{SITEID}." in anon_ds1.StudyInstanceUID
    assert f"{UIDROOT}.{SITEID}." in anon_ds1.SeriesInstanceUID
    assert f"{UIDROOT}.{SITEID}." in anon_ds1.SOPInstanceUID

    anon_filename2 = anonymizer.local_storage_path(store_dir, ds2)
    anon_ds2 = dcmread(anon_filename2)
    assert isinstance(anon_ds2, Dataset)
    assert anon_ds2.PatientID == anon_pt_id
    assert anon_ds2.PatientName == anon_pt_id
    assert anon_ds2.AccessionNumber == ""
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

    assert controller.anonymizer.model.get_phi_name_by_anon_patient_id(anon_pt_id) is None
    phi = controller.anonymizer.model.get_phi_by_anon_patient_id(anon_pt_id)
    if phi:
        assert phi.patient_id == ""


def test_anonymize_dataset_with_PatientID_1_study(controller):
    anonymizer: AnonymizerController = controller.anonymizer
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    phi_ds = deepcopy(ds)
    anonymizer.anonymize_dataset_ex(LocalSCU, ds)
    sleep(0.5)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]

    SITEID = controller.model.site_id
    UIDROOT = controller.model.uid_root

    anon_pt_id = SITEID + "-000001"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    anon_filename = anonymizer.local_storage_path(store_dir, ds)
    anon_ds = dcmread(anon_filename)
    assert isinstance(anon_ds, Dataset)
    assert anon_ds.PatientID == anon_pt_id
    assert anon_ds.PatientID != phi_ds.PatientID
    assert anon_ds.PatientName == anon_pt_id
    assert len(anon_ds.AccessionNumber) == 18
    assert anon_ds.StudyDate != phi_ds.StudyDate
    assert anon_ds.StudyDate == hash_date(phi_ds.StudyDate, phi_ds.PatientID)[1]
    assert anon_ds.SOPClassUID == phi_ds.SOPClassUID
    assert anon_ds.StudyInstanceUID == hash_cr1_StudyInstanceUID
    assert anon_ds.SeriesInstanceUID == hash_cr1_SeriesInstanceUID
    assert anon_ds.SOPInstanceUID == hash_cr1_SOPInstanceUID

    assert controller.anonymizer.model.get_phi_name_by_anon_patient_id(anon_pt_id) == phi_ds.PatientName
    phi = controller.anonymizer.model.get_phi_by_anon_patient_id(anon_pt_id)
    assert phi
    assert phi.patient_id == phi_ds.PatientID


# QUARANTINE Tests:
def test_anonymize_file_not_found(temp_dir: str, controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer

    error_msg, ds = anonymizer.anonymize_file(Path("unknown_file.dcm"))

    assert error_msg
    assert "No such file" in error_msg
    assert ds is None

    error_msg, ds = anonymizer.anonymize_file(Path(temp_dir))

    assert error_msg
    assert "Is a directory" in error_msg or "Permission denied" in error_msg or "Errno 13" in error_msg
    assert ds is None


def test_anonymize_invalid_dicom_file(temp_dir: str, controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer

    test_filename = "test_file.txt"
    test_file_path = Path(temp_dir, test_filename)
    with open(test_file_path, "w") as f:
        f.write("Testing Anonymizer")

    error_msg, ds = anonymizer.anonymize_file(test_file_path)

    assert error_msg
    assert "File is missing DICOM File Meta" in error_msg
    assert ds is None

    # Ensure file is moved to correct quarantine directory:
    qpath = Path(anonymizer.get_quarantine_path(), QuarantineDirectories.INVALID_DICOM.value)
    assert qpath.exists()


def test_anonymize_dicom_missing_attributes(temp_dir: str, controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer

    cr1 = get_testdata_file(cr1_filename, read=True)
    assert isinstance(cr1, Dataset)
    assert cr1
    assert cr1.SOPClassUID
    del cr1.SOPClassUID  # remove required attribute
    test_filename = "test.dcm"
    test_dcm_file_path = Path(temp_dir, test_filename)
    cr1.save_as(test_dcm_file_path)

    error_msg, ds = anonymizer.anonymize_file(test_dcm_file_path)

    assert error_msg
    assert "Missing Attributes" in error_msg
    assert ds == cr1

    # Ensure file is moved to correct quarantine directory:
    qpath = Path(anonymizer.get_quarantine_path(), QuarantineDirectories.MISSING_ATTRIBUTES.value)
    assert qpath.exists()


def test_anonymize_storage_error(controller: ProjectController):
    anonymizer: AnonymizerController = controller.anonymizer

    cr1 = get_testdata_file(cr1_filename, read=True)
    assert isinstance(cr1, Dataset)
    assert cr1
    assert cr1.SOPClassUID
    del cr1.file_meta  # remove file_meta

    error_msg = anonymizer.anonymize("Unit Testing", cr1)

    assert error_msg
    assert "Storage Error" in error_msg

    # Ensure file is moved to correct quarantine directory:
    qpath = Path(anonymizer.get_quarantine_path(), QuarantineDirectories.STORAGE_ERROR.value)
    assert qpath.exists()
    filename: Path = anonymizer.local_storage_path(qpath, cr1)
    assert filename.exists()


# TODO: Transcoding tests here


def test_always_operand_sets_literal_and_creates_missing(controller: ProjectController) -> None:
    """@always()/bare literals replace values; @always() also create-if-missing."""
    anon: AnonymizerController = controller.anonymizer

    ds = Dataset()
    ds.add_new(0x00120062, "CS", "NO")
    anon.model._tag_keep["00120062"] = "YES"
    anon._anonymize_element(ds, ds[0x00120062], "phi", "anon", None, 0)
    assert ds.PatientIdentityRemoved == "YES"

    ds2 = Dataset()
    ds2.add_new(0x00081030, "LO", "old-desc")
    anon.model._tag_keep["00081030"] = "@always()REMOVED"
    anon._anonymize_element(ds2, ds2[0x00081030], "phi", "anon", None, 0)
    assert ds2.StudyDescription == "REMOVED"

    ds3 = Dataset()
    anon.model._tag_keep["00120062"] = "@always()YES"
    assert 0x00120062 not in ds3
    anon._insert_always_missing_elements(ds3)
    assert ds3.PatientIdentityRemoved == "YES"

    ds4 = Dataset()
    anon.model._tag_keep["00120062"] = "YES"
    anon._insert_always_missing_elements(ds4)
    assert 0x00120062 not in ds4


def test_date_operands_present_set_by_load_script(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    assert anon.model.date_operands_present is True
    anon.model._tag_keep.clear()
    anon.model._tag_keep["00100020"] = "@ptid"
    anon.model.date_operands_present = any("date" in op for op in anon.model._tag_keep.values())
    assert anon.model.date_operands_present is False
    anon.model._tag_keep["00080020"] = "@hashdate"
    anon.model.date_operands_present = any("date" in op for op in anon.model._tag_keep.values())
    assert anon.model.date_operands_present is True


def test_incrementdate_shifts_da_and_dt(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    ds = Dataset()
    ds.add_new(0x00080020, "DA", "20200101")
    ds.add_new(0x0008002A, "DT", "20200101123000")
    anon.model._tag_keep["00080020"] = "@incrementdate(this,42)"
    anon.model._tag_keep["0008002A"] = "@incrementdate(this,42)"
    anon._anonymize_element(ds, ds[0x00080020], "phi", "anon", None, 42)
    anon._anonymize_element(ds, ds[0x0008002A], "phi", "anon", None, 42)
    assert ds.StudyDate == "20200212"
    assert str(ds.AcquisitionDateTime).startswith("20200212")


def test_incrementdate_negative_shifts_earlier(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    ds = Dataset()
    ds.add_new(0x00080020, "DA", "20200115")
    ds.add_new(0x0008002A, "DT", "20200115120000")
    anon.model._tag_keep["00080020"] = "@incrementdate(this,-10)"
    anon.model._tag_keep["0008002A"] = "@incrementdate(this,-10)"
    anon._anonymize_element(ds, ds[0x00080020], "phi", "anon", None, -10)
    anon._anonymize_element(ds, ds[0x0008002A], "phi", "anon", None, -10)
    assert ds.StudyDate == "20200105"
    assert str(ds.AcquisitionDateTime).startswith("20200105")


def test_incrementdate_is_trial_wide_same_for_all_patients(controller: ProjectController) -> None:
    """TCIA/CTP DATEINC: the same n applies to every patient."""
    anon: AnonymizerController = controller.anonymizer
    anon.model._tag_keep["00080020"] = "@incrementdate(this,42)"
    a = Dataset()
    a.add_new(0x00080020, "DA", "20200101")
    b = Dataset()
    b.add_new(0x00080020, "DA", "20200101")
    anon._anonymize_element(a, a[0x00080020], "patient-A", "anon-A", None, 42)
    anon._anonymize_element(b, b[0x00080020], "patient-B", "anon-B", None, 42)
    assert a.StudyDate == b.StudyDate == "20200212"


def test_incrementdate_preserves_study_interval(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    anon.model._tag_keep["00080020"] = "@incrementdate(this,42)"
    early = Dataset()
    early.add_new(0x00080020, "DA", "20200101")
    late = Dataset()
    late.add_new(0x00080020, "DA", "20200131")
    anon._anonymize_element(early, early[0x00080020], "patient-inc", "anon", None, 42)
    anon._anonymize_element(late, late[0x00080020], "patient-inc", "anon", None, 42)
    assert (
        datetime.strptime(str(late.StudyDate), "%Y%m%d")
        - datetime.strptime(str(early.StudyDate), "%Y%m%d")
    ).days == 30


def test_incrementdate_sets_modified_flag(controller: ProjectController) -> None:
    ds = Dataset()
    ds.add_new(0x00080020, "DA", "20200101")
    stamp_dates_modified(ds)
    assert ds.LongitudinalTemporalInformationModified == "MODIFIED"
    assert not hasattr(ds, "LongitudinalTemporalEventType")


def test_apply_day_delta_empty_and_short_passthrough(controller: ProjectController) -> None:
    assert apply_day_delta("", 10) == ""
    assert apply_day_delta("2020", 10) == "2020"
    assert apply_day_delta("20200101", 10) == "20200111"
    assert apply_day_delta("20200101123000.123", 1).startswith("20200102")


def test_rebasedate_without_basedate_leaves_value(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    anon.model.upsert_ctp_lookup_phi([])
    ds = Dataset()
    ds.add_new(0x00080020, "DA", "20180329")
    anon.model._tag_keep["00080020"] = "@rebasedate(this,19600101)"
    anon._anonymize_element(ds, ds[0x00080020], "UNKNOWN", "SITE-X", None, None)
    assert ds.StudyDate == "20180329"


def test_hashdate_preserves_study_interval(controller: ProjectController) -> None:
    """Same PatientID → same offset; two study dates stay the same number of days apart."""
    anon: AnonymizerController = controller.anonymizer
    early = Dataset()
    early.add_new(0x00080020, "DA", "20200101")
    late = Dataset()
    late.add_new(0x00080020, "DA", "20200131")
    anon.model._tag_keep["00080020"] = "@hashdate"
    delta = resolve_date_delta("@hashdate", patient_id="patient-interval", days_from_lookup=0, base_date=None)
    anon._anonymize_element(early, early[0x00080020], "patient-interval", "anon", None, delta)
    anon._anonymize_element(late, late[0x00080020], "patient-interval", "anon", None, delta)
    delta_before = (datetime(2020, 1, 31) - datetime(2020, 1, 1)).days
    delta_after = (
        datetime.strptime(str(late.StudyDate), "%Y%m%d")
        - datetime.strptime(str(early.StudyDate), "%Y%m%d")
    ).days
    assert delta_after == delta_before


def test_hashdate_is_per_patient_deterministic(controller: ProjectController) -> None:
    """Different patients get different offsets; same patient is stable."""
    anon: AnonymizerController = controller.anonymizer
    anon.model._tag_keep["00080020"] = "@hashdate"
    a1 = Dataset()
    a1.add_new(0x00080020, "DA", "20200101")
    a2 = Dataset()
    a2.add_new(0x00080020, "DA", "20200101")
    b = Dataset()
    b.add_new(0x00080020, "DA", "20200101")
    delta_a = resolve_date_delta("@hashdate", patient_id="patient-A", days_from_lookup=0, base_date=None)
    delta_b = resolve_date_delta("@hashdate", patient_id="patient-B", days_from_lookup=0, base_date=None)
    anon._anonymize_element(a1, a1[0x00080020], "patient-A", "anon-A", None, delta_a)
    anon._anonymize_element(a2, a2[0x00080020], "patient-A", "anon-A", None, delta_a)
    anon._anonymize_element(b, b[0x00080020], "patient-B", "anon-B", None, delta_b)
    assert a1.StudyDate == a2.StudyDate
    assert a1.StudyDate != b.StudyDate


def test_anonymize_records_selected_option_codes(controller: ProjectController) -> None:
    """(0012,0064) records exactly the selected AT_INGEST options."""
    from anonymizer.model.project import RETAIN_OPTIONS

    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "CODES-PT"
    ds.StudyDate = "20200101"
    ds.SOPInstanceUID = "1.2.840.10008.codes.1"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    codes = {str(item.CodeValue) for item in ds.DeidentificationMethodCodeSequence}
    assert codes == {"113100"}

    controller.model.confidentiality_options = RETAIN_OPTIONS
    ds2 = dcmread(get_testdata_file(ct_small_filename))
    ds2.PatientID = "CODES-PT"
    ds2.StudyDate = "20200101"
    ds2.SOPInstanceUID = "1.2.840.10008.codes.2"
    assert controller.anonymizer.anonymize(LocalSCU, ds2) is None
    codes2 = {str(item.CodeValue) for item in ds2.DeidentificationMethodCodeSequence}
    assert codes2 == {"113100", "113107", "113108", "113111"}


def test_safe_private_walk_dispositions(controller: ProjectController) -> None:
    """Retain Safe Private: KB keep/date/uid apply in the walk; unknown is removed."""
    from anonymizer.model.project import RETAIN_OPTIONS

    controller.model.confidentiality_options = RETAIN_OPTIONS
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "SAFE-PT"
    ds.StudyDate = "20200101"
    ds.SOPInstanceUID = "1.2.840.10008.safepriv.1"
    ds.add_new(0x00090010, "LO", "GEMS_PETD_01")
    ds.add_new(0x0009100F, "LO", "KEEPME")
    ds.add_new(0x00091005, "DT", "20200101120000")
    ds.add_new(0x00190010, "LO", "MMCPrivate")
    ds.add_new(0x0019101A, "UI", "1.2.3.4.5")
    ds.add_new(0x00110010, "LO", "ACME")
    ds.add_new(0x00111001, "LO", "SECRET")

    delta = resolve_date_delta(
        controller.anonymizer.model._tag_keep.get("00080020") or None,
        patient_id="SAFE-PT",
        days_from_lookup=0,
        base_date=None,
    )
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None

    assert ds[0x00090010].value == "GEMS_PETD_01"
    assert ds[0x0009100F].value == "KEEPME"
    assert str(ds[0x00091005].value) == apply_day_delta("20200101120000", delta)
    assert str(ds[0x0019101A].value) != "1.2.3.4.5"
    assert str(ds[0x0019101A].value).startswith(controller.model.uid_root)
    assert ds[0x00110010].value == "ACME"
    assert 0x00111001 not in ds


def test_hashdate_full_anonymize_sets_modified(controller: ProjectController) -> None:
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "HASHDATE-PT"
    ds.StudyDate = "20200101"
    ds.SOPInstanceUID = "1.2.840.10008.hashdate.1"
    controller.model.confidentiality_options |= {DeidMethodCode.MODIFIED_DATES}
    error = controller.anonymizer.anonymize(LocalSCU, ds)
    assert error is None
    assert ds.StudyDate != "20200101"
    assert ds.LongitudinalTemporalInformationModified == "MODIFIED"
    codes = {str(item.CodeValue) for item in ds.DeidentificationMethodCodeSequence}
    assert "113107" in codes


def _install_basedate_patient(anon: AnonymizerController, *, patient_id: str = "MRN1", basedate: str = "20180327") -> None:
    from anonymizer.model.anonymizer import CtpLookupPhiRow

    anon.model.upsert_ctp_lookup_phi(
        [
            CtpLookupPhiRow(
                patient_id=patient_id,
                anon_patient_id="SITE-1",
                date_offset=None,
                base_date=basedate,
            )
        ]
    )


def test_rebasedate_offset_math_and_explicit_origin(controller: ProjectController) -> None:
    """TCIA: anon_date = ORIGIN + (PHI_date − basedate)."""
    anon: AnonymizerController = controller.anonymizer
    _install_basedate_patient(anon)

    expected_offset = (datetime(1960, 1, 1) - datetime(2018, 3, 27)).days
    assert rebase_days("20180327", "19600101") == expected_offset
    assert rebase_days(None, "19600101") is None

    ds = Dataset()
    ds.add_new(0x00080020, "DA", "20180329")
    anon.model._tag_keep["00080020"] = "@rebasedate(this,19600101)"
    anon._anonymize_element(ds, ds[0x00080020], "MRN1", "SITE-1", None, REBASE_DELTA)
    # PHI 20180329 is +2 days from basedate 20180327 → ORIGIN+2
    assert ds.StudyDate == "19600103"


def test_rebasedate_bare_operand_uses_default_origin(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    _install_basedate_patient(anon)
    ds = Dataset()
    ds.add_new(0x00080020, "DA", "20180329")
    anon.model._tag_keep["00080020"] = "@rebasedate"
    anon._anonymize_element(ds, ds[0x00080020], "MRN1", "SITE-1", None, REBASE_DELTA)
    assert ds.StudyDate == "19600103"


def test_rebasedate_custom_origin(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    _install_basedate_patient(anon)
    ds = Dataset()
    ds.add_new(0x00080020, "DA", "20180329")
    anon.model._tag_keep["00080020"] = "@rebasedate(this,19700101)"
    anon._anonymize_element(ds, ds[0x00080020], "MRN1", "SITE-1", None, resolve_date_delta("@rebasedate(this,19700101)", patient_id="MRN1", days_from_lookup=0, base_date="20180327"))
    assert ds.StudyDate == "19700103"


def test_rebasedate_shifts_datetime_preserving_time(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    _install_basedate_patient(anon)
    ds = Dataset()
    ds.add_new(0x0008002A, "DT", "20180329123045.123456")
    anon.model._tag_keep["0008002A"] = "@rebasedate(this,19600101)"
    anon._anonymize_element(ds, ds[0x0008002A], "MRN1", "SITE-1", None, REBASE_DELTA)
    assert str(ds.AcquisitionDateTime).startswith("19600103")
    assert "123045" in str(ds.AcquisitionDateTime)


def test_rebasedate_preserves_study_interval(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    _install_basedate_patient(anon)
    anon.model._tag_keep["00080020"] = "@rebasedate(this,19600101)"

    early = Dataset()
    early.add_new(0x00080020, "DA", "20180327")
    late = Dataset()
    late.add_new(0x00080020, "DA", "20180426")  # +30 days
    anon._anonymize_element(early, early[0x00080020], "MRN1", "SITE-1", None, REBASE_DELTA)
    anon._anonymize_element(late, late[0x00080020], "MRN1", "SITE-1", None, REBASE_DELTA)

    assert early.StudyDate == "19600101"
    assert late.StudyDate == "19600131"
    assert (
        datetime.strptime(str(late.StudyDate), "%Y%m%d")
        - datetime.strptime(str(early.StudyDate), "%Y%m%d")
    ).days == 30


def test_rebasedate_longitudinal_provenance_registration(controller: ProjectController) -> None:
    """TCIA: basedate → (0012,0052)/(0012,0053)=REGISTRATION and MODIFIED."""
    anon: AnonymizerController = controller.anonymizer
    _install_basedate_patient(anon)

    ds = Dataset()
    ds.add_new(0x00080020, "DA", "20180329")
    anon.model._tag_keep["00080020"] = "@rebasedate(this,19600101)"
    anon._anonymize_element(ds, ds[0x00080020], "MRN1", "SITE-1", None, REBASE_DELTA)
    stamp_dates_modified(ds)
    stamp_rebase_registration(ds, "20180329", "20180327")
    assert ds.LongitudinalTemporalInformationModified == "MODIFIED"
    assert float(ds.LongitudinalTemporalOffsetFromEvent) == 2.0
    assert ds.LongitudinalTemporalEventType == "REGISTRATION"

    # Even without walking a date tag, basedate still stamps REGISTRATION + MODIFIED.
    bare = Dataset()
    stamp_rebase_registration(bare, "20180329", "20180327")
    assert bare.LongitudinalTemporalInformationModified == "MODIFIED"
    assert float(bare.LongitudinalTemporalOffsetFromEvent) == 2.0
    assert bare.LongitudinalTemporalEventType == "REGISTRATION"


def test_rebasedate_full_anonymize_with_ctp_basedate(controller: ProjectController, tmp_path: Path) -> None:
    """End-to-end: load basedate table, @rebasedate StudyDate, anonymize real DICOM."""
    from anonymizer.controller.ctp_lookup import commit_ctp_lookup, preview_ctp_lookup

    props = tmp_path / "rebase.properties"
    props.write_text(
        "ptid/12345=527408-000042\nbasedate/12345=20180327\n",
        encoding="utf-8",
    )
    commit_ctp_lookup(controller, preview_ctp_lookup(props))
    controller.model.confidentiality_options |= {DeidMethodCode.MODIFIED_DATES}
    controller.anonymizer.model._tag_keep["00080020"] = "@rebasedate(this,19600101)"
    controller.anonymizer.model._tag_keep["00080021"] = "@rebasedate(this,19600101)"
    controller.anonymizer.model.date_operands_present = True

    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "12345"
    ds.StudyDate = "20180329"
    if hasattr(ds, "SeriesDate"):
        ds.SeriesDate = "20180329"

    error = controller.anonymizer.anonymize(LocalSCU, ds)
    assert error is None
    assert ds.PatientID == "527408-000042"
    assert ds.StudyDate == "19600103"
    if hasattr(ds, "SeriesDate"):
        assert ds.SeriesDate == "19600103"
    assert ds.LongitudinalTemporalInformationModified == "MODIFIED"
    assert float(ds.LongitudinalTemporalOffsetFromEvent) == 2.0
    assert ds.LongitudinalTemporalEventType == "REGISTRATION"
    codes = {str(item.CodeValue) for item in ds.DeidentificationMethodCodeSequence}
    assert "113107" in codes


def test_hashdate_sets_modified_flag_via_provenance(controller: ProjectController) -> None:
    anon: AnonymizerController = controller.anonymizer
    ds = Dataset()
    ds.add_new(0x00080020, "DA", "20200101")
    anon.model._tag_keep["00080020"] = "@hashdate"
    anon._anonymize_element(ds, ds[0x00080020], "patient-x", "anon", None, resolve_date_delta("@hashdate", patient_id="patient-x", days_from_lookup=0, base_date=None))
    stamp_dates_modified(ds)
    assert ds.LongitudinalTemporalInformationModified == "MODIFIED"
