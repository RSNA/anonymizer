"""Simulator tests: prefer C-GET when negotiated; fall back to C-MOVE."""

from __future__ import annotations

import os
import time

from pydicom.dataset import Dataset

import tests.controller.dicom.support.pacs_simulator_scp as pacs_simulator_scp
from anonymizer.controller.dicom.requests import MoveStudiesRequest
from anonymizer.controller.project import ProjectController
from anonymizer.utils.storage import count_studies_series_images
from tests.controller.dicom.support.helpers import send_file_to_scp
from tests.controller.dicom.support.test_files import (
    ct_small_SeriesInstanceUID,
    ct_small_StudyInstanceUID,
    ct_small_filename,
    patient3_id,
)
from tests.controller.dicom.support.test_nodes import LocalStorageSCP, PACSSimulatorSCP


def _wait_move_idle(controller: ProjectController, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while controller.bulk_move_active() and time.time() < deadline:
        time.sleep(0.2)
    assert not controller.bulk_move_active()


def test_manage_move_prefers_c_get_when_simulator_advertises_get(
    temp_dir: str, controller: ProjectController
) -> None:
    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    assert ds
    error_msg, study = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id
    )
    assert error_msg is None
    assert study.get_number_of_instances() == 1

    controller._qr_get_supported.clear()
    req = MoveStudiesRequest(
        scp_name=PACSSimulatorSCP.aet,
        dest_scp_ae=LocalStorageSCP.aet,
        level="STUDY",
        studies=[study],
    )
    controller.manage_move(req)
    assert controller._last_retrieve_modality == "GET"
    assert controller.get_number_of_pending_instances(study) == 0

    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert count_studies_series_images(os.path.join(store_dir, dirlist[0])) == (1, 1, 1)


def test_manage_move_falls_back_to_c_move_when_get_absent(temp_dir: str, controller: ProjectController) -> None:
    # Restart simulator without Study-Root Get
    pacs_simulator_scp.stop()
    assert pacs_simulator_scp.start(
        addr=PACSSimulatorSCP,
        storage_dir=os.path.join(temp_dir, PACSSimulatorSCP.aet),
        known_nodes=[LocalStorageSCP],
        enable_get=False,
    )

    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    assert ds
    error_msg, study = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id
    )
    assert error_msg is None

    controller._qr_get_supported.clear()
    req = MoveStudiesRequest(
        scp_name=PACSSimulatorSCP.aet,
        dest_scp_ae=LocalStorageSCP.aet,
        level="STUDY",
        studies=[study],
    )
    controller.manage_move(req)
    assert controller._last_retrieve_modality == "MOVE"
    assert controller.get_number_of_pending_instances(study) == 0


def test_force_move_skips_get_even_when_available(temp_dir: str, controller: ProjectController) -> None:
    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    assert ds
    error_msg, study = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id
    )
    assert error_msg is None

    controller._qr_get_supported.clear()
    req = MoveStudiesRequest(
        scp_name=PACSSimulatorSCP.aet,
        dest_scp_ae=LocalStorageSCP.aet,
        level="STUDY",
        studies=[study],
        force_move=True,
    )
    controller.manage_move(req)
    assert controller._last_retrieve_modality == "MOVE"
    assert study.series[ct_small_SeriesInstanceUID].instance_count == 1
    assert controller.get_number_of_pending_instances(study) == 0
