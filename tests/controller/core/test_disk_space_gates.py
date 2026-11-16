"""Unit tests for low-disk gates on C-STORE, import, and export."""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

from anonymizer.controller.dicom.requests import ExportPatientsRequest, ExportPatientsResponse
from anonymizer.controller.dicom.scp import ScpMixin
from anonymizer.controller.project import ProjectController
from anonymizer.utils.dicom import C_STORE_DECODE_ERROR, C_STORE_OUT_OF_RESOURCES


def test_handle_store_refuses_when_disk_abort() -> None:
    # Plain mock: check_storage_disk lives on ProjectController, not ScpMixin.
    scp = MagicMock()
    scp._handle_store_time_slice_interval = 0.0
    scp._memory_available_backoff_threshold = 0
    scp.check_storage_disk.return_value = "abort"

    with (
        patch("anonymizer.controller.dicom.scp.time.sleep"),
        patch("anonymizer.controller.dicom.scp.virtual_memory") as mock_vm,
    ):
        mock_vm.return_value.available = 1 << 40
        status = ScpMixin._handle_store(scp, MagicMock())

    assert status == C_STORE_OUT_OF_RESOURCES
    scp.anonymizer.anonymize_dataset_ex.assert_not_called()


def test_handle_store_disk_ok_reaches_decode() -> None:
    """When free space is ok, the handler proceeds past the disk gate."""
    scp = MagicMock()
    scp._handle_store_time_slice_interval = 0.0
    scp._memory_available_backoff_threshold = 0
    scp.check_storage_disk.return_value = "ok"
    event = MagicMock()
    event.assoc.remote = {"address": "1.2.3.4", "port": 11112, "ae_title": "REMOTE"}

    with (
        patch("anonymizer.controller.dicom.scp.time.sleep"),
        patch("anonymizer.controller.dicom.scp.virtual_memory") as mock_vm,
        patch("anonymizer.controller.dicom.scp.Dataset", side_effect=ValueError("bad ds")),
    ):
        mock_vm.return_value.available = 1 << 40
        status = ScpMixin._handle_store(scp, event)

    assert status == C_STORE_DECODE_ERROR


def test_import_paths_stops_on_disk_abort() -> None:
    controller = MagicMock(spec=ProjectController)
    controller.anonymizer = MagicMock()
    controller.anonymizer.anonymize_file.return_value = (None, MagicMock(PatientID="A1"))
    controller.check_storage_disk.side_effect = ["ok", "abort", "abort"]
    controller.storage_disk_abort_message.return_value = "disk full"

    result = ProjectController.import_paths(
        controller,
        [Path("a.dcm"), Path("b.dcm"), Path("c.dcm")],
    )

    assert result.succeeded == 1
    assert result.failed == 2
    assert result.failures[0]["error"] == "disk full"
    assert controller.anonymizer.anonymize_file.call_count == 1


def test_manage_export_refuses_when_disk_abort() -> None:
    controller = MagicMock(spec=ProjectController)
    controller.check_storage_disk.return_value = "abort"
    controller.storage_disk_abort_message.return_value = "disk full"
    controller._export_futures = None
    controller._patient_export_thread_pool_size = 1
    ux_q: Queue = Queue()
    req = ExportPatientsRequest(dest_name="PACS", patient_ids=["p1", "p2"], ux_Q=ux_q)

    ProjectController._manage_export(controller, req)

    assert controller._abort_export is True
    assert ux_q.qsize() == 2
    first = ux_q.get()
    assert isinstance(first, ExportPatientsResponse)
    assert first.error == "disk full"
    assert first.complete is True
