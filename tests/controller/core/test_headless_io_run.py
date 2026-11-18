"""Unit tests for headless import/export runners (mocked controller)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from anonymizer.controller import headless_io
from anonymizer.mcp.ops import HeadlessOpsError


def _mock_controller(tmp_path: Path) -> MagicMock:
    controller = MagicMock()
    controller.model.images_dir.return_value = tmp_path / "images"
    controller.model.project_name = "TestProject"
    controller.model.site_id = "AB12"
    controller.model.storage_dir = tmp_path / "storage"
    controller.anonymizer.model = MagicMock()
    return controller


def test_export_midi_mappings_writes_manifest(tmp_path: Path) -> None:
    controller = _mock_controller(tmp_path)
    out = tmp_path / "midi"
    with (
        patch.object(headless_io, "write_uid_mapping", return_value=3) as uid,
        patch.object(headless_io, "write_patid_mapping", return_value=2) as pat,
    ):
        manifest = headless_io.export_midi_mappings(controller, out)
    uid.assert_called_once()
    pat.assert_called_once()
    assert manifest["uid_mapping_rows"] == 3
    assert manifest["patid_mapping_rows"] == 2
    assert manifest["project_name"] == "TestProject"
    assert (out / "manifest.json").is_file()


def test_run_headless_import_controller_none(tmp_path: Path) -> None:
    with patch.object(headless_io, "create_headless_controller", return_value=None):
        assert headless_io.run_headless_import(tmp_path / "p.json", tmp_path) == 1


def test_run_headless_import_success_shuts_down(tmp_path: Path) -> None:
    controller = _mock_controller(tmp_path)
    with (
        patch.object(headless_io, "create_headless_controller", return_value=controller),
        patch.object(
            headless_io,
            "import_directory",
            return_value={"source": "x", "files_seen": 1, "succeeded": 1, "skipped": 0, "failed": 0},
        ),
    ):
        code = headless_io.run_headless_import(tmp_path / "p.json", tmp_path / "import")
    assert code == 0
    controller.apply_confidentiality_options.assert_called_once()
    controller.shutdown.assert_called_once()
    controller.save_model.assert_called_once()
    controller.anonymizer.stop.assert_called_once()


def test_run_headless_import_ops_error_still_finally(tmp_path: Path) -> None:
    controller = _mock_controller(tmp_path)
    with (
        patch.object(headless_io, "create_headless_controller", return_value=controller),
        patch.object(headless_io, "import_directory", side_effect=HeadlessOpsError("nope")),
    ):
        code = headless_io.run_headless_import(tmp_path / "p.json", tmp_path / "import")
    assert code == 1
    controller.shutdown.assert_called_once()
    controller.save_model.assert_called_once()
    controller.anonymizer.stop.assert_called_once()


def test_run_headless_export_mappings_success_and_fail(tmp_path: Path) -> None:
    controller = _mock_controller(tmp_path)
    with (
        patch.object(headless_io, "create_headless_controller", return_value=controller),
        patch.object(headless_io, "export_midi_mappings", return_value={}) as export,
    ):
        assert headless_io.run_headless_export_mappings(tmp_path / "p.json", tmp_path / "out") == 0
    export.assert_called_once()
    controller.shutdown.assert_called_once()
    controller.anonymizer.stop.assert_called_once()

    with patch.object(headless_io, "create_headless_controller", return_value=None):
        assert headless_io.run_headless_export_mappings(tmp_path / "p.json", tmp_path / "out") == 1
