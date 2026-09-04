"""Tests that preview dialogs use WorkState + JobPoller patterns."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.controller.ai.blur_face import FaceBlurMode
from anonymizer.controller.ai.harmonize import HarmonizeProgress
from anonymizer.controller.runner import Algorithm
from anonymizer.controller.work_state import WorkState
from anonymizer.view.ai.face_blur_review_dialog import FaceBlurReviewDialog
from anonymizer.view.ai.harmonize_results import HarmonizeResultsView


def test_harmonize_job_tick_updates_progress_from_work_state() -> None:
    view = HarmonizeResultsView.__new__(HarmonizeResultsView)
    view._closing = False
    view.cancelled = False
    view._ds = MagicMock(Modality="CT")
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


@patch("anonymizer.view.ai.face_blur_review_dialog.start_background_job")
def test_face_blur_dialog_starts_load_job_with_work_state(mock_start: MagicMock) -> None:
    from anonymizer.view.common.app_window import AppCTkToplevel

    parent = MagicMock()
    parent.winfo_rootx.return_value = 0
    parent.winfo_rooty.return_value = 0

    with (
        patch.object(AppCTkToplevel, "__init__", return_value=None),
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
    ):
        dialog = FaceBlurReviewDialog(
            parent,
            anon_model=MagicMock(),
            series_path=MagicMock(),
            blur_mode=FaceBlurMode.GAUSSIAN,
        )

    mock_start.assert_called_once()
    call_kwargs = mock_start.call_args.kwargs
    assert call_kwargs["algorithm"] is Algorithm.FACE_BLUR
    assert call_kwargs["work_state"] is dialog._load_work_state


def test_apply_fixed_viewer_sizing_marks_startup_complete() -> None:
    """Blur Face review must enable slice scrolling after its fixed layout pass."""
    dialog = FaceBlurReviewDialog.__new__(FaceBlurReviewDialog)
    viewer = MagicMock()
    dialog.image_viewer = viewer
    dialog.update_idletasks = MagicMock()

    FaceBlurReviewDialog._apply_fixed_viewer_sizing(dialog)

    viewer.fit_to_viewport.assert_called_once_with(force=True, fill_viewport=True)
    viewer.mark_startup_complete.assert_called_once()


def test_face_blur_cancel_while_blur_running_waits_for_step() -> None:
    """Cancel during preview shows status and closes only after the worker finishes."""
    dialog = FaceBlurReviewDialog.__new__(FaceBlurReviewDialog)
    dialog._closing = False
    dialog._destroyed = False
    dialog._loading = False
    dialog._blur_running = True
    dialog._cancel_after_step = False
    dialog._load_work_state = WorkState()
    dialog._blur_work_state = WorkState()
    dialog._blur_work_state.prepare_job()
    dialog._status_label = MagicMock()
    dialog._cancel_button = MagicMock()
    dialog._loading_status_label = None
    dialog._close = MagicMock()
    dialog.winfo_exists = lambda: True

    FaceBlurReviewDialog._on_cancel(dialog)

    assert dialog._cancel_after_step is True
    assert dialog._blur_work_state.should_cancel()
    dialog._status_label.configure.assert_called()
    assert "Cancelling after current step" in dialog._status_label.configure.call_args.kwargs["text"]
    dialog._close.assert_not_called()

    FaceBlurReviewDialog._on_blur_job_done(dialog, None, dialog._blur_work_state)
    dialog._close.assert_called_once_with(cancelled=True)
