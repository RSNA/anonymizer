"""Unit tests for storage free-space helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from anonymizer.utils.disk import (
    DISK_FREE_ABORT_BYTES,
    DISK_FREE_WARN_BYTES,
    DiskGuard,
    format_free_bytes,
    free_bytes,
)


def test_format_free_bytes_gib_and_mib() -> None:
    assert format_free_bytes(3 << 30) == "3.0 GiB"
    assert format_free_bytes(512 << 20) == "512 MiB"


def test_free_bytes_reads_shutil() -> None:
    with patch("anonymizer.utils.disk.shutil.disk_usage", return_value=SimpleNamespace(free=12345)) as mock_du:
        assert free_bytes("/tmp") == 12345
        mock_du.assert_called_once_with("/tmp")


def test_free_bytes_oserror_returns_none() -> None:
    with patch("anonymizer.utils.disk.shutil.disk_usage", side_effect=OSError("boom")):
        assert free_bytes("/missing") is None


def test_disk_guard_pressure_bands() -> None:
    guard = DiskGuard(warn_free_bytes=1000, abort_free_bytes=100, ttl_seconds=60.0)
    with patch("anonymizer.utils.disk.free_bytes", return_value=50):
        assert guard.check("/data", now=1.0) == "abort"
    with patch("anonymizer.utils.disk.free_bytes", return_value=500):
        # Force cache miss with a later timestamp past TTL... use fresh guard
        guard2 = DiskGuard(warn_free_bytes=1000, abort_free_bytes=100, ttl_seconds=60.0)
        assert guard2.check("/data", now=1.0) == "warn"
    with patch("anonymizer.utils.disk.free_bytes", return_value=5000):
        guard3 = DiskGuard(warn_free_bytes=1000, abort_free_bytes=100, ttl_seconds=60.0)
        assert guard3.check("/data", now=1.0) == "ok"


def test_disk_guard_fail_open_when_unreadable() -> None:
    guard = DiskGuard(warn_free_bytes=1000, abort_free_bytes=100, ttl_seconds=60.0)
    with patch("anonymizer.utils.disk.free_bytes", return_value=None):
        assert guard.check("/data", now=1.0) == "ok"


def test_disk_guard_ttl_cache_avoids_repeat_syscall() -> None:
    guard = DiskGuard(warn_free_bytes=1000, abort_free_bytes=100, ttl_seconds=10.0)
    with patch("anonymizer.utils.disk.free_bytes", return_value=500) as mock_free:
        assert guard.check("/data", now=1.0) == "warn"
        assert guard.check("/data", now=5.0) == "warn"
        mock_free.assert_called_once_with("/data")
        assert guard.check("/data", now=12.0) == "warn"
        assert mock_free.call_count == 2


def test_disk_guard_should_log_warn_once() -> None:
    guard = DiskGuard()
    assert guard.should_log_warn() is True
    assert guard.should_log_warn() is False


def test_disk_guard_abort_message_includes_free_space() -> None:
    guard = DiskGuard()
    with patch("anonymizer.utils.disk.free_bytes", return_value=1 << 30):
        msg = guard.abort_message(Path("/storage"))
    assert "1.0 GiB" in msg
    assert "/storage" in msg


def test_disk_guard_against_real_free_space_via_threshold() -> None:
    """
    Integration-style: set abort just above measured free space so the live
    syscall path trips without filling the disk.
    """
    path = Path(".")
    measured = free_bytes(path)
    assert measured is not None
    guard = DiskGuard(
        warn_free_bytes=measured + (2 << 20),
        abort_free_bytes=measured + (1 << 20),
        ttl_seconds=0.0,
    )
    assert guard.check(path) == "abort"

    ok_guard = DiskGuard(
        warn_free_bytes=max(1, measured // 2),
        abort_free_bytes=max(1, measured // 4),
        ttl_seconds=0.0,
    )
    assert ok_guard.check(path) == "ok"


def test_default_thresholds_are_ordered() -> None:
    assert DISK_FREE_ABORT_BYTES < DISK_FREE_WARN_BYTES
