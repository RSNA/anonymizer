import os
import time
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError
import tests.controller.dicom_pacs_simulator_scp as pacs_simulator_scp
from controller.project import ProjectController

from utils.storage import count_dcm_files_and_studies
from pydicom.data import get_testdata_file

# DICOM NODES involved in tests:
from tests.controller.dicom_test_nodes import PACSSimulatorSCP

from tests.controller.helpers import (
    pacs_storage_dir,
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


def test_send_invalid_filepath_to_test_pacs(
    temp_dir: str, controller: ProjectController
):
    try:
        controller.send(["does_not_exist.dcm"], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, FileNotFoundError)


def test_send_connection_error(temp_dir: str, controller: ProjectController):
    # Stop PACS Simulator SCP then try to send a file:
    pacs_simulator_scp.stop()
    try:
        controller.send([cr1_filename], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, ConnectionError)


def test_send_no_file_meta_dcm(temp_dir: str, controller: ProjectController):
    filepath = str(get_testdata_file("no_meta.dcm"))
    assert filepath
    try:
        controller.send([filepath], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, InvalidDicomError)


def test_send_SOP_class_not_supported(temp_dir: str, controller: ProjectController):
    filepath = str(get_testdata_file("rtplan.dcm"))
    assert filepath
    try:
        controller.send([filepath], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, ValueError)  # No presentation context for RT Plan Storage


def test_send_missing_SOPInstanceUID_AttributeError(
    temp_dir: str, controller: ProjectController
):
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    # Remove SOPInstanceUID from dataset:
    del ds.SOPInstanceUID
    # Save dataset to new file in temp_dir:
    filepath = os.path.join(temp_dir, "missing_SOPInstanceUID.dcm")
    ds.save_as(filepath)
    try:
        controller.send([filepath], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, AttributeError)  # Required element missing: SOPInstanceUID


# TODO: tests for DICOMRuntimeError (range of invalid responses from pacs) & RuntimeError (send_cstore called without association)


def test_send_1_CR_file_to_test_pacs(temp_dir: str, controller: ProjectController):
    ds: Dataset = send_file_to_scp(cr1_filename, True, controller)
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


def test_send_1_CT_file_to_test_pacs(temp_dir: str, controller: ProjectController):
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


def test_send_1_MR_file_explicit__VR_little_endian_to_test_pacs(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(mr_small_filename, True, controller)
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


def test_send_1_MR_file_implicit_VR_little_endian_to_test_pacs(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(mr_small_implicit_filename, True, controller)
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


# Explicit VR Big Endian Transfer Syntax is supported but uncommon and to be retired:
def test_send_1_MR_file_explicit_VR_big_endian_to_test_pacs(
    temp_dir: str, controller: ProjectController
):
    ds = get_testdata_file(mr_small_bigendian_filename, read=True)
    assert isinstance(ds, Dataset)
    dcm_file_path = str(get_testdata_file(mr_small_bigendian_filename))
    assert dcm_file_path
    assert controller.send(
        [dcm_file_path],
        PACSSimulatorSCP.aet,
        controller.get_radiology_storage_contexts_BIGENDIAN(),
    )
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


def test_send_CT_MR_files_find_all_studies_on_test_pacs(
    temp_dir: str, controller: ProjectController
):
    ds1: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    ds2: Dataset = send_file_to_scp(mr_small_filename, True, controller)
    verify_files_sent_to_pacs_simulator([ds1, ds2], temp_dir, controller)


def test_send_3_CR_files_to_test_pacs(temp_dir: str, controller: ProjectController):
    dsets: list[Dataset] = send_files_to_scp(
        CR_STUDY_3_SERIES_3_IMAGES, True, controller
    )
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)


def test_send_4_CT_files_to_test_pacs(temp_dir: str, controller: ProjectController):
    dsets: list[Dataset] = send_files_to_scp(
        CT_STUDY_1_SERIES_4_IMAGES, True, controller
    )
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)


def test_send_11_MR_files_to_test_pacs(temp_dir: str, controller: ProjectController):
    dsets: list[Dataset] = send_files_to_scp(
        MR_STUDY_3_SERIES_11_IMAGES, True, controller
    )
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)


def test_export_patient_CR_study_to_test_pacs(
    temp_dir: str, controller: ProjectController
):
    # Send 1 Study with 1 CR files to local storage:
    phi_dsets: list[Dataset] = send_files_to_scp([cr1_filename], False, controller)
    time.sleep(0.5)
    dirlist = os.listdir(controller.model.storage_dir)
    anon_pt_id = controller.model.siteid + "-000001"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    # Export this patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs([anon_pt_id], controller)


def test_export_patient_CT_study_to_test_pacs(
    temp_dir: str, controller: ProjectController
):
    # Send 1 Study with 4 CT files to local storage:
    phi_dsets: list[Dataset] = send_files_to_scp(
        CT_STUDY_1_SERIES_4_IMAGES, False, controller
    )
    time.sleep(0.5)
    dirlist = os.listdir(controller.model.storage_dir)
    anon_pt_id = controller.model.siteid + "-000001"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    # Export this patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs([anon_pt_id], controller)


def test_export_1_patient_2_studies_CR_CT_to_test_pacs(
    temp_dir: str, controller: ProjectController
):
    # SAME Patient: (Doe^Archibald)
    # Send CR & CT studies to local storage:
    # Send 1 Study with 3 CR files to local storage:
    cr_phi_dsets: list[Dataset] = send_files_to_scp(
        CR_STUDY_3_SERIES_3_IMAGES, False, controller
    )
    assert cr_phi_dsets[0].PatientName == "Doe^Archibald"
    # Send 1 Study with 4 CT files to local storage:
    ct_phi_dsets: list[Dataset] = send_files_to_scp(
        CT_STUDY_1_SERIES_4_IMAGES, False, controller
    )
    time.sleep(0.5)
    assert ct_phi_dsets[0].PatientName == "Doe^Archibald"
    dirlist = os.listdir(controller.model.storage_dir)
    anon_pt_id = controller.model.siteid + "-000001"
    assert len(dirlist) == 1
    assert anon_pt_id in dirlist
    # Check 2 studies and 7 files in patient directory on local storage:
    assert count_dcm_files_and_studies(
        os.path.join(controller.model.storage_dir, anon_pt_id)
    ) == (2, 7)
    # Export these patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs([anon_pt_id], controller)
    time.sleep(0.5)
    # Check 7 files in test pacs directory:
    assert len(os.listdir(pacs_storage_dir(temp_dir))) == 7


def test_export_2_patients_to_test_pacs(temp_dir: str, controller: ProjectController):
    # Send Patient 1: 1 CR study to local storage:
    cr_phi_dsets: list[Dataset] = send_files_to_scp(
        CR_STUDY_3_SERIES_3_IMAGES, False, controller
    )
    assert cr_phi_dsets[0].PatientName == "Doe^Archibald"
    # Send Patient 2: 1 Study with 11 MR files to local storage:
    mr_phi_dsets: list[Dataset] = send_files_to_scp(
        MR_STUDY_3_SERIES_11_IMAGES, False, controller
    )
    time.sleep(0.5)
    assert mr_phi_dsets[0].PatientName == "Doe^Peter"
    dirlist = os.listdir(controller.model.storage_dir)
    ct_anon_pt_id = controller.model.siteid + "-000001"
    mr_anon_pt_id = controller.model.siteid + "-000002"
    assert len(dirlist) == 2
    assert ct_anon_pt_id in dirlist
    assert mr_anon_pt_id in dirlist
    # Check 1 study and 3 files in ct patient directory on local storage:
    assert count_dcm_files_and_studies(
        os.path.join(controller.model.storage_dir, ct_anon_pt_id)
    ) == (1, 3)
    # Check 1 study and 11 files in mr patient directory on local storage:
    assert count_dcm_files_and_studies(
        os.path.join(controller.model.storage_dir, mr_anon_pt_id)
    ) == (1, 11)
    # Export these patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs(
        [ct_anon_pt_id, mr_anon_pt_id], controller
    )
    # Check 14 files in test pacs directory:
    assert len(os.listdir(pacs_storage_dir(temp_dir))) == 14


def test_export_4_patients_to_test_pacs(temp_dir: str, controller: ProjectController):
    # Send Patient 1: 1 CR study to local storage:
    cr_phi_dsets: list[Dataset] = send_files_to_scp(
        CR_STUDY_3_SERIES_3_IMAGES, False, controller
    )
    assert cr_phi_dsets[0].PatientName == "Doe^Archibald"
    # Send Patient 2: 1 Study with 11 MR files to local storage:
    mr_phi_dsets: list[Dataset] = send_files_to_scp(
        MR_STUDY_3_SERIES_11_IMAGES, False, controller
    )
    assert mr_phi_dsets[0].PatientName == "Doe^Peter"
    # Send Patient 3: 1 Study with 1 CT file to local storage:
    ctsmall_ds: Dataset = send_file_to_scp(ct_small_filename, False, controller)
    # Send Patient 4: 1 Study with 1 MR file to local storage:
    mrsmall_ds: Dataset = send_file_to_scp(mr_small_filename, False, controller)
    time.sleep(0.5)
    dirlist = os.listdir(controller.model.storage_dir)
    ct_anon_pt_id = controller.model.siteid + "-000001"
    mr_anon_pt_id = controller.model.siteid + "-000002"
    ctsmall_anon_pt_id = controller.model.siteid + "-000003"
    mrsmall_anon_pt_id = controller.model.siteid + "-000004"
    assert len(dirlist) == 4
    assert ct_anon_pt_id in dirlist
    assert mr_anon_pt_id in dirlist
    assert ctsmall_anon_pt_id in dirlist
    assert mrsmall_anon_pt_id in dirlist
    # Check 1 study and 3 files in ct patient 1 directory on local storage:
    assert count_dcm_files_and_studies(
        os.path.join(controller.model.storage_dir, ct_anon_pt_id)
    ) == (1, 3)
    # Check 1 study and 11 files in mr patient 2 directory on local storage:
    assert count_dcm_files_and_studies(
        os.path.join(controller.model.storage_dir, mr_anon_pt_id)
    ) == (1, 11)
    # Check 1 study and 1 files in ctsmall patient 3 directory on local storage:
    assert count_dcm_files_and_studies(
        os.path.join(controller.model.storage_dir, ctsmall_anon_pt_id)
    ) == (1, 1)
    # Check 1 study and 1 files in mrsmall patient 4 directory on local storage:
    assert count_dcm_files_and_studies(
        os.path.join(controller.model.storage_dir, mrsmall_anon_pt_id)
    ) == (1, 1)
    # Export these patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs(
        [ct_anon_pt_id, mr_anon_pt_id, ctsmall_anon_pt_id, mrsmall_anon_pt_id],
        controller,
    )
    # Check 16 files in test pacs directory:
    assert len(os.listdir(pacs_storage_dir(temp_dir))) == 16


# TODO: test export: active storage directory not set, invalid patient directory, valid dir but not files, connection error, invalid response from PACS
# TODO: test retry mechanism for failed export
