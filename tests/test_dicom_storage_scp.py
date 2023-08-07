# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import logging
from controller.dicom_storage_scp import start, stop, server_running
from controller.dicom_echo_send_scu import echo, send
from pydicom.data import get_testdata_file, fetch_data_files

logger = logging.getLogger(__name__)

# TEST SCP
TEST_SCP_IP = "127.0.0.1"
TEST_SCP_PORT = 1045
TEST_SCP_AET = "SCP_AET"

# TEST_SCU
TEST_SCU_IP = "127.0.0.1"
TEST_SCU_AET = "SCU_AET"


def test_start_stop_dicom_storage_scp(temp_dir):
    logger.info(f"start local scp on port {TEST_SCP_PORT}")
    assert not server_running()
    assert start(TEST_SCP_IP, TEST_SCP_PORT, TEST_SCP_AET, temp_dir)
    assert server_running()
    logger.info("stop local scp")
    stop(True)
    assert not server_running()


def test_echo_fail():
    logger.info("C-ECHO to local scp which not running")
    assert not server_running()
    assert not echo(TEST_SCP_IP, TEST_SCP_PORT, TEST_SCP_AET, TEST_SCU_IP, TEST_SCU_AET)


def test_start_echo_stop_dicom_storage_scp(temp_dir):
    logger.info(f"start local scp on port {TEST_SCP_PORT}")
    assert start(TEST_SCP_IP, TEST_SCP_PORT, TEST_SCP_AET, temp_dir)
    assert server_running()
    logger.info("C-ECHO to local scp")
    assert echo(TEST_SCP_IP, TEST_SCP_PORT, TEST_SCP_AET, TEST_SCU_IP, TEST_SCU_AET)
    stop(True)
    assert not server_running()


def test_start_send_ct_small_stop_dicom_storage_scp(temp_dir):
    logger.info(f"start local scp on port {TEST_SCP_PORT}")
    assert start(TEST_SCP_IP, TEST_SCP_PORT, TEST_SCP_AET, temp_dir)
    assert server_running()
    logger.info("C-STORE to local scp")
    # Use test data which comes with pydicom, if not found, download with fetch_data_files()
    ct_small = get_testdata_file("CT_small.dcm")
    if not ct_small:
        fetch_data_files()
    assert ct_small
    logger.info(f"Sending pydicom test data set: {ct_small}")
    assert send(
        TEST_SCP_IP,
        TEST_SCP_PORT,
        TEST_SCP_AET,
        TEST_SCU_IP,
        TEST_SCU_AET,
        [ct_small],
    )
    stop(True)
    assert not server_running()


def test_start_send_mr_small_stop_dicom_storage_scp(temp_dir):
    logger.info(f"start local scp on port {TEST_SCP_PORT}")
    assert start(TEST_SCP_IP, TEST_SCP_PORT, TEST_SCP_AET, temp_dir)
    assert server_running()
    logger.info("C-STORE to local scp")
    # Use test data which comes with pydicom, if not found, download with fetch_data_files()
    mr_small = get_testdata_file("MR_small.dcm")
    if not mr_small:
        fetch_data_files()
    assert mr_small
    logger.info(f"Sending pydicom test data set: {mr_small}")
    assert send(
        TEST_SCP_IP,
        TEST_SCP_PORT,
        TEST_SCP_AET,
        TEST_SCU_IP,
        TEST_SCU_AET,
        [mr_small],
    )
    stop(True)
    assert not server_running()
