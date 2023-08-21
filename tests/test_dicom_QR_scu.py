# UNIT TESTS for controller/dicom_QR_find_scu.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import logging
import os
from unittest import result
from controller.dicom_return_codes import C_MOVE_UNKNOWN_AE, C_PENDING_A, C_SUCCESS

from tests.helpers import (
    start_local_storage_scp,
    start_pacs_simulator_scp,
    echo_pacs_simulator_scp,
    send_file_to_scp,
    find_all_studies_on_test_pacs_scp,
    move_study_from_test_pacs_scp_to_local_scp,
    pacs_storage_dir,
    local_storage_dir,
)
from tests.dcm_tst_files import (
    ct_small_filename,
    ct_small_SeriesInstanceUID,
    ct_small_StudyInstanceUID,
    ct_small_patient_name,
    ct_small_patient_id,
    mr_small_filename,
    mr_small_SeriesInstanceUID,
    mr_small_StudyInstanceUID,
    mr_small_patient_name,
    mr_small_patient_id,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# UNIT TESTS:
def test_echo_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    echo_pacs_simulator_scp()


def test_send_1_CT_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    send_file_to_scp(ct_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ct_small_SeriesInstanceUID + ".1.dcm"


def test_send_1_MR_file_to_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    send_file_to_scp(mr_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == mr_small_SeriesInstanceUID + ".1.dcm"


def test_send_2_files_find_all_studies_on_test_pacs(temp_dir: str):
    start_pacs_simulator_scp(temp_dir)
    send_file_to_scp(ct_small_filename, True)
    send_file_to_scp(mr_small_filename, True)
    results = find_all_studies_on_test_pacs_scp()
    assert results
    assert len(results) == 2
    assert (
        results[0].PatientName == ct_small_patient_name
        or results[1].PatientName == ct_small_patient_name
    )
    assert (
        results[0].PatientID == ct_small_patient_id
        or results[1].PatientID == ct_small_patient_id
    )
    assert (
        results[1].PatientName == mr_small_patient_name
        or results[0].PatientName == mr_small_patient_name
    )
    assert (
        results[1].PatientID == mr_small_patient_id
        or results[0].PatientID == mr_small_patient_id
    )


def test_move_1_CT_file_from_pacs_with_file_to_unknown_AET(temp_dir: str):
    start_local_storage_scp(temp_dir)
    start_pacs_simulator_scp(temp_dir, {"UNKNOWNAE": ("127.0.0.1", 104)})
    send_file_to_scp(ct_small_filename, True)
    results = move_study_from_test_pacs_scp_to_local_scp(ct_small_StudyInstanceUID)
    assert results
    assert len(results) == 1
    assert results[0].Status == C_MOVE_UNKNOWN_AE
    logger.info(results)


def test_move_1_file_from_empty_pacs_to_local_storage(temp_dir: str):
    start_local_storage_scp(temp_dir)
    start_pacs_simulator_scp(temp_dir)
    results = move_study_from_test_pacs_scp_to_local_scp(ct_small_StudyInstanceUID)
    assert results
    assert len(results) == 1
    assert results[0].Status == C_SUCCESS
    assert results[0].NumberOfCompletedSuboperations == 0
    assert results[0].NumberOfFailedSuboperations == 0


def test_move_1_CT_file_from_pacs_with_file_to_local_storage(temp_dir: str):
    start_local_storage_scp(temp_dir)
    start_pacs_simulator_scp(temp_dir)
    send_file_to_scp(ct_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ct_small_SeriesInstanceUID + ".1.dcm"
    results = move_study_from_test_pacs_scp_to_local_scp(ct_small_StudyInstanceUID)
    assert results
    logger.info(results)
    assert len(results) == 2  # one pending and one completed result
    assert results[0].Status == C_PENDING_A
    assert results[1].Status == C_SUCCESS
    assert results[1].NumberOfCompletedSuboperations == 1
    assert results[1].NumberOfFailedSuboperations == 0
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == "DEFAULT-SITE-000001"


def test_move_of_unknown_StudyUID_from_pacs_with_file_to_local_storage(temp_dir: str):
    start_local_storage_scp(temp_dir)
    start_pacs_simulator_scp(temp_dir)
    send_file_to_scp(ct_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ct_small_SeriesInstanceUID + ".1.dcm"
    results = move_study_from_test_pacs_scp_to_local_scp("1.2.3.4.5.6")
    assert results
    logger.info(results)
    assert len(results) == 1
    assert results[0].Status == C_SUCCESS
    assert results[0].NumberOfCompletedSuboperations == 0
    assert results[0].NumberOfFailedSuboperations == 0
