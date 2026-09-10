"""Dataset View refreshes after file/folder import completes (no polling)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.anonymizer import Anonymizer


def _stub_anonymizer(*, dataset_view=None) -> Anonymizer:
    app = Anonymizer.__new__(Anonymizer)
    app.dataset_view = dataset_view
    app.controller = MagicMock()
    app.controller.anonymizer = MagicMock()
    app.dashboard = MagicMock()
    return app


def test_refresh_dataset_view_if_open_updates_tree() -> None:
    view = MagicMock()
    view.winfo_exists.return_value = True
    app = _stub_anonymizer(dataset_view=view)

    app._refresh_dataset_view_if_open()

    view._update_tree_from_phi_index.assert_called_once_with()


def test_refresh_dataset_view_if_open_noop_when_closed() -> None:
    app = _stub_anonymizer(dataset_view=None)
    app._refresh_dataset_view_if_open()  # must not raise

    view = MagicMock()
    view.winfo_exists.return_value = False
    app.dataset_view = view
    app._refresh_dataset_view_if_open()
    view._update_tree_from_phi_index.assert_not_called()


def test_run_import_files_dialog_refreshes_dataset_view() -> None:
    view = MagicMock()
    view.winfo_exists.return_value = True
    app = _stub_anonymizer(dataset_view=view)
    dlg = MagicMock()
    dlg.get_input.return_value = 3

    with patch("anonymizer.anonymizer.ImportFilesDialog", return_value=dlg) as dialog_cls:
        app._run_import_files_dialog(["a.dcm", "b.dcm"])

    dialog_cls.assert_called_once()
    dlg.get_input.assert_called_once_with()
    view._update_tree_from_phi_index.assert_called_once_with()


def test_import_directory_path_refreshes_after_dialog() -> None:
    view = MagicMock()
    view.winfo_exists.return_value = True
    app = _stub_anonymizer(dataset_view=view)
    dlg = MagicMock()
    dlg.get_input.return_value = 2

    with (
        patch.object(app, "_collect_files_from_directory", return_value=["a.dcm", "b.dcm"]),
        patch("anonymizer.anonymizer.messagebox.askyesno", return_value=True),
        patch("anonymizer.anonymizer.ImportFilesDialog", return_value=dlg),
    ):
        app._import_directory_path("/tmp/study")

    dlg.get_input.assert_called_once_with()
    view._update_tree_from_phi_index.assert_called_once_with()
    app.dashboard.set_status.assert_called()
