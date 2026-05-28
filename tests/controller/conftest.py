# tests/conftest.py
import sys
import os
import gc
import psutil
import shutil
import tempfile

# Add the src directory to sys.path dynamically
#  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

import tests.controller.dicom_pacs_simulator_scp as pacs_simulator_scp
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import NetworkTimeouts, ProjectModel
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

def pytest_sessionstart(session):
    """Runs before the test session begins."""
    # Initialise logging without file handler:
    init_logging(file_handler=False)


@pytest.fixture
def temp_dir() -> Generator[str, Any, None]:
    # Create a temporary directory
    temp_path = tempfile.mkdtemp(prefix="anonymizer_")

    # Yield the directory path to the test function
    yield temp_path

    # Remove the temporary directory after the test is done
    shutil.rmtree(temp_path)

@pytest.fixture
def assert_no_memory_leak():
    """
    Measures the OS-level memory of the current test process.
    Skips the strict assertion if running inside a debugger (like VSCode).
    """
    process = psutil.Process(os.getpid())
    mem_before = process.memory_info().rss
    
    yield 
    
    gc.collect()
    mem_after = process.memory_info().rss
    growth_mb = (mem_after - mem_before) / (1024 * 1024)
    
    # Check if a debugger trace function is active
    is_debugging = sys.gettrace() is not None

    if is_debugging:
        # Just print/log the growth, don't fail the test
        print(f"\n[Debugger Active] Memory growth bypassed: {growth_mb:.2f} MB")
    else:
        # Enforce the strict threshold during normal CLI or CI runs
        assert growth_mb < 5.0, f"Memory leak detected! RAM grew by {growth_mb:.2f} MB"

@pytest.fixture
def controller(temp_dir: str) -> Generator[ProjectController, Any, None]:
    anon_store = Path(temp_dir, LocalSCU.aet)
    # Make sure storage directory exists:
    os.makedirs(anon_store, exist_ok=True)

    # Create Test ProjectModel:
    project_model: ProjectModel = ProjectModel(
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
