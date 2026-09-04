"""Shared mutable state for background algorithm jobs (worker writes, UI polls)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from numpy import ndarray
from pydicom import Dataset

if TYPE_CHECKING:
    from anonymizer.controller.runner import Algorithm

logger = logging.getLogger(__name__)


@dataclass
class WorkState:
    """Lock-protected job progress; bound to one series volume during processing."""

    ds: Dataset | None = None
    frames: ndarray | None = None
    ocr_pixels: ndarray | None = None
    slice_paths: tuple[Path, ...] | None = None
    default_window: tuple[float, float] = (0.0, 0.0)
    single_frame: bool = True
    frame_index: int = 0
    status: str = ""
    done: bool = False
    cancel_requested: bool = False
    error: str | None = None
    result: object | None = None
    batch_logs: list[str] = field(default_factory=list)
    fraction: float = 0.0
    progress_detail: object | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bind(
        self,
        ds: Dataset,
        frames: ndarray,
        slice_paths: tuple[Path, ...],
        default_window: tuple[float, float],
        *,
        single_frame: bool,
    ) -> None:
        with self._lock:
            logger.info(
                "WorkState.bind: series=%s frames_shape=%s single_frame=%s",
                getattr(ds, "SeriesInstanceUID", "?"),
                frames.shape,
                single_frame,
            )
            self.ds = ds
            self.frames = frames
            self.ocr_pixels = None
            self.slice_paths = slice_paths
            self.default_window = default_window
            self.single_frame = single_frame
            self.frame_index = 0
            self.status = ""
            self.done = False
            self.cancel_requested = False
            self.error = None
            self.result = None
            self.fraction = 0.0
            self.progress_detail = None

    def reset(self) -> None:
        with self._lock:
            logger.debug("WorkState.reset")
            self.ds = None
            self.frames = None
            self.ocr_pixels = None
            self.slice_paths = None
            self.done = False
            self.cancel_requested = False
            self.error = None
            self.result = None
            self.fraction = 0.0
            self.progress_detail = None

    def prepare_job(self) -> None:
        """Reset completion fields for a new background job on this instance."""
        with self._lock:
            self.done = False
            self.cancel_requested = False
            self.error = None
            self.result = None
            self.status = ""
            self.fraction = 0.0
            self.progress_detail = None

    def set_progress(self, frame_index: int, status: str) -> None:
        with self._lock:
            self.frame_index = frame_index
            self.status = status
        logger.debug("WorkState.set_progress: frame_index=%s status=%r", frame_index, status)

    def set_status(self, status: str) -> None:
        with self._lock:
            self.status = status
        logger.debug("WorkState.set_status: %r", status)

    def update_job_progress(
        self,
        *,
        status: str | None = None,
        fraction: float | None = None,
        detail: object | None = None,
    ) -> None:
        with self._lock:
            if status is not None:
                self.status = status
            if fraction is not None:
                self.fraction = fraction
            if detail is not None:
                self.progress_detail = detail

    def read_job_ui(
        self,
    ) -> tuple[str, bool, float, str | None, object | None, object | None]:
        with self._lock:
            result = self.result
            detail = self.progress_detail
            return self.status, self.done, self.fraction, self.error, result, detail

    def append_log(self, line: str) -> None:
        with self._lock:
            self.batch_logs.append(line)

    def drain_logs(self) -> list[str]:
        with self._lock:
            drained = list(self.batch_logs)
            self.batch_logs.clear()
            return drained

    def should_cancel(self) -> bool:
        with self._lock:
            return self.cancel_requested

    def request_cancel(self) -> None:
        with self._lock:
            if self.cancel_requested:
                logger.debug("WorkState.request_cancel (already requested)")
                return
            logger.info("WorkState.request_cancel")
            self.cancel_requested = True

    def finish(self, result: object | None = None) -> None:
        with self._lock:
            self.result = result
            self.done = True
        logger.info("WorkState.finish")

    def fail(self, message: str) -> None:
        with self._lock:
            self.error = message
            self.done = True
        logger.error("WorkState.fail: %s", message)

    def _require_frames(self) -> ndarray:
        if self.frames is None:
            raise RuntimeError("WorkState.frames is not bound")
        return self.frames

    def frame_count(self, algorithm: Algorithm) -> int:
        frames = self._require_frames()
        return int(frames.shape[0])

    def frame_at(self, frame_index: int, algorithm: Algorithm) -> ndarray:
        frames = self._require_frames()
        return frames[frame_index]

    def snapshot_progress(self) -> tuple[int, str, bool, object | None]:
        with self._lock:
            result = self.result
            if isinstance(result, dict):
                result = dict(result)
            return self.frame_index, self.status, self.done, result
