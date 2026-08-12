"""Tests for JobPoller and start_background_job."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from anonymizer.controller.harmonize import HarmonizeProgress
from anonymizer.controller.runner import Algorithm
from anonymizer.controller.work_state import WorkState
from anonymizer.view.job_poller import JobPoller, start_background_job


class _FakeWidget:
    def __init__(self) -> None:
        self._callbacks: list[tuple[int, object]] = []
        self._exists = True

    def winfo_exists(self) -> bool:
        return self._exists

    def after(self, ms: int, callback) -> str:
        self._callbacks.append((ms, callback))
        return f"id-{len(self._callbacks)}"

    def run_pending(self) -> None:
        while self._callbacks:
            _ms, cb = self._callbacks.pop(0)
            cb()


def test_job_poller_calls_on_done_when_finished() -> None:
    widget = _FakeWidget()
    ws = WorkState()
    ws.done = True
    on_done = MagicMock()
    poller = JobPoller(widget, ws, on_done=on_done, algorithm=Algorithm.REMOVE_PIXEL_PHI, poll_ms=10)
    poller.start()
    widget.run_pending()
    on_done.assert_called_once_with(Algorithm.REMOVE_PIXEL_PHI, ws)


def test_job_poller_calls_on_tick_when_already_done() -> None:
    """Final OCR result must be visible on the last poll (on_tick runs even when done=True)."""
    widget = _FakeWidget()
    ws = WorkState()
    ws.done = True
    ws.result = {"frame": 0}
    on_tick = MagicMock()
    JobPoller(widget, ws, on_tick=on_tick, poll_ms=10).start()
    on_tick.assert_called_once_with(ws)


def test_job_poller_skips_on_tick_when_snapshot_unchanged() -> None:
    widget = _FakeWidget()
    ws = WorkState()
    ws.set_status("working")
    on_tick = MagicMock()
    poller = JobPoller(widget, ws, on_tick=on_tick, poll_ms=10)
    poller._running = True
    poller._poll()
    on_tick.assert_called_once_with(ws)

    on_tick.reset_mock()
    poller._poll()
    on_tick.assert_not_called()


def test_job_poller_calls_on_tick_when_progress_detail_changes() -> None:
    widget = _FakeWidget()
    ws = WorkState()
    ws.update_job_progress(
        status="Analyzing",
        fraction=0.25,
        detail=HarmonizeProgress(stage="geometry", message="geo", fraction=0.25, elapsed_sec=0.1),
    )
    on_tick = MagicMock()
    poller = JobPoller(widget, ws, on_tick=on_tick, poll_ms=10)
    poller._running = True
    poller._poll()
    on_tick.assert_called_once_with(ws)

    on_tick.reset_mock()
    poller._poll()
    on_tick.assert_not_called()

    ws.update_job_progress(
        status="Analyzing",
        fraction=0.5,
        detail=HarmonizeProgress(stage="regions", message="regions", fraction=0.5, elapsed_sec=1.0),
    )
    poller._poll()
    on_tick.assert_called_once_with(ws)


def test_start_background_job_runs_worker() -> None:
    widget = _FakeWidget()
    ws = WorkState()
    ran = threading.Event()

    def worker() -> None:
        ws.set_status("busy")
        ws.finish(None)
        ran.set()

    start_background_job(
        widget,
        work_state=ws,
        algorithm=Algorithm.REMOVE_PIXEL_PHI,
        worker_target=worker,
        poll_ms=1,
    )
    deadline = time.time() + 2.0
    while not ran.is_set() and time.time() < deadline:
        time.sleep(0.01)
    assert ran.is_set()
