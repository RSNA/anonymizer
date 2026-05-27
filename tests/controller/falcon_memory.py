"""RSS memory helpers for FALCON controller tests."""

from __future__ import annotations

import gc

import psutil


def process_rss_mb() -> float:
    """Return current process resident set size in megabytes."""
    return psutil.Process().memory_info().rss / (1024 * 1024)


def collect_garbage() -> None:
    """Run a full garbage collection cycle before measuring RSS."""
    gc.collect()
