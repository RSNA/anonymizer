"""Unit tests for low-disk gates on C-STORE, import, and export."""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

from anonymizer.controller.dicom.requests import ExportPatientsRequest, ExportPatientsResponse
from anonymizer.controller.dicom.scp import ScpMixin
from anonymizer.controller.project import ProjectController
from anonymizer.utils.dicom import C_STORE_DECODE_ERROR, C_STORE_OUT_OF_RESOURCES
from anonymizer.utils.disk import DiskGuard


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


def test_check_storage_disk_via_disk_guard() -> None:
    controller = MagicMock(spec=ProjectController)
    controller.model = MagicMock()
    controller.model.storage_dir = Path("/tmp/storage")
    controller._disk_guard = DiskGuard(warn_free_bytes=1000, abort_free_bytes=100, ttl_seconds=0.0)
    with patch("anonymizer.utils.disk.free_bytes", return_value=50):
        assert ProjectController.check_storage_disk(controller) == "abort"
        msg = ProjectController.storage_disk_abort_message(controller)
    assert "critically low" in msg.lower() or "Storage disk" in msg
    assert "/tmp/storage" in msg


def test_check_storage_disk_warn_band() -> None:
    controller = MagicMock(spec=ProjectController)
    controller.model = MagicMock()
    controller.model.storage_dir = Path("/tmp/storage")
    controller._disk_guard = DiskGuard(warn_free_bytes=1000, abort_free_bytes=100, ttl_seconds=0.0)
    with patch("anonymizer.utils.disk.free_bytes", return_value=500):
        assert ProjectController.check_storage_disk(controller) == "warn"


def test_export_patient_refuses_when_disk_abort() -> None:
    controller = MagicMock(spec=ProjectController)
    controller.check_storage_disk.return_value = "abort"
    controller.storage_disk_abort_message.return_value = "disk full"
    controller._abort_export = False
    ux_q: Queue = Queue()

    ProjectController._export_patient(controller, "PACS", "p1", ux_q)

    assert controller._abort_export is True
    resp = ux_q.get()
    assert isinstance(resp, ExportPatientsResponse)
    assert resp.patient_id == "p1"
    assert resp.files_sent == 0
    assert resp.error == "disk full"
    assert resp.complete is True


def test_import_paths_aborts_on_first_file() -> None:
    controller = MagicMock(spec=ProjectController)
    controller.anonymizer = MagicMock()
    controller.check_storage_disk.return_value = "abort"
    controller.storage_disk_abort_message.return_value = "disk full"

    result = ProjectController.import_paths(
        controller,
        [Path("a.dcm"), Path("b.dcm")],
    )

    assert result.succeeded == 0
    assert result.failed == 2
    assert result.failures[0]["error"] == "disk full"
    controller.anonymizer.anonymize_file.assert_not_called()


def test_import_paths_failure_detail_cap() -> None:
    controller = MagicMock(spec=ProjectController)
    controller.anonymizer = MagicMock()
    controller.check_storage_disk.return_value = "abort"
    controller.storage_disk_abort_message.return_value = "disk full"
    paths = [Path(f"{i}.dcm") for i in range(5)]

    result = ProjectController.import_paths(controller, paths, max_failure_details=2)

    assert result.failed == 5
    assert len(result.failures) == 2


def test_import_paths_warn_does_not_block() -> None:
    controller = MagicMock(spec=ProjectController)
    controller.anonymizer = MagicMock()
    controller.check_storage_disk.return_value = "warn"
    ds = MagicMock(PatientID="A1")
    controller.anonymizer.anonymize_file.return_value = (None, ds)

    result = ProjectController.import_paths(controller, [Path("a.dcm")])

    assert result.succeeded == 1
    assert result.failed == 0
    controller.anonymizer.anonymize_file.assert_called_once()
