"""Tests for FaceBlurReviewDialog."""

from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from anonymizer.controller.blur_face import FaceBlurMode
from anonymizer.view.face_blur_review_dialog import (
    FaceBlurReviewDialog,
    FaceBlurReviewOutcome,
    show_face_blur_review_dialog,
)
from anonymizer.view.image import ImageViewer


@pytest.fixture
def sample_frames() -> np.ndarray:
    return np.arange(3 * 4 * 5, dtype=np.uint16).reshape(3, 4, 5)


def test_show_blur_review_attaches_companion_stack(sample_frames: np.ndarray) -> None:
    preview = SimpleNamespace(
        mask=np.zeros((3, 4, 5), dtype=np.uint8),
        blurred_slice_frames=sample_frames.astype(np.float32),
        qa_stats=SimpleNamespace(outside_clean=True, n_face_voxels=10, n_outside_voxels=0, n_violating_voxels=0),
        sigma_mm=1.0,
        slice_count=3,
        blur_mode=FaceBlurMode.GAUSSIAN,
        error=None,
        hu_after=None,
        slice_paths=(),
    )
    dialog = FaceBlurReviewDialog.__new__(FaceBlurReviewDialog)
    dialog._slice_frames = sample_frames
    dialog._ds = MagicMock()
    dialog._preview = None
    dialog._status_label = MagicMock()
    dialog._progressbar = MagicMock()
    dialog._save_button = MagicMock()
    dialog._apply_fixed_viewer_sizing = MagicMock()
    viewer = MagicMock()
    viewer.playing = False
    viewer.attach_companion_stack = MagicMock()
    viewer.update_companion_stack = MagicMock()
    viewer.set_wlww_sync = MagicMock()
    viewer.set_segmentation_overlays = MagicMock()
    viewer.active_layers = set()
    viewer.overlay_data = {}
    viewer.SMALL_JUMP_PERCENTAGE = ImageViewer.SMALL_JUMP_PERCENTAGE
    viewer.LARGE_JUMP_PERCENTAGE = ImageViewer.LARGE_JUMP_PERCENTAGE
    dialog.image_viewer = viewer

    with patch("anonymizer.view.face_blur_review_dialog.mask_slice_segmentations", return_value=[]):
        with patch("anonymizer.view.face_blur_review_dialog.face_review_wl_ww", return_value=(40.0, 400.0)):
            with patch("anonymizer.view.face_blur_review_dialog.format_face_blur_qa_summary", return_value="QA"):
                FaceBlurReviewDialog._show_blur_review(dialog, preview)

    viewer.attach_companion_stack.assert_not_called()
    viewer.update_companion_stack.assert_called_once()
    dialog._save_button.configure.assert_called_once_with(state="normal")


def test_poll_blur_worker_shows_error_and_closes() -> None:
    dialog = FaceBlurReviewDialog.__new__(FaceBlurReviewDialog)
    dialog._widget_alive = MagicMock(return_value=True)
    dialog._blur_running = True
    dialog._blur_worker_queue = queue.Queue()
    dialog._blur_worker_queue.put(("done", SimpleNamespace(error="failed")))
    dialog._close = MagicMock()
    dialog.after = MagicMock()

    with patch("anonymizer.view.face_blur_review_dialog.messagebox.showerror"):
        FaceBlurReviewDialog._poll_blur_worker(dialog)

    dialog._close.assert_called_once_with(cancelled=True)


def test_save_button_clicked_writes_frames_and_metadata(sample_frames: np.ndarray) -> None:
    dialog = FaceBlurReviewDialog.__new__(FaceBlurReviewDialog)
    dialog._ds = MagicMock(SeriesInstanceUID="series-1")
    dialog._series_path = MagicMock()
    dialog._slice_frames = sample_frames
    dialog._anon_model = MagicMock()
    dialog._preview = SimpleNamespace(
        error=None,
        blurred_slice_frames=sample_frames.astype(np.float32),
        slice_count=3,
        qa_stats=None,
        blur_mode=FaceBlurMode.GAUSSIAN,
        hu_after=None,
        slice_paths=(),
    )
    dialog._close = MagicMock()

    with (
        patch("anonymizer.view.face_blur_review_dialog.save_series_frames", return_value=True) as save_frames,
        patch("anonymizer.view.face_blur_review_dialog.apply_series_face_blur_metadata") as apply_metadata,
    ):
        FaceBlurReviewDialog._save_button_clicked(dialog)

    save_frames.assert_called_once()
    apply_metadata.assert_called_once()
    dialog._close.assert_called_once_with(saved=True)


def test_blur_face_button_clicked_closes_series_and_opens_dialog() -> None:
    from anonymizer.controller.blur_face import FaceBlurGateDecision
    from anonymizer.view.series import SeriesView

    series = SeriesView.__new__(SeriesView)
    series._ds = SimpleNamespace(SeriesInstanceUID="anon-series-1")
    series._anon_model = MagicMock()
    series._anon_model.series_has_face_blur.return_value = False
    series._series_interaction_allowed = MagicMock(return_value=True)
    series._blur_face_toolbar_state = MagicMock(return_value="normal")
    series._face_blur_eligibility = MagicMock(
        return_value=SimpleNamespace(
            decision=FaceBlurGateDecision.ALLOW,
            reason=SimpleNamespace(name="METADATA_HEAD"),
        ),
    )
    series._selected_face_blur_mode = MagicMock(return_value=FaceBlurMode.GAUSSIAN)
    series._series_path = MagicMock()
    series._find_phi_index = MagicMock(return_value=MagicMock())
    series._on_cancel = MagicMock()

    with (
        patch("anonymizer.view.series.find_phi_index_parent", series._find_phi_index),
        patch("anonymizer.view.series.show_face_blur_review_dialog") as show_dialog,
    ):
        SeriesView.blur_face_button_clicked(series)

    series._on_cancel.assert_called_once()
    show_dialog.assert_called_once()


def test_show_face_blur_review_dialog_returns_outcome() -> None:
    parent = MagicMock()
    expected = FaceBlurReviewOutcome(saved=True, cancelled=False)
    dialog = MagicMock()
    dialog.get_input.return_value = expected

    with patch("anonymizer.view.face_blur_review_dialog.FaceBlurReviewDialog", return_value=dialog):
        outcome = show_face_blur_review_dialog(
            parent,
            anon_model=MagicMock(),
            series_path=MagicMock(),
            blur_mode=FaceBlurMode.GAUSSIAN,
        )

    assert outcome == expected
