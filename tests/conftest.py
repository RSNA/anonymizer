# tests/conftest.py
import os
from pathlib import Path
import shutil
import tempfile
import pytest
import logging

from model.project import ProjectModel
from controller.project import ProjectController
import tests.controller.dicom_pacs_simulator_scp as pacs_simulator_scp
from tests.controller.dicom_test_nodes import (
    TEST_PROJECTNAME,
    TEST_SITEID,
    TEST_TRIALNAME,
    TEST_UIDROOT,
    LocalSCU,
    LocalStorageSCP,
    PACSSimulatorSCP,
    RemoteSCPDict,
)

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

    # Yield the directory path to the test function
    yield temp_path

    # Remove the temporary directory after the test is done
    logger.info(f"Removing temporary directory: {temp_path}")
    shutil.rmtree(temp_path)


@pytest.fixture
def controller(temp_dir):
    anon_store = Path(temp_dir, LocalSCU.aet)
    # Make sure storage directory exists:
    os.makedirs(anon_store, exist_ok=True)
    # Create Test ProjectModel:
    project_model = ProjectModel(
        siteid=TEST_SITEID,
        projectname=TEST_PROJECTNAME,
        trialname=TEST_TRIALNAME,
        uidroot=TEST_UIDROOT,
        storage_dir=anon_store,
        scu=LocalSCU,
        scp=LocalStorageSCP,
        remote_scps=RemoteSCPDict,
        network_timeout=3,
    )

    project_controller = ProjectController(project_model)

    assert project_controller

    # Start PACS Simulator:
    assert pacs_simulator_scp.start(
        PACSSimulatorSCP,
        os.path.join(temp_dir, PACSSimulatorSCP.aet),
        [LocalStorageSCP],  # one move destination
    )
    assert pacs_simulator_scp.server_running()

    yield project_controller

    # Ensure Local Storage is stopped
    # (cleanup of project_controller doesn't happen fast enough)
    project_controller.stop_scp()

    # Stop PACS Simulator:
    pacs_simulator_scp.stop()
