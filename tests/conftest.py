# tests/conftest.py

import shutil
import tempfile
import pytest
import logging
from controller.anonymize import clear_lookups
from controller.dicom_storage_scp import stop as local_storage_scp_stop
from tests.dicom_pacs_simulator_scp import stop as pacs_simulator_scp_stop

# Configure the logging format
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.DEBUG,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def pytest_sessionstart(session):
    """Runs before the test session begins."""
    logger.info("Starting the test session")


@pytest.fixture
def temp_dir():
    # Create a temporary directory
    temp_path = tempfile.mkdtemp()
    logger.info(f"Creating temporary directory: {temp_path}")

    clear_lookups()

    # Yield the directory path to the test function
    yield temp_path

    # Remove the temporary directory after the test is done
    logger.info(f"Removing temporary directory: {temp_path}")
    shutil.rmtree(temp_path)
    local_storage_scp_stop()
    pacs_simulator_scp_stop()
