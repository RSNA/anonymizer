"""Tests that preview dialogs use WorkState + JobPoller patterns."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.controller.ai.harmonize import HarmonizeProgress
from anonymizer.controller.runner import Algorithm
from anonymizer.controller.work_state import WorkState
from anonymizer.view.face_blur_review_dialog import FaceBlurReviewDialog
from anonymizer.view.harmonize_results import HarmonizeResultsView


def test_harmonize_job_tick_updates_progress_from_work_state() -> None:
    view = HarmonizeResultsView.__new__(HarmonizeResultsView)
    view._closing = False
    view.winfo_exists = lambda: True
    view._batch_overall_fraction = lambda fraction: fraction
    view._status_label = MagicMock()
    view._progressbar = MagicMock()
    view._update_playbook_from_progress = MagicMock()

    work_state = WorkState()
    progress = HarmonizeProgress(stage="geometry", message="geo", fraction=0.25, elapsed_sec=0.1)
    work_state.update_job_progress(status="Analyzing", fraction=0.25, detail=progress)

    HarmonizeResultsView._on_harmonize_job_tick(view, work_state)

    view._status_label.configure.assert_called_once()
    assert "25%" in view._status_label.configure.call_args.kwargs["text"]
    view._progressbar.set.assert_called_once_with(0.25)
    view._update_playbook_from_progress.assert_called_once_with(progress)


@patch("anonymizer.view.face_blur_review_dialog.start_background_job")
def test_face_blur_dialog_starts_load_job_with_work_state(mock_start: MagicMock) -> None:
    import customtkinter as ctk

    parent = MagicMock()
    parent.winfo_rootx.return_value = 0
    parent.winfo_rooty.return_value = 0

    with (
        patch.object(ctk.CTkToplevel, "__init__", return_value=None),
        patch.object(FaceBlurReviewDialog, "_show_loading_shell"),
        patch.object(FaceBlurReviewDialog, "wait_visibility"),
        patch.object(FaceBlurReviewDialog, "grab_set"),
        patch.object(FaceBlurReviewDialog, "deiconify"),
        patch.object(FaceBlurReviewDialog, "lift"),
        patch.object(FaceBlurReviewDialog, "withdraw"),
        patch.object(FaceBlurReviewDialog, "protocol"),
        patch.object(FaceBlurReviewDialog, "bind"),
        patch.object(FaceBlurReviewDialog, "title"),
        patch.object(FaceBlurReviewDialog, "geometry"),
        patch.object(FaceBlurReviewDialog, "resizable"),
        patch("anonymizer.view.face_blur_review_dialog.mark_ctk_window_alive"),
    ):
        dialog = FaceBlurReviewDialog(
            parent,
            anon_model=MagicMock(),
            series_path=MagicMock(),
            blur_mode=MagicMock(),
        )

    mock_start.assert_called_once()
    call_kwargs = mock_start.call_args.kwargs
    assert call_kwargs["algorithm"] is Algorithm.FACE_BLUR
    assert call_kwargs["work_state"] is dialog._load_work_state
