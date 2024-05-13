# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import time
from pydicom.dataset import Dataset
from tests.controller.helpers import send_file_to_scp, send_files_to_scp
from tests.controller.dicom_test_files import (
    cr1_filename,
    ct_small_filename,
    mr_small_filename,
    CR_STUDY_3_SERIES_3_IMAGES,
    CT_STUDY_1_SERIES_4_IMAGES,
)
from tests.controller.dicom_test_nodes import TEST_SITEID, TEST_UIDROOT, LocalStorageSCP
from model.anonymizer import AnonymizerModel


def test_send_cr1(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(cr1_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert len(phi.studies) == 1
    assert len(phi.studies[0].series) == 1
    assert phi.studies[0].study_uid == ds.StudyInstanceUID
    assert phi.studies[0].study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert phi.studies[0].anon_date_delta == date_delta
    assert phi.studies[0].study_desc == ds.get("StudyDescription")
    assert phi.studies[0].accession_number == ds.get("AccessionNumber")
    assert phi.studies[0].target_instance_count == 0  # Set by controller move operation
    assert phi.studies[0].series[0].series_uid == ds.get("SeriesInstanceUID")
    assert phi.studies[0].series[0].series_desc == ds.get("SeriesDescription")
    assert phi.studies[0].series[0].modality == ds.get("Modality")
    assert phi.studies[0].series[0].instance_count == 1


def test_send_ct_small(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(ct_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"
    assert model.get_anon_uid(ds.FrameOfReferenceUID) == prefix + ".4"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert len(phi.studies) == 1
    assert len(phi.studies[0].series) == 1
    assert phi.studies[0].study_uid == ds.StudyInstanceUID
    assert phi.studies[0].study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert phi.studies[0].anon_date_delta == date_delta
    assert phi.studies[0].study_desc == ds.get("StudyDescription")
    assert phi.studies[0].accession_number == ds.get("AccessionNumber")
    assert phi.studies[0].target_instance_count == 0  # Set by controller move operation
    assert phi.studies[0].series[0].series_uid == ds.get("SeriesInstanceUID")
    assert phi.studies[0].series[0].series_desc == ds.get("SeriesDescription")
    assert phi.studies[0].series[0].modality == ds.get("Modality")
    assert phi.studies[0].series[0].instance_count == 1


def test_send_mr_small(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(mr_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"
    assert model.get_anon_uid(ds.FrameOfReferenceUID) == prefix + ".4"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert len(phi.studies) == 1
    assert len(phi.studies[0].series) == 1
    assert phi.studies[0].study_uid == ds.StudyInstanceUID
    assert phi.studies[0].study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert phi.studies[0].anon_date_delta == date_delta
    assert phi.studies[0].study_desc == ds.get("StudyDescription")
    assert phi.studies[0].accession_number == ds.get("AccessionNumber")
    assert phi.studies[0].target_instance_count == 0  # Set by controller move operation
    assert phi.studies[0].series[0].series_uid == ds.get("SeriesInstanceUID")
    assert phi.studies[0].series[0].series_desc == ds.get("SeriesDescription")
    assert phi.studies[0].series[0].modality == ds.get("Modality")
    assert phi.studies[0].series[0].instance_count == 1


def test_send_ct_small_AND_mr_small(temp_dir: str, controller):
    # Send CT SMALL:
    ds: Dataset = send_file_to_scp(ct_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"
    assert model.get_anon_uid(ds.FrameOfReferenceUID) == prefix + ".4"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert len(phi.studies) == 1
    assert len(phi.studies[0].series) == 1
    assert phi.studies[0].study_uid == ds.StudyInstanceUID
    assert phi.studies[0].study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert phi.studies[0].anon_date_delta == date_delta
    assert phi.studies[0].study_desc == ds.get("StudyDescription")
    assert phi.studies[0].accession_number == ds.get("AccessionNumber")
    assert phi.studies[0].target_instance_count == 0  # Set by controller move operation
    assert phi.studies[0].series[0].series_uid == ds.get("SeriesInstanceUID")
    assert phi.studies[0].series[0].series_desc == ds.get("SeriesDescription")
    assert phi.studies[0].series[0].modality == ds.get("Modality")
    assert phi.studies[0].series[0].instance_count == 1

    # Send MR SMALL:
    ds: Dataset = send_file_to_scp(mr_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 2
    assert TEST_SITEID + "-000002" in dirlist

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".5"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".6"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".7"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert len(phi.studies) == 1
    assert len(phi.studies[0].series) == 1
    assert phi.studies[0].study_uid == ds.StudyInstanceUID
    assert phi.studies[0].study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert phi.studies[0].anon_date_delta == date_delta
    assert phi.studies[0].study_desc == ds.get("StudyDescription")
    assert phi.studies[0].accession_number == ds.get("AccessionNumber")
    assert phi.studies[0].target_instance_count == 0  # Set by controller move operation
    assert phi.studies[0].series[0].series_uid == ds.get("SeriesInstanceUID")
    assert phi.studies[0].series[0].series_desc == ds.get("SeriesDescription")
    assert phi.studies[0].series[0].modality == ds.get("Modality")
    assert phi.studies[0].series[0].instance_count == 1


def test_send_ct_Archibald_Doe(temp_dir: str, controller):
    dsets: Dataset = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    ds = dsets[0]
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"
    assert model.get_anon_uid(ds.FrameOfReferenceUID) == prefix + ".4"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert len(phi.studies) == 1
    assert len(phi.studies[0].series) == 1
    assert phi.studies[0].study_uid == ds.StudyInstanceUID
    assert phi.studies[0].study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert phi.studies[0].anon_date_delta == date_delta
    assert phi.studies[0].study_desc == ds.get("StudyDescription")
    assert phi.studies[0].accession_number == ds.get("AccessionNumber")
    assert phi.studies[0].target_instance_count == 0  # Set by controller move operation
    assert phi.studies[0].series[0].series_uid == ds.get("SeriesInstanceUID")
    assert phi.studies[0].series[0].series_desc == ds.get("SeriesDescription")
    assert phi.studies[0].series[0].modality == ds.get("Modality")
    assert phi.studies[0].series[0].instance_count == 4


def test_send_cr_and_ct_Archibald_Doe(temp_dir: str, controller):
    # Send CR_STUDY_3_SERIES_3_IMAGES:
    dsets: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, LocalStorageSCP, controller)
    time.sleep(1)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    ds = dsets[0]
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert len(phi.studies) == 1
    assert len(phi.studies[0].series) == 3
    assert phi.studies[0].study_uid == ds.StudyInstanceUID
    assert phi.studies[0].study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert phi.studies[0].anon_date_delta == date_delta
    assert phi.studies[0].study_desc == ds.get("StudyDescription")
    assert phi.studies[0].accession_number == ds.get("AccessionNumber")
    assert phi.studies[0].target_instance_count == 0  # Set by controller move operation
    assert sum([s.instance_count for s in phi.studies[0].series]) == 3
    for series in phi.studies[0].series:
        assert series.series_uid in [ds.get("SeriesInstanceUID") for ds in dsets]
        assert series.series_desc in [ds.get("SeriesDescription") for ds in dsets]
        assert series.modality in [ds.get("Modality") for ds in dsets]
        assert series.instance_count == 1

    # Send CT_STUDY_1_SERIES_4_IMAGES:
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, LocalStorageSCP, controller)
    time.sleep(1)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"  # Same Patient

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    ds = dsets[0]
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".8"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".9"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".10"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert len(phi.studies) == 2
    assert len(phi.studies[1].series) == 1
    assert phi.studies[1].study_uid == ds.StudyInstanceUID
    assert phi.studies[1].study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[1].study_date, phi.patient_id)
    assert phi.studies[1].anon_date_delta == date_delta
    assert phi.studies[1].study_desc == ds.get("StudyDescription")
    assert phi.studies[1].accession_number == ds.get("AccessionNumber")
    assert phi.studies[1].target_instance_count == 0  # Set by controller move operation
    assert phi.studies[1].series[0].series_uid == ds.get("SeriesInstanceUID")
    assert phi.studies[1].series[0].series_desc == ds.get("SeriesDescription")
    assert phi.studies[1].series[0].modality == ds.get("Modality")
    assert phi.studies[1].series[0].instance_count == 4
