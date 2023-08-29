# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import logging
import time
from pydicom.dataset import Dataset
from controller.anonymize import uid_lookup, patient_id_lookup
from controller.dicom_ae import DICOMNode
from tests.controller.dicom_test_nodes import LocalStorageSCP
from tests.controller.helpers import (
    start_local_storage_scp,
    start_pacs_simulator_scp,
    send_file_to_scp,
    move_study_from_pacs_simulator_scp_to_local_scp,
    pacs_storage_dir,
    local_storage_dir,
)
from controller.dicom_return_codes import C_MOVE_UNKNOWN_AE, C_SUCCESS, C_PENDING_A
from model.project import UIDROOT, SITEID
from tests.controller.dicom_test_files import ct_small_filename

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def test_move_1_CT_file_from_pacs_with_file_to_unknown_AET(temp_dir: str):
    start_local_storage_scp(temp_dir)
    start_pacs_simulator_scp(temp_dir, [DICOMNode("127.0.0.1", 104, "UNKNOWNAE", True)])
    ds: Dataset = send_file_to_scp(ct_small_filename, True)
    results = move_study_from_pacs_simulator_scp_to_local_scp(ds.StudyInstanceUID)
    assert results
    assert len(results) == 1
    assert results[0].Status == C_MOVE_UNKNOWN_AE
    logger.info(results)


def test_move_1_file_from_empty_pacs_to_local_storage(temp_dir: str):
    start_local_storage_scp(temp_dir)
    start_pacs_simulator_scp(temp_dir)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 0
    results = move_study_from_pacs_simulator_scp_to_local_scp("1.2.3.4.5.6")
    assert results
    assert len(results) == 1
    assert results[0].Status == C_SUCCESS
    assert results[0].NumberOfCompletedSuboperations == 0
    assert results[0].NumberOfFailedSuboperations == 0


def test_move_1_CT_file_from_pacs_with_file_to_local_storage(temp_dir: str):
    start_local_storage_scp(temp_dir)
    start_pacs_simulator_scp(temp_dir)
    ds: Dataset = send_file_to_scp(ct_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"
    results = move_study_from_pacs_simulator_scp_to_local_scp(ds.StudyInstanceUID)
    assert results
    logger.info(results)
    assert len(results) == 2  # one pending and one completed result
    assert results[0].Status == C_PENDING_A
    assert results[1].Status == C_SUCCESS
    assert results[1].NumberOfCompletedSuboperations == 1
    assert results[1].NumberOfFailedSuboperations == 0
    time.sleep(1)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == SITEID + "-000001"


def test_move_of_unknown_StudyUID_from_pacs_with_file_to_local_storage(temp_dir: str):
    start_local_storage_scp(temp_dir)
    start_pacs_simulator_scp(temp_dir)
    ds: Dataset = send_file_to_scp(ct_small_filename, True)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"
    results = move_study_from_pacs_simulator_scp_to_local_scp("1.2.3.4.5.6")
    assert results
    logger.info(results)
    assert len(results) == 1
    assert results[0].Status == C_SUCCESS
    assert results[0].NumberOfCompletedSuboperations == 0
    assert results[0].NumberOfFailedSuboperations == 0
