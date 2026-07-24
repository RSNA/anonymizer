"""Process memory logging helpers."""

from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)


def format_array_memory(array: np.ndarray | None) -> str:
    if array is None:
        return "array=none"
    return (
        f"array shape={array.shape} dtype={array.dtype} "
        f"nbytes={array.nbytes / (1024 * 1024):.1f}MB"
    )


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
    try:
        import psutil

        rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        target.info("Memory [%s]: RSS unavailable (%s)", stage, suffix)
        return None
    target.info("Memory [%s]: RSS %.1f MB (%s)", stage, rss_mb, suffix)
    return rss_mb
