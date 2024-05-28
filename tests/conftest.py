# tests/conftest.py
import os
from pathlib import Path
import shutil
import tempfile
import pytest

from logging import DEBUG, INFO, WARNING
from utils.logging import init_logging
from model.project import ProjectModel, NetworkTimeouts, LoggingLevels
from controller.project import ProjectController
import tests.controller.dicom_pacs_simulator_scp as pacs_simulator_scp
from tests.controller.dicom_test_nodes import (
    TEST_PROJECTNAME,
    TEST_SITEID,
    TEST_UIDROOT,
    LocalSCU,
    LocalStorageSCP,
    PACSSimulatorSCP,
    RemoteSCPDict,
)


def pytest_sessionstart(session):
    """Runs before the test session begins."""


@pytest.fixture
def temp_dir():
    # Create a temporary directory
    temp_path = tempfile.mkdtemp()

    # Initialise logging without file handler:
    init_logging(temp_path, False)

    # Yield the directory path to the test function
    yield temp_path

    # Remove the temporary directory after the test is done
    shutil.rmtree(temp_path)


@pytest.fixture
def controller(temp_dir):
    anon_store = Path(temp_dir, LocalSCU.aet)
    # Make sure storage directory exists:
    os.makedirs(anon_store, exist_ok=True)
    # Create Test ProjectModel:
    project_model = ProjectModel(
        site_id=TEST_SITEID,
        project_name=TEST_PROJECTNAME,
        uid_root=TEST_UIDROOT,
        storage_dir=anon_store,
        scu=LocalSCU,
        scp=LocalStorageSCP,
        remote_scps=RemoteSCPDict,
        network_timeouts=NetworkTimeouts(2, 5, 5, 15),
        logging_levels=LoggingLevels(anonymizer=DEBUG, pynetdicom=INFO, pydicom=False),
    )

    project_controller = ProjectController(project_model)

    assert project_controller

    project_controller.start_scp()

    # Start PACS Simulator:
    assert pacs_simulator_scp.start(
        addr=PACSSimulatorSCP,
        storage_dir=os.path.join(temp_dir, PACSSimulatorSCP.aet),
        known_nodes=[LocalStorageSCP],  # one move destination
    )
    assert pacs_simulator_scp.server_running()

    yield project_controller

    # Ensure Local Storage is stopped
    project_controller.stop_scp()
    project_controller.anonymizer.stop()

    # Stop PACS Simulator:
    pacs_simulator_scp.stop()
