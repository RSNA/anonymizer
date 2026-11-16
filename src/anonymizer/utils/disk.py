"""Free-space checks for the project storage directory.

Used at transfer boundaries (C-STORE, local import, export) so low disk is
handled before more files are written. Checks are TTL-cached to keep the hot
C-STORE path cheap.

Public API
----------
DiskPressure
    "ok", "warn", or "abort" relative to free-space thresholds.

DISK_FREE_WARN_BYTES
    Default warn threshold: 5 GiB free.

DISK_FREE_ABORT_BYTES
    Default abort threshold: 1 GiB free.

DISK_CHECK_TTL_SECONDS
    Default cache lifetime for free-space reads (2 seconds).

free_bytes(path: Path | str) -> int | None
    Free bytes on the volume containing path, or None if unavailable.

format_free_bytes(n: int) -> str
    Short human-readable free-space string (e.g. "1.5 GiB").

DiskGuard
    Cooperative low-disk guard with TTL-cached checks and one-shot warn logging.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Literal

from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

DiskPressure = Literal["ok", "warn", "abort"]

# Defaults sized for medical imaging workloads (GiB-scale studies).
DISK_FREE_WARN_BYTES = 5 << 30
DISK_FREE_ABORT_BYTES = 1 << 30
DISK_CHECK_TTL_SECONDS = 2.0


def free_bytes(path: Path | str) -> int | None:
    """
    Return free bytes on the volume that contains path.

    Args:
        path: File or directory on the volume to measure.

    Returns:
        Free bytes, or None when the OS query fails.
    """
    try:
        return int(shutil.disk_usage(path).free)
    except OSError:
        logger.debug("disk_usage failed for %s", path, exc_info=True)
        return None


def format_free_bytes(n: int) -> str:
    """
    Format a byte count for logs and short UI messages.

    Args:
        n: Free bytes.

    Returns:
        Compact string using GiB or MiB.
    """
    gib = 1 << 30
    mib = 1 << 20
    if n >= gib:
        return f"{n / gib:.1f} GiB"
    return f"{n / mib:.0f} MiB"


class DiskGuard:
    """Cooperative low-disk guard (transfer-boundary checks with TTL cache)."""

    def __init__(
        self,
        *,
        warn_free_bytes: int | None = None,
        abort_free_bytes: int | None = None,
        ttl_seconds: float | None = None,
    ) -> None:
        """
        Create a guard with warn/abort free-space thresholds.

        Args:
            warn_free_bytes: Free bytes below which pressure is "warn".
            abort_free_bytes: Free bytes below which pressure is "abort".
            ttl_seconds: How long a free-space sample stays valid.
        """
        self._warn_free_bytes = int(
            DISK_FREE_WARN_BYTES if warn_free_bytes is None else warn_free_bytes
        )
        self._abort_free_bytes = int(
            DISK_FREE_ABORT_BYTES if abort_free_bytes is None else abort_free_bytes
        )
        self._ttl_seconds = float(
            DISK_CHECK_TTL_SECONDS if ttl_seconds is None else ttl_seconds
        )
        self._cached_free: int | None = None
        self._cached_at: float = 0.0
        self._warned = False

    def check(self, path: Path | str, *, now: float | None = None) -> DiskPressure:
        """
        Classify free space on the volume containing path.

        When free space cannot be read, returns "ok" (fail-open) so transfers
        are not blocked by a probe failure; write errors still quarantine.

        Args:
            path: Storage directory (or any path on that volume).
            now: Optional monotonic time for tests; defaults to time.monotonic().

        Returns:
            "abort", "warn", or "ok".
        """
        free = self._free_bytes_cached(path, now=now)
        if free is None:
            return "ok"
        if free < self._abort_free_bytes:
            return "abort"
        if free < self._warn_free_bytes:
            return "warn"
        return "ok"

    def last_free_bytes(self) -> int | None:
        """Most recently cached free-byte sample, if any."""
        return self._cached_free

    def should_log_warn(self) -> bool:
        """
        True once per guard lifetime for the first warn-level pressure.

        Returns:
            Whether the caller should emit a warn log/UI notice.
        """
        if self._warned:
            return False
        self._warned = True
        return True

    def abort_message(self, path: Path | str | None = None) -> str:
        """
        User-facing message when transfers must stop for low disk.

        Args:
            path: Optional storage path included in the message.

        Returns:
            Localized short explanation including free space when known.
        """
        free = self._cached_free
        if free is None and path is not None:
            free = free_bytes(path)
        free_text = format_free_bytes(free) if free is not None else _("unknown")
        base = _("Storage disk space is critically low") + f" ({free_text} {_('free')})"
        if path is not None:
            return f"{base}: {path}"
        return base

    def _free_bytes_cached(self, path: Path | str, *, now: float | None) -> int | None:
        """
        Return free bytes, reusing the cache when still within TTL.

        Args:
            path: Volume path to query on a cache miss.
            now: Optional monotonic timestamp.

        Returns:
            Free bytes or None.
        """
        t = time.monotonic() if now is None else now
        if self._cached_free is not None and (t - self._cached_at) < self._ttl_seconds:
            return self._cached_free
        free = free_bytes(path)
        self._cached_free = free
        self._cached_at = t
        return free
