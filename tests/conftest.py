# tests/conftest.py
import os
import shutil
import tempfile
from logging import INFO, WARNING

# Add the src directory to sys.path dynamically
#  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from pathlib import Path
from typing import Any, Generator

import pytest

import tests.controller.dicom_pacs_simulator_scp as pacs_simulator_scp
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import LoggingLevels, NetworkTimeouts, ProjectModel
from anonymizer.utils.logging import init_logging
from tests.controller.dicom_test_nodes import (
    TEST_PROJECTNAME,
    TEST_SITEID,
    TEST_UIDROOT,
    LocalSCU,
    LocalStorageSCP,
    PACSSimulatorSCP,
    RemoteSCPDict,
)

# def pytest_sessionstart(session):
#     """Runs before the test session begins."""


@pytest.fixture
def temp_dir() -> Generator[str, Any, None]:
    # Create a temporary directory
    temp_path = tempfile.mkdtemp(prefix="anonymizer_")

    # Initialise logging without file handler:
    init_logging(file_handler=False)

    # Yield the directory path to the test function
    yield temp_path

    # Remove the temporary directory after the test is done
    shutil.rmtree(temp_path)


@pytest.fixture
def controller(temp_dir: str) -> Generator[ProjectController, Any, None]:
    anon_store = Path(temp_dir, LocalSCU.aet)
    # Make sure storage directory exists:
    os.makedirs(anon_store, exist_ok=True)

    # Create Test ProjectModel:
    project_model = ProjectModel(
        site_id=TEST_SITEID,
        project_name=TEST_PROJECTNAME,
        uid_root=TEST_UIDROOT,
        remove_pixel_phi=False,
        storage_dir=anon_store,
        scu=LocalSCU,
        scp=LocalStorageSCP,
        remote_scps=RemoteSCPDict,
        network_timeouts=NetworkTimeouts(2, 5, 5, 15),
        anonymizer_script_path=Path("src/anonymizer/assets/scripts/default-anonymizer.script"),
        logging_levels=LoggingLevels(anonymizer=INFO, pynetdicom=WARNING, pydicom=False),
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
