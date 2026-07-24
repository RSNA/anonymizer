"""Tests for Series View single-pane startup and companion-stack lifecycle."""

from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from anonymizer.view.image import ImageViewer
from anonymizer.view.series import SeriesView


@pytest.fixture
def sample_frames() -> np.ndarray:
    return np.arange(3 * 4 * 5, dtype=np.uint16).reshape(3, 4, 5)


def test_detach_companion_stack_resets_dual_column_layout(sample_frames: np.ndarray) -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.num_images = sample_frames.shape[0]
    viewer._companion_images = sample_frames
    viewer.companion_canvas = MagicMock()
    viewer.companion_canvas_image_item = 1
    viewer._primary_label = MagicMock()
    viewer._companion_label = MagicMock()
    viewer._companion_cache = {0: ("cached", (4, 5))}
    viewer.image_frame = MagicMock()
    viewer.canvas = MagicMock()
    viewer.scrollbar = MagicMock()

    ImageViewer.detach_companion_stack(viewer)

    assert viewer.companion_canvas is None
    assert viewer.companion_attached is False
    assert viewer._companion_images is None
    assert viewer._companion_cache == {}
    viewer.image_frame.grid_columnconfigure.assert_any_call(0, weight=1)
    viewer.image_frame.grid_columnconfigure.assert_any_call(1, weight=0)
    viewer.canvas.grid.assert_called_with(row=0, column=0, sticky="nsew", padx=0)


def test_poll_blur_worker_ignores_stale_done_after_cancel() -> None:
    series = SeriesView.__new__(SeriesView)
    series.winfo_exists = MagicMock(return_value=True)
    series._blur_running = False
    series._blur_worker_queue = queue.Queue()
    series._blur_worker_queue.put(("done", SimpleNamespace(error=None)))
    series._show_blur_review = MagicMock()
    series.after = MagicMock()

    SeriesView._poll_blur_worker(series)

    series._show_blur_review.assert_not_called()
    series.after.assert_called_once()


def test_poll_blur_worker_processes_done_while_running() -> None:
    preview = SimpleNamespace(error=None)
    series = SeriesView.__new__(SeriesView)
    series.winfo_exists = MagicMock(return_value=True)
    series._blur_running = True
    series._blur_worker_queue = queue.Queue()
    series._blur_worker_queue.put(("done", preview))
    series._show_blur_review = MagicMock()
    series.after = MagicMock()

    SeriesView._poll_blur_worker(series)

    series._show_blur_review.assert_called_once_with(preview)
    assert series._blur_running is False
    series.after.assert_not_called()


def test_drain_blur_worker_queue_discards_pending_messages() -> None:
    worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    worker_queue.put(("progress", object()))
    worker_queue.put(("done", object()))

    SeriesView._drain_blur_worker_queue(worker_queue)

    assert worker_queue.empty()
