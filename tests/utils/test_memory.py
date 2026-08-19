"""Tests for batch memory estimation helpers."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from anonymizer.utils.memory import collect_garbage_safe, estimate_batch_resources


def test_estimate_batch_resources_is_per_series_not_pending_count() -> None:
    """Memory estimate must not scale with how many series are queued."""
    single = estimate_batch_resources(
        includes_pixel_phi=True,
        includes_harmonize=True,
        includes_face_blur=True,
    )
    assert single.min_available_mb == 7_000.0
    assert "pending series" not in single.notes.lower()


def test_estimate_batch_resources_algorithm_additions() -> None:
    base = estimate_batch_resources(
        includes_pixel_phi=False,
        includes_harmonize=False,
        includes_face_blur=False,
    )
    assert base.min_available_mb == 1_500.0

    ocr = estimate_batch_resources(
        includes_pixel_phi=True,
        includes_harmonize=False,
        includes_face_blur=False,
    )
    assert ocr.min_available_mb == 3_000.0

    harmonize = estimate_batch_resources(
        includes_pixel_phi=False,
        includes_harmonize=True,
        includes_face_blur=False,
    )
    assert harmonize.min_available_mb == 4_000.0

    face_blur = estimate_batch_resources(
        includes_pixel_phi=False,
        includes_harmonize=False,
        includes_face_blur=True,
    )
    assert face_blur.min_available_mb == 3_000.0


@patch("anonymizer.utils.memory.gc.collect")
def test_collect_garbage_safe_skips_gc_off_main_thread(mock_gc: MagicMock) -> None:
    done = threading.Event()

    def worker() -> None:
        collect_garbage_safe()
        done.set()

    thread = threading.Thread(target=worker, name="TestWorker")
    thread.start()
    thread.join(timeout=5.0)
    assert done.is_set()
    mock_gc.assert_not_called()


@patch("anonymizer.utils.memory.gc.collect")
def test_collect_garbage_safe_runs_gc_on_main_thread(mock_gc: MagicMock) -> None:
    collect_garbage_safe(generations=2)
    assert mock_gc.call_count == 2
