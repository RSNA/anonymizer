# tests/conftest.py

import shutil
import tempfile
import pytest
import logging

# Configure the logging format
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.DEBUG,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def temp_dir():
    # Create a temporary directory
    temp_path = tempfile.mkdtemp()
    logger.info(f"Creating temporary directory: {temp_path}")

    # Yield the directory path to the test function
    yield temp_path

    # Remove the temporary directory after the test is done
    logger.info(f"Removing temporary directory: {temp_path}")
    shutil.rmtree(temp_path)
