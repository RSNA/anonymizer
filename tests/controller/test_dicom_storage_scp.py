# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import time
from pathlib import Path
from pydicom import dcmread
from pydicom.dataset import Dataset
from pydicom.data import get_testdata_file
from pynetdicom.presentation import PresentationContext, build_context
from tests.controller.helpers import send_file_to_scp, send_files_to_scp
from tests.controller.dicom_test_files import (
    cr1_filename,
    ct_small_filename,
    mr_small_filename,
    CR_STUDY_3_SERIES_3_IMAGES,
    CT_STUDY_1_SERIES_4_IMAGES,
    COMPRESSED_TEST_FILES,
)
from tests.controller.dicom_test_nodes import TEST_SITEID, TEST_UIDROOT, LocalStorageSCP
from controller.project import ProjectController
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


# Test sending compressed syntaxes to local storage SCP:
# TODO: loop through COMPRESSED_TEST_FILES in single test?


# Transfer Syntax: "1.2.840.10008.1.2.4.50",  # JPEG Baseline ISO_10918_1
# SOPClass: 1.2.840.10008.5.1.4.1.1.7 # Secondary Capture
# No PatientID & PatientName, StudyDate
def test_send_JPEG_Baseline(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG_Baseline"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_BASELINE_TS = "1.2.840.10008.1.2.4.50"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_BASELINE_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    # Try and send this Secondary Capture to LocalStorageSCP, default config of does not include SC
    # This should fail to establish an association due to no matching presentation contexts:
    try:
        files_sent = controller.send([dcm_file_path], LocalStorageSCP)
    except Exception as e:
        assert "No presentation context" in str(e)

    # By default, LocalStorageSCP is configured to only accept uncompressed syntaxes

    # Add Secondary Capture to ProjectModel storage classes:
    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    # Add JPEG Baseline to ProjectModel transfer syntaxes:
    controller.model.add_transfer_syntax(JPEG_BASELINE_TS)
    # Restart LocalStorageSCP to apply new config:
    controller.update_model()

    # Try again to send test file, even though LocalStorageSCP is setup with required context, send_context must be specified:
    try:
        files_sent = controller.send([dcm_file_path], LocalStorageSCP)
    except Exception as e:
        assert "No presentation context" in str(e)

    # Create Presentation Context for sending as per the file format, since no transcoding is implemented:
    # If this is not specified (as above in last send) the ProjectController AE will use the SCP contexts in requested_contexts property
    # which includes the default syntaxes and the negotiation will settle on first common syntax which wil be Explicit VR Little Endian
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_BASELINE_TS)

    # Try again to send test file to LocalStorageSCP, this should now succeed
    files_sent = controller.send([dcm_file_path], LocalStorageSCP, [send_context])

    assert files_sent == 1

    time.sleep(0.5)

    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    # This test file has no patient ID so it will file in default anonymized patient directory site_id + "000000"
    assert dirlist[0] == controller.anonymizer.model.default_anon_pt_id
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.study_desc == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.series_desc == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instance_count == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_BASELINE_TS
    assert ds.PatientID == controller.anonymizer.model.default_anon_pt_id
    assert ds.PatientName == controller.anonymizer.model.default_anon_pt_id
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.51" JPEG Extended
def test_send_JPEG_Extended(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG_Extended"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_EXTENDED_TS = "1.2.840.10008.1.2.4.51"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert ds

    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_EXTENDED_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    controller.model.add_transfer_syntax(JPEG_EXTENDED_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_EXTENDED_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP, [send_context])

    assert files_sent == 1

    time.sleep(1)

    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.sex == ds.get("PatientSex")
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.study_desc == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.series_desc == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instance_count == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_EXTENDED_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.70" Nonhierarchical, First-Order Prediction (Processes 14 [Selection Value 1])
def test_send_JPEG_Lossless_P14_FOP(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG_Lossless_P14_FOP"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_LOSSLESS_P14_TS = "1.2.840.10008.1.2.4.70"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert ds

    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LOSSLESS_P14_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    controller.model.add_transfer_syntax(JPEG_LOSSLESS_P14_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_LOSSLESS_P14_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP, [send_context])

    assert files_sent == 1

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

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.sex == ds.get("PatientSex")
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.study_desc == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.series_desc == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instance_count == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LOSSLESS_P14_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.80" JPEG-LS Lossless
def test_send_JPEG_LS_Lossless(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG-LS_Lossless"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.4"  # MR Image Storage
    JPEG_LS_LOSSLESS_TS = "1.2.840.10008.1.2.4.80"
    # Ensure test file is present from assets/test_files:
    ds = get_testdata_file(filename, read=True)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LS_LOSSLESS_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_transfer_syntax(JPEG_LS_LOSSLESS_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_LS_LOSSLESS_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP, [send_context])

    assert files_sent == 1

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

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.sex == ds.get("PatientSex")
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.study_desc == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.series_desc == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instance_count == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LS_LOSSLESS_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.81" JPEG-LS Lossy
# This Storage class not provided in pydicom data, so use test file from assets
def test_send_JPEG_LS_Lossy(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG-LS_Lossy"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_LS_LOSSY_TS = "1.2.840.10008.1.2.4.81"

    if "test_dcm_files" in filename:
        # Get file from test assets:
        dcm_file_path = Path("tests/controller/assets/", filename)
        ds = dcmread(dcm_file_path)
    else:
        # Get test file from pydicom data:
        ds = get_testdata_file(filename, read=True)
        dcm_file_path = str(get_testdata_file(filename))

    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LS_LOSSY_TS

    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    controller.model.add_transfer_syntax(JPEG_LS_LOSSY_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_LS_LOSSY_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP, [send_context])

    assert files_sent == 1

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

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.sex == ds.get("PatientSex")
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.study_desc == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.series_desc == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instance_count == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LS_LOSSY_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.81" JPEG-2000 Lossless
def test_send_JPEG_2000_Lossless(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG2000_Lossless"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.4"  # MR Image Storage
    JPEG_2000_LOSSLESS_TS = "1.2.840.10008.1.2.4.90"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_2000_LOSSLESS_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_transfer_syntax(JPEG_2000_LOSSLESS_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_2000_LOSSLESS_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP, [send_context])

    assert files_sent == 1

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

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.sex == ds.get("PatientSex")
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.study_desc == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.series_desc == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instance_count == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_2000_LOSSLESS_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.81" JPEG-2000
def test_send_JPEG_2000(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG2000"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_2000_TS = "1.2.840.10008.1.2.4.91"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_2000_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    controller.model.add_transfer_syntax(JPEG_2000_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_2000_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP, [send_context])

    assert files_sent == 1

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

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    phi = model.get_phi(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.sex == ds.get("PatientSex")
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.study_desc == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.series_desc == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instance_count == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_2000_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD
