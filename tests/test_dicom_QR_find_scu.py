# UNIT TESTS for controller/dicom_QR_find_scu.py
# use pytest from terminal to show full logging output
import logging
from controller.dicom_QR_find_scu import find
from controller.dicom_move_scu import move
from controller.dicom_echo_send_scu import echo

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# TODO: Instead of local PACS, run a local pynetdicom C-STORE SCP for testing with Storage and QueryRetrieve PresentationContexts
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


def test_move(temp_dir: str):
    assert move(
        TEST_SCP_IP,
        TEST_SCP_PORT,
        TEST_SCP_AET,
        TEST_SCU_IP,
        "PYANON",
        # "1.3.51.0.7.2580558702.65205.27203.38597.5639.39660.54942",
        "1.2.840.113619.2.278.3.2831181056.402.1645770506.560",
        temp_dir,
    )
