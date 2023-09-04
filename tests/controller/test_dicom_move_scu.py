# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import logging
import time
from pydicom.dataset import Dataset
from utils.storage import count_dcm_files_and_studies
from controller.anonymize import uid_lookup, patient_id_lookup
from controller.dicom_ae import DICOMNode
from tests.controller.dicom_test_nodes import LocalStorageSCP
from tests.controller.helpers import (
    start_local_storage_scp,
    start_pacs_simulator_scp,
    send_file_to_scp,
    send_files_to_scp,
    move_study_from_pacs_simulator_scp_to_local_scp,
    move_studies_from_pacs_simulator_scp_to_local_scp,
    pacs_storage_dir,
    local_storage_dir,
    verify_files_sent_to_pacs_simulator,
)
from controller.dicom_return_codes import C_MOVE_UNKNOWN_AE, C_SUCCESS, C_PENDING_A
from model.project import UIDROOT, SITEID
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


def test_move_of_3_studies_from_pacs_to_local_storage(temp_dir: str):
    # Send 2 studies to TEST PACS
    start_pacs_simulator_scp(temp_dir)
    ds1: Dataset = send_file_to_scp(ct_small_filename, True)
    ds2: Dataset = send_file_to_scp(mr_small_filename, True)
    dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, True)
    verify_files_sent_to_pacs_simulator([ds1, ds2] + dsets, temp_dir)
    # Move 2 studies from TEST PACS to local storage
    start_local_storage_scp(temp_dir)
    assert move_studies_from_pacs_simulator_scp_to_local_scp(
        [ds1.StudyInstanceUID, ds2.StudyInstanceUID, dsets[0].StudyInstanceUID]
    )
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 3
    time.sleep(0.5)
    total_studies = 0
    total_files = 0
    for i in range(len(dirlist)):
        studies, files = count_dcm_files_and_studies(
            os.path.join(local_storage_dir(temp_dir), dirlist[i])
        )
        total_studies += studies
        total_files += files
    assert total_studies == 3
    assert total_files == 13
