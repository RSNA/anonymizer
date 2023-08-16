# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import logging
import queue
import controller.dicom_storage_scp as storage_scp
from controller.dicom_echo_scu import echo
from controller.dicom_send_scu import send, SendRequest, SendResponse
from pydicom.data import get_testdata_file, fetch_data_files
from controller.dicom_return_codes import C_MOVE_UNKNOWN_AE, C_PENDING_A, C_SUCCESS

from tests.helpers import (
    start_local_storage_scp,
    echo_local_storage_scp,
    send_file_to_scp,
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


def test_start_stop_dicom_storage_scp(temp_dir):
    start_local_storage_scp(temp_dir)


def test_start_echo_stop_dicom_storage_scp(temp_dir):
    start_local_storage_scp(temp_dir)
    echo_local_storage_scp()


def test_start_send_ct_small_stop_dicom_storage_scp(temp_dir):
    start_local_storage_scp(temp_dir)
    send_file_to_scp(ct_small_filename, False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == "DEFAULT-SITE-000001"


def test_start_send_mr_small_stop_dicom_storage_scp(temp_dir):
    start_local_storage_scp(temp_dir)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    logging.info(dirlist)
    send_file_to_scp(mr_small_filename, False)
    dirlist = os.listdir(local_storage_dir(temp_dir))
    assert len(dirlist) == 1
    logging.info(dirlist)
    assert dirlist[0] == "DEFAULT-SITE-000001"


# TODO: test with multiple files, see CT2N, CT5N, MR2N dirs of pydicom test data
