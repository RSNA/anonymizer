"""Process memory logging helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

MemoryPressure = Literal["ok", "warn", "abort"]


@dataclass(frozen=True)
class MemorySnapshot:
    rss_mb: float
    available_mb: float
    total_mb: float
    percent_used: float


@dataclass(frozen=True)
class BatchResourceEstimate:
    min_available_mb: float
    notes: str


def format_array_memory(array: np.ndarray | None) -> str:
    if array is None:
        return "array=none"
    return f"array shape={array.shape} dtype={array.dtype} nbytes={array.nbytes / (1024 * 1024):.1f}MB"


def capture_memory_snapshot() -> MemorySnapshot | None:
    """Return current process RSS and system memory usage, or None when psutil is unavailable."""
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        rss_mb = proc.memory_info().rss / (1024 * 1024)
        vm = psutil.virtual_memory()
        return MemorySnapshot(
            rss_mb=rss_mb,
            available_mb=vm.available / (1024 * 1024),
            total_mb=vm.total / (1024 * 1024),
            percent_used=vm.percent,
        )
    except Exception:
        return None


def format_memory_snapshot_label(snapshot: MemorySnapshot) -> str:
    """User-facing one-line memory summary for batch dialog."""
    from anonymizer.utils.translate import _

    return _("Memory available") + f": {snapshot.available_mb / 1024:.1f} GB"


def estimate_batch_resources(
    *,
    includes_pixel_phi: bool,
    includes_harmonize: bool,
    includes_face_blur: bool,
) -> BatchResourceEstimate:
    """Heuristic minimum available system memory (MB) for one AI batch series."""
    from anonymizer.utils.translate import _

    base_mb = 1_500.0
    if includes_pixel_phi:
        base_mb += 1_500.0
    if includes_harmonize:
        base_mb += 2_500.0
    if includes_face_blur:
        base_mb += 1_500.0

    parts: list[str] = []
    if includes_pixel_phi:
        parts.append(_("OCR"))
    if includes_harmonize:
        parts.append(_("harmonize"))
    if includes_face_blur:
        parts.append(_("face blur"))
    algo_text = ", ".join(parts) if parts else _("batch")
    notes = _("Recommended available memory per series for batch run with") + f" {algo_text}"
    return BatchResourceEstimate(min_available_mb=base_mb, notes=notes)


class MemoryGuard:
    """Cooperative low-memory guard for batch processing (series-boundary checks)."""

    def __init__(
        self,
        *,
        warn_available_mb: float | None = None,
        abort_available_mb: float | None = None,
    ) -> None:
        from anonymizer.controller.ai.tseg.config import (
            BATCH_MEMORY_ABORT_AVAILABLE_MB,
            BATCH_MEMORY_WARN_AVAILABLE_MB,
        )

        self._warn_available_mb = (
            warn_available_mb if warn_available_mb is not None else float(BATCH_MEMORY_WARN_AVAILABLE_MB)
        )
        self._abort_available_mb = (
            abort_available_mb if abort_available_mb is not None else float(BATCH_MEMORY_ABORT_AVAILABLE_MB)
        )
        self._warned = False

    def check(self, snapshot: MemorySnapshot | None) -> MemoryPressure:
        if snapshot is None:
            return "ok"
        if snapshot.available_mb < self._abort_available_mb:
            return "abort"
        if snapshot.available_mb < self._warn_available_mb:
            return "warn"
        return "ok"

    def should_log_warn(self) -> bool:
        if self._warned:
            return False
        self._warned = True
        return True


def log_process_memory(
    stage: str,
    *,
    array: np.ndarray | None = None,
    extra: str = "",
    log: logging.Logger | None = None,
) -> float | None:
    """Log process RSS and optional NumPy array size; return RSS in MB when available."""
    target = log or logger
    suffix = format_array_memory(array)
    if extra:
        suffix = f"{extra}; {suffix}"
    snapshot = capture_memory_snapshot()
    if snapshot is None:
        target.info("Memory [%s]: RSS unavailable (%s)", stage, suffix)
        return None
    target.info("Memory [%s]: RSS %.1f MB (%s)", stage, snapshot.rss_mb, suffix)
    return snapshot.rss_mb
