import os
from pydicom.dataset import Dataset
from model.project import SITEID


from tests.controller.helpers import (
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
    CR_STUDY_3_SERIES_3_IMAGES,
    CT_STUDY_1_SERIES_4_IMAGES,
    MR_STUDY_3_SERIES_11_IMAGES,
)


def test_send_1_CR_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    ds: Dataset = send_file_to_scp(cr1_filename, True)
    verify_files_sent_to_pacs_simulator([ds], temp_dir)


def test_send_1_CT_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    ds: Dataset = send_file_to_scp(ct_small_filename, True)
    verify_files_sent_to_pacs_simulator([ds], temp_dir)


def test_send_1_MR_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    ds: Dataset = send_file_to_scp(mr_small_filename, True)
    verify_files_sent_to_pacs_simulator([ds], temp_dir)


def test_send_CT_MR_files_find_all_studies_on_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    ds1: Dataset = send_file_to_scp(ct_small_filename, True)
    ds2: Dataset = send_file_to_scp(mr_small_filename, True)
    verify_files_sent_to_pacs_simulator([ds1, ds2], temp_dir)


def test_send_3_CR_files_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    dsets: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, True)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir)


def test_send_4_CT_files_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, True)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir)


def test_send_11_MR_files_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, True)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir)


def test_export_patient_CR_study_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    start_local_storage_scp(temp_dir)
    # Send 1 Study with 1 CR files to local storage:
    phi_dsets: list[Dataset] = send_files_to_scp([cr1_filename], False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    anon_pt_id = SITEID + "-000001"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    # Export this patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs([anon_pt_id])


def test_export_patient_CT_study_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    start_local_storage_scp(temp_dir)
    # Send 1 Study with 4 CT files to local storage:
    phi_dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    anon_pt_id = SITEID + "-000001"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    # Export this patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs([anon_pt_id])
