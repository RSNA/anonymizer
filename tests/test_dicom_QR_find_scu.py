# UNIT TESTS for controller/dicom_QR_find_scu.py
# use pytest from terminal to show full logging output
import logging
import os
import re
from controller.dicom_QR_find_scu import find
from controller.dicom_move_scu import move
from controller.dicom_echo_send_scu import echo
from controller.dicom_storage_scp import start, stop, server_running

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# TODO: Instead of PACS, run a local pynetdicom C-STORE SCP for testing with Storage and QueryRetrieve PresentationContexts
TEST_PACS_IP = "127.0.0.1"
TEST_PACS_PORT = 11112
TEST_PACS_AET = "MDEDEV"

TEST_LOCAL_SCP_IP = "127.0.0.1"
TEST_LOCAL_SCP_PORT = 1045
TEST_LOCAL_SCP_AET = "PYANON"  # ip and port setup on PACS

TEST_SCU_IP = "127.0.0.1"
TEST_SCU_AET = "SCU_AET"


def test_find(temp_dir):
    logger.info(f"echo PACS@{TEST_PACS_IP}:{TEST_PACS_PORT}:{TEST_PACS_AET}")
    assert echo(TEST_PACS_IP, TEST_PACS_PORT, TEST_PACS_AET, TEST_SCU_IP, TEST_SCU_AET)
    logger.info(f"find all studies on PACS...")
    assert find(
        TEST_PACS_IP,
        TEST_PACS_PORT,
        TEST_PACS_AET,
        TEST_SCU_IP,
        TEST_SCU_AET,
        "",
        "",
        "",
        "",
        "",
    )


def test_move(temp_dir: str):
    logger.info(
        f"start local storage scp@{TEST_LOCAL_SCP_IP}:{TEST_LOCAL_SCP_PORT}:{TEST_LOCAL_SCP_AET}"
    )
    assert not server_running()
    assert start(TEST_LOCAL_SCP_IP, TEST_LOCAL_SCP_PORT, TEST_LOCAL_SCP_AET, temp_dir)
    assert server_running()
    result = move(
        TEST_PACS_IP,
        TEST_PACS_PORT,
        TEST_PACS_AET,
        TEST_SCU_IP,
        TEST_SCU_AET,
        TEST_LOCAL_SCP_AET,
        "1.3.51.0.7.2580558702.65205.27203.38597.5639.39660.54942",
        # "1.2.410.200059.12.1.100.20220914095120859.15",
        # "1.2.840.113619.2.278.3.2831181056.402.1645770506.560",
        # "1.2.826.0.1.3680043.8.1055.1.20111102150758591.92402465.76095170",
    )
    logger.info("stop local storage scp")
    stop(True)
    assert not server_running()
    assert result
    logger.info(os.listdir(temp_dir))
    # TODO: check if file is in temp_dir
