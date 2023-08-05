# UNIT TESTS for controller/dicom_QR_find_scu.py
# use pytest from terminal to show full logging output
import logging
from controller.dicom_QR_find_scu import find
from controller.dicom_echo_send_scu import echo

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# TODO: run test local scp using pynetdicom and local dicom files in /dicom
TEST_SCP_IP = "127.0.0.1"
TEST_SCP_PORT = 11112
TEST_SCP_AET = "MDEDEV"

TEST_SCU_IP = "127.0.0.1"
TEST_SCU_AET = "SCU_AET"


def test_find(temp_dir):
    logger.info(f"echo scp on port {TEST_SCP_PORT}")
    assert echo(TEST_SCP_IP, TEST_SCP_PORT, TEST_SCP_AET, TEST_SCU_IP, TEST_SCU_AET)
    logger.info(f"find scp on port {TEST_SCP_PORT}")
    assert find(
        TEST_SCP_IP,
        TEST_SCP_PORT,
        TEST_SCP_AET,
        TEST_SCU_IP,
        TEST_SCU_AET,
        "",
        "",
        "",
        "",
        "",
    )
