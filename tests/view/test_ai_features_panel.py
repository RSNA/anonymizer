"""Tests for AI Features panel download progress UI."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.tseg.runtime_status import (
    TsWeightKind,
    TsWeightState,
    TsWeightStatus,
    set_ai_session,
)
from anonymizer.utils.download_progress import (
    begin_download,
    end_download,
    update_download,
)
from anonymizer.view.settings.ai_features_panel import AiFeaturesPanel


def _make_panel(**kwargs) -> AiFeaturesPanel:
    root = tk.Tk()
    root.withdraw()
    session = kwargs.pop("session", None)
    if session is None:
        panel = AiFeaturesPanel(root, **kwargs)
        return panel

    set_ai_session(
        remove_pixel_phi=session.get("remove_pixel_phi", False),
        enable_harmonize=session.get("enable_harmonize", False),
        enable_face_blur=session.get("enable_face_blur", False),
    )
    with patch.object(AiFeaturesPanel, "sync_from_runtime", lambda self: None):
        panel = AiFeaturesPanel(root, **kwargs)
    for key, enabled in session.items():
        panel._feature_vars[key].set(1 if enabled else 0)
    return panel


def test_feature_download_in_progress_uses_progress_tracker() -> None:
    panel = _make_panel()
    try:
        begin_download("enable_harmonize", message="Downloading: 10.0MB/400.0MB")
        assert panel._feature_download_in_progress("enable_harmonize") is True
        assert panel._download_detail_message("enable_harmonize") == "Downloading: 10.0MB/400.0MB"
    finally:
        end_download("enable_harmonize")
        panel.destroy()


def test_refresh_status_shows_progress_instead_of_download_button() -> None:
    panel = _make_panel(session={"enable_harmonize": True})
    try:
        begin_download(
            "enable_harmonize",
            message="Downloading model for Task 298 ...",
        )
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_needs_download",
                return_value=True,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_status_harmonize",
                return_value="Downloading…",
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_summary_harmonize",
                return_value="Summary",
            ),
        ):
            panel._refresh_status()

        actions = panel._action_frames["enable_harmonize"]
        children = actions.winfo_children()
        assert len(children) == 2
        assert "CTkProgressBar" in children[0].__class__.__name__
        assert panel._progress_bars["enable_harmonize"] is children[0]
        assert panel._progress_details["enable_harmonize"].cget("text") == ("Downloading model for Task 298 ...")
    finally:
        end_download("enable_harmonize")
        panel.destroy()


def test_apply_download_progress_switches_to_determinate() -> None:
    panel = _make_panel(session={"enable_harmonize": True})
    try:
        begin_download("enable_harmonize", message="Downloading: 50%")
        update_download("enable_harmonize", fraction=0.5)
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_needs_download",
                return_value=True,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_status_harmonize",
                return_value="Downloading…",
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_summary_harmonize",
                return_value="Summary",
            ),
        ):
            panel._refresh_status()

        progress_bar = panel._progress_bars["enable_harmonize"]
        panel._apply_download_progress("enable_harmonize")
        assert progress_bar.cget("mode") == "determinate"
        assert progress_bar.get() == pytest.approx(0.5)
    finally:
        end_download("enable_harmonize")
        panel.destroy()


def test_pending_ts_download_shows_progress_before_runtime_status() -> None:
    panel = _make_panel(session={"enable_face_blur": True})
    try:
        panel._pending_ts_download = TsWeightKind.FACE
        panel._download_thread = MagicMock(is_alive=MagicMock(return_value=True))
        assert panel._feature_download_in_progress("enable_face_blur") is True
    finally:
        panel.destroy()


def test_refresh_status_uses_runtime_weight_detail_when_no_tracker() -> None:
    panel = _make_panel(session={"enable_face_blur": True})
    try:
        runtime = MagicMock()
        runtime.face_weights = TsWeightState(
            kind=TsWeightKind.FACE,
            status=TsWeightStatus.DOWNLOADING,
            task_id=303,
            model_folder=None,
            detail="Downloading model for Task 303 ...",
        )
        panel._pending_ts_download = TsWeightKind.FACE
        panel._download_thread = MagicMock(is_alive=MagicMock(return_value=True))
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.get_runtime_status",
                return_value=runtime,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.face_blur_needs_download",
                return_value=False,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_status_face_blur",
                return_value="Face models downloading",
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_summary_face_blur",
                return_value="Summary",
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.face_blur_needs_license",
                return_value=False,
            ),
        ):
            panel._refresh_status()

        children = panel._action_frames["enable_face_blur"].winfo_children()
        assert "CTkProgressBar" in children[0].__class__.__name__
        assert panel._progress_details["enable_face_blur"].cget("text") == ("Downloading model for Task 303 ...")
    finally:
        panel.destroy()


def test_drain_worker_queue_refreshes_ready_status_after_download() -> None:
    panel = _make_panel(session={"enable_harmonize": True})
    try:
        if panel._poll_after_id is not None:
            panel.after_cancel(panel._poll_after_id)
            panel._poll_after_id = None
        status_messages = [
            "Anatomy segmentation models are not installed yet. Click Download models below to set up this tool.",
            "Anatomy models are installed. Harmonize from the study index (batch) or from Series View (single series).",
        ]
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_needs_download",
                side_effect=[True, False],
            ),
            patch.dict(
                "anonymizer.view.settings.ai_features_panel._FEATURE_STATUS",
                {"enable_harmonize": MagicMock(side_effect=status_messages)},
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_summary_harmonize",
                return_value="Summary",
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.refresh_weight_status",
            ) as refresh_status,
        ):
            panel._refresh_status()
            assert len(panel._action_frames["enable_harmonize"].winfo_children()) == 1

            panel._worker_queue.put(("download_done", TsWeightKind.ANATOMY))
            panel._drain_worker_queue()

            refresh_status.assert_called_once_with(TsWeightKind.ANATOMY)
            assert not panel._action_frames["enable_harmonize"].winfo_children()
            assert "installed" in panel._status_labels["enable_harmonize"].cget("text").lower()
    finally:
        panel.destroy()


def test_update_download_progress_refreshes_when_progress_stale() -> None:
    panel = _make_panel(session={"enable_harmonize": True})
    try:
        begin_download("enable_harmonize", message="Downloading…")
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_needs_download",
                return_value=True,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_status_harmonize",
                return_value="Downloading…",
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_summary_harmonize",
                return_value="Summary",
            ),
        ):
            panel._refresh_status()
            assert "enable_harmonize" in panel._progress_bars

        end_download("enable_harmonize")
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_needs_download",
                return_value=False,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_status_harmonize",
                return_value="Anatomy models are installed.",
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_summary_harmonize",
                return_value="Summary",
            ),
            patch.object(panel, "_refresh_status", wraps=panel._refresh_status) as refresh,
        ):
            panel._update_download_progress()
            refresh.assert_called_once()
            assert "enable_harmonize" not in panel._progress_bars
    finally:
        end_download("enable_harmonize")
        panel.destroy()


def test_uncheck_remove_pixel_phi_removes_models() -> None:
    panel = _make_panel(session={"remove_pixel_phi": True})
    try:
        panel._feature_vars["remove_pixel_phi"].set(0)
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.messagebox.askyesno",
                return_value=True,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.remove_pixel_phi_has_models",
                return_value=True,
            ),
            patch("anonymizer.view.settings.ai_features_panel.remove_ocr_models") as remove_models,
        ):
            panel._on_toggle_changed()
            remove_models.assert_called_once()
        assert panel._feature_vars["remove_pixel_phi"].get() == 0
    finally:
        panel.destroy()


def test_uncheck_remove_pixel_phi_cancelled_keeps_feature_enabled() -> None:
    panel = _make_panel(session={"remove_pixel_phi": True})
    try:
        panel._feature_vars["remove_pixel_phi"].set(0)
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.messagebox.askyesno",
                return_value=False,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.remove_pixel_phi_has_models",
                return_value=True,
            ),
            patch("anonymizer.view.settings.ai_features_panel.remove_ocr_models") as remove_models,
        ):
            panel._on_toggle_changed()
            remove_models.assert_not_called()
        assert panel._feature_vars["remove_pixel_phi"].get() == 1
    finally:
        panel.destroy()


def test_uncheck_harmonize_removes_anatomy_model() -> None:
    panel = _make_panel(session={"enable_harmonize": True})
    try:
        panel._feature_vars["enable_harmonize"].set(0)
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.messagebox.askyesno",
                return_value=True,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_has_models",
                return_value=True,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.remove_segmentation_model",
            ) as remove_model,
        ):
            panel._on_toggle_changed()
            remove_model.assert_called_once_with(TsWeightKind.ANATOMY)
    finally:
        panel.destroy()


def test_uncheck_harmonize_without_models_skips_confirmation() -> None:
    panel = _make_panel(session={"enable_harmonize": True})
    try:
        panel._feature_vars["enable_harmonize"].set(0)
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.messagebox.askyesno",
            ) as confirm,
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_has_models",
                return_value=False,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.remove_segmentation_model",
            ) as remove_model,
        ):
            panel._on_toggle_changed()
            confirm.assert_not_called()
            remove_model.assert_not_called()
        assert panel._feature_vars["enable_harmonize"].get() == 0
    finally:
        panel.destroy()


def test_sync_from_runtime_preserves_enabled_without_models() -> None:
    set_ai_session(enable_harmonize=True)
    root = tk.Tk()
    root.withdraw()
    with patch.object(AiFeaturesPanel, "sync_from_runtime", lambda self: None):
        panel = AiFeaturesPanel(root)
    try:
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.get_runtime_status",
            ) as refresh_status,
            patch.object(panel, "_refresh_status") as refresh_ui,
        ):
            AiFeaturesPanel.sync_from_runtime(panel)
            refresh_status.assert_any_call(force_refresh=True)
            refresh_ui.assert_called_once()
        assert panel._feature_vars["enable_harmonize"].get() == 1
    finally:
        panel.destroy()
        set_ai_session(enable_harmonize=False)


def test_refresh_status_shows_summary_and_status_separately() -> None:
    panel = _make_panel(session={"enable_harmonize": True})
    try:
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_needs_download",
                return_value=True,
            ),
            patch.dict(
                "anonymizer.view.settings.ai_features_panel._FEATURE_SUMMARIES",
                {"enable_harmonize": lambda: "Functional summary"},
            ),
            patch.dict(
                "anonymizer.view.settings.ai_features_panel._FEATURE_STATUS",
                {"enable_harmonize": lambda: "Status line"},
            ),
        ):
            panel._refresh_status()

        assert panel._summary_labels["enable_harmonize"].cget("text") == "Functional summary"
        assert panel._status_labels["enable_harmonize"].cget("text") == "Status line"
        assert len(panel._action_frames["enable_harmonize"].winfo_children()) == 1
    finally:
        panel.destroy()


def test_sync_from_runtime_shows_installed_status_without_download_button() -> None:
    panel = _make_panel(session={"enable_harmonize": True, "enable_face_blur": True})
    try:
        installed_harmonize = (
            "Anatomy models are installed. Harmonize from the study index (batch) or from Series View (single series)."
        )
        installed_face = "Face segmentation models are installed. De-identify faces from Series View on head CT."
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_needs_download",
                return_value=False,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.face_blur_needs_download",
                return_value=False,
            ),
            patch.dict(
                "anonymizer.view.settings.ai_features_panel._FEATURE_STATUS",
                {
                    "enable_harmonize": lambda: installed_harmonize,
                    "enable_face_blur": lambda: installed_face,
                },
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.face_blur_needs_license",
                return_value=False,
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_summary_harmonize",
                return_value="Harmonize summary",
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_summary_face_blur",
                return_value="Face summary",
            ),
        ):
            panel.sync_from_runtime()

        assert "installed" in panel._status_labels["enable_harmonize"].cget("text").lower()
        assert not panel._action_frames["enable_harmonize"].winfo_children()
        assert "installed" in panel._status_labels["enable_face_blur"].cget("text").lower()
        assert not panel._action_frames["enable_face_blur"].winfo_children()
    finally:
        panel.destroy()


def test_panel_init_with_ready_weights_hides_download_button() -> None:
    root = __import__("tkinter").Tk()
    root.withdraw()
    set_ai_session(enable_harmonize=True)
    installed = "Anatomy models are installed."
    try:
        with patch.object(AiFeaturesPanel, "sync_from_runtime", lambda self: None):
            panel = AiFeaturesPanel(root)
        panel._feature_vars["enable_harmonize"].set(1)
        with (
            patch(
                "anonymizer.view.settings.ai_features_panel.harmonize_needs_download",
                return_value=False,
            ),
            patch.dict(
                "anonymizer.view.settings.ai_features_panel._FEATURE_STATUS",
                {"enable_harmonize": lambda: installed},
            ),
            patch(
                "anonymizer.view.settings.ai_features_panel.ai_feature_summary_harmonize",
                return_value="Summary",
            ),
        ):
            panel._refresh_status()

        assert panel._status_labels["enable_harmonize"].cget("text") == installed
        assert not panel._action_frames["enable_harmonize"].winfo_children()
    finally:
        set_ai_session(enable_harmonize=False)
        panel.destroy()
        root.destroy()
