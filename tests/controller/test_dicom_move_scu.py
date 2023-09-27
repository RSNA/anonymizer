# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import logging
import time
from queue import Queue
from pydicom.dataset import Dataset
from utils.storage import count_studies_series_images

from controller.project import ProjectController
from tests.controller.dicom_test_nodes import LocalStorageSCP, PACSSimulatorSCP
from tests.controller.helpers import (
    send_file_to_scp,
    send_files_to_scp,
    move_studies_from_pacs_simulator_scp_to_local_scp,
    pacs_storage_dir,
    local_storage_dir,
    verify_files_sent_to_pacs_simulator,
)
from controller.dicom_C_codes import C_FAILURE, C_SUCCESS, C_PENDING_A
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


def test_move_1_CT_file_from_pacs_with_file_to_unknown_AET(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    ux_Q: Queue[Dataset] = Queue()
    controller._move_study(PACSSimulatorSCP.aet, "UNKNOWNAE", ds.StudyInstanceUID, ux_Q)
    result = ux_Q.get()
    assert result
    assert ux_Q.empty()
    assert result.Status == C_FAILURE
    assert "destination unknown" in result.ErrorComment


def test_move_1_file_from_empty_pacs_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 0
    ux_Q: Queue[Dataset] = Queue()
    controller._move_study(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, "1.2.3.4.5.6", ux_Q
    )
    result = ux_Q.get()
    assert result
    assert ux_Q.empty()
    assert result.Status == C_SUCCESS
    assert result.NumberOfCompletedSuboperations == 0
    assert result.NumberOfFailedSuboperations == 0
    assert result.NumberOfWarningSuboperations == 0


def test_move_1_CT_file_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"
    ux_Q: Queue[Dataset] = Queue()
    controller._move_study(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, ds.StudyInstanceUID, ux_Q
    )
    result1 = ux_Q.get()
    assert result1
    assert result1.Status == C_PENDING_A
    result2 = ux_Q.get()
    assert result2.Status == C_SUCCESS
    assert result2.NumberOfCompletedSuboperations == 1
    assert result2.NumberOfFailedSuboperations == 0
    assert result2.NumberOfWarningSuboperations == 0
    time.sleep(1)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"


def test_move_of_unknown_StudyUID_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"
    ux_Q: Queue[Dataset] = Queue()
    controller._move_study(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, "1.2.3.4.5.6", ux_Q
    )
    result = ux_Q.get()
    assert result
    assert ux_Q.empty()
    assert result.Status == C_SUCCESS
    assert result.NumberOfCompletedSuboperations == 0
    assert result.NumberOfFailedSuboperations == 0
    assert result.NumberOfWarningSuboperations == 0


def test_move_of_3_studies_from_pacs_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send 3 studies to TEST PACS
    ds1: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    ds2: Dataset = send_file_to_scp(mr_small_filename, True, controller)
    dsets: list[Dataset] = send_files_to_scp(
        MR_STUDY_3_SERIES_11_IMAGES, True, controller
    )
    verify_files_sent_to_pacs_simulator([ds1, ds2] + dsets, temp_dir, controller)
    # Move 2 studies from TEST PACS to local storage
    assert move_studies_from_pacs_simulator_scp_to_local_scp(
        [ds1.StudyInstanceUID, ds2.StudyInstanceUID, dsets[0].StudyInstanceUID],
        controller,
    )
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 3
    time.sleep(0.5)
    total_studies = 0
    total_files = 0
    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(
            os.path.join(local_storage_dir(temp_dir), dirlist[i])
        )
        total_studies += studies
        total_files += images
    assert total_studies == 3
    assert total_files == 13
