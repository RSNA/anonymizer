# tests/conftest.py
import os
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
from tests.controller.falcon_memory import collect_garbage, process_rss_mb


def pytest_sessionstart(session):
    """Runs before the test session begins."""
    # Initialise logging without file handler:
    init_logging(file_handler=False)


@pytest.fixture(autouse=True)
def falcon_memory(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Log RSS before/after and optionally fail when ``@pytest.mark.falcon_memory`` delta is too large."""
    marker = request.node.get_closest_marker("falcon_memory")
    if marker is None:
        yield
        return

    max_rss_delta_mb = float(marker.kwargs.get("max_rss_delta_mb", 400.0))
    collect_garbage()
    rss_before_mb = process_rss_mb()
    yield
    collect_garbage()
    rss_after_mb = process_rss_mb()
    rss_delta_mb = rss_after_mb - rss_before_mb

    request.node.user_properties.extend(
        (
            ("rss_before_mb", round(rss_before_mb, 1)),
            ("rss_after_mb", round(rss_after_mb, 1)),
            ("rss_delta_mb", round(rss_delta_mb, 1)),
        )
    )
    print(
        f"\n[{request.node.name}] RSS {rss_before_mb:.1f} -> {rss_after_mb:.1f} MB "
        f"({rss_delta_mb:+.1f} MB)"
    )
    if rss_delta_mb > max_rss_delta_mb:
        pytest.fail(
            f"RSS grew by {rss_delta_mb:.1f} MB, exceeding limit of {max_rss_delta_mb:.1f} MB"
        )


@pytest.fixture
def temp_dir() -> Generator[str, Any, None]:
    # Create a temporary directory
    temp_path = tempfile.mkdtemp(prefix="anonymizer_")

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
