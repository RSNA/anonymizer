"""Main-thread poller for background WorkState jobs."""

from __future__ import annotations

import contextlib
import logging
import threading
import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from anonymizer.controller.runner import Algorithm
from anonymizer.controller.work_state import WorkState

logger = logging.getLogger(__name__)

FRAME_POLL_MS = 200
BATCH_POLL_MS = 300
LOAD_POLL_MS = 300
STAGE_POLL_MS = 500
DEFAULT_POLL_MS = FRAME_POLL_MS


def _progress_detail_tick_key(detail: object | None) -> tuple[object, ...] | None:
    if detail is None:
        return None
    stage = getattr(detail, "stage", None)
    if stage is not None:
        return (
            stage,
            getattr(detail, "fraction", None),
            getattr(detail, "message", None),
        )
    return (detail,)


class JobPoller:
    def __init__(
        self,
        widget: ctk.CTkBaseClass,
        work_state: WorkState,
        *,
        on_tick: Callable[[WorkState], None] | None = None,
        on_done: Callable[[Algorithm | None, WorkState], None] | None = None,
        algorithm: Algorithm | None = None,
        poll_ms: int = DEFAULT_POLL_MS,
    ) -> None:
        self._widget = widget
        self._work_state = work_state
        self._on_tick = on_tick
        self._on_done = on_done
        self._algorithm = algorithm
        self._poll_ms = poll_ms
        self._running = False
        self._done_called = False
        self._last_tick_key: tuple[object, ...] | None = None

    def start(self) -> None:
        logger.info("JobPoller.start algorithm=%s poll_ms=%s", self._algorithm, self._poll_ms)
        self._running = True
        self._last_tick_key = None
        self._poll()

    def _widget_alive(self) -> bool:
        with contextlib.suppress(tk.TclError):
            return bool(self._widget.winfo_exists())
        return False

    def _tick_key(self) -> tuple[object, ...]:
        frame_index, status, done, _result = self._work_state.snapshot_progress()
        _status, _done, fraction, _error, _result, detail = self._work_state.read_job_ui()
        return (
            frame_index,
            status,
            done,
            fraction,
            _progress_detail_tick_key(detail),
            self._work_state.log_sequence(),
        )

    def _poll(self) -> None:
        if not self._running:
            return
        if not self._widget_alive():
            logger.debug("JobPoller stopping: widget destroyed")
            self._running = False
            return

        tick_key = self._tick_key()
        frame_index, status, done, _fraction, _detail_key, _log_seq = tick_key
        state_changed = tick_key != self._last_tick_key
        if state_changed:
            logger.debug(
                "JobPoller._poll frame_index=%s done=%s status=%r thread=%s",
                frame_index,
                done,
                status,
                threading.current_thread().name,
            )

        if self._on_tick is not None and (state_changed or done):
            self._on_tick(self._work_state)
        self._last_tick_key = tick_key

        if done:
            if not self._done_called and self._on_done is not None:
                self._done_called = True
                logger.info("JobPoller calling on_done algorithm=%s", self._algorithm)
                self._on_done(self._algorithm, self._work_state)
            self._running = False
            return
        if self._widget_alive():
            self._widget.after(self._poll_ms, self._poll)
        else:
            self._running = False


def start_background_job(
    widget: ctk.CTkBaseClass,
    *,
    work_state: WorkState,
    algorithm: Algorithm | None,
    worker_target: Callable[[], None],
    on_tick: Callable[[WorkState], None] | None = None,
    on_done: Callable[[Algorithm | None, WorkState], None] | None = None,
    poll_ms: int = DEFAULT_POLL_MS,
) -> None:
    """Start JobPoller on main thread and worker_target on a daemon thread."""
    logger.info("start_background_job algorithm=%s", algorithm)
    JobPoller(
        widget,
        work_state,
        on_tick=on_tick,
        on_done=on_done,
        algorithm=algorithm,
        poll_ms=poll_ms,
    ).start()
    threading.Thread(
        target=worker_target,
        name=f"job-{algorithm}" if algorithm is not None else "job-worker",
        daemon=True,
    ).start()
