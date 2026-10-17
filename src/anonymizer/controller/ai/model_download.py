"""Thread-safe progress tracking for AI model downloads (any feature)."""

from __future__ import annotations

import contextlib
import io
import sys
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from tqdm import tqdm as orig_tqdm

from anonymizer.utils.translate import _

_download_lock = threading.Lock()


@dataclass(frozen=True)
class DownloadProgress:
    """Snapshot of one in-flight AI model download."""

    message: str = ""
    fraction: float | None = None


_download_progress: dict[str, DownloadProgress] = {}


def begin_model_download(download_id: str, *, message: str = "") -> None:
    """
    Register a model download under ``download_id``.

    Args:
        download_id: Stable feature key for UI polling.
        message: Initial status message.
    """
    with _download_lock:
        _download_progress[download_id] = DownloadProgress(message=message or _("Downloading…"), fraction=None)


def update_model_download(
    download_id: str,
    *,
    message: str | None = None,
    fraction: float | None | object = ...,
) -> None:
    """
    Update progress for an active download; no-op if ``download_id`` is unknown.

    Args:
        download_id: Stable feature key.
        message: New message, or None to keep the current one.
        fraction: New fraction, ``...`` to keep current, or None to clear.
    """
    with _download_lock:
        current = _download_progress.get(download_id)
        if current is None:
            return
        new_message = current.message if message is None else message
        new_fraction = current.fraction if fraction is ... else fraction
        _download_progress[download_id] = DownloadProgress(message=new_message, fraction=new_fraction)


def end_model_download(download_id: str) -> None:
    """
    Clear progress for ``download_id`` when a download finishes or fails.

    Args:
        download_id: Stable feature key.
    """
    with _download_lock:
        _download_progress.pop(download_id, None)


def get_model_download_progress(download_id: str) -> DownloadProgress | None:
    """
    Return the current progress snapshot for ``download_id``, if any.

    Args:
        download_id: Stable feature key.

    Returns:
        Progress snapshot or None.
    """
    with _download_lock:
        return _download_progress.get(download_id)


def is_model_download_active(download_id: str) -> bool:
    """
    True when a download is registered for ``download_id``.

    Args:
        download_id: Stable feature key.

    Returns:
        Whether the download is active.
    """
    return get_model_download_progress(download_id) is not None


def any_model_download_active() -> bool:
    """True when any model download is in progress."""
    with _download_lock:
        return bool(_download_progress)


def _format_download_bytes(num: float) -> str:
    """Format a byte count for download progress messages."""
    if num < 1024:
        return f"{num:.0f}B"
    num /= 1024
    if num < 1024:
        return f"{num:.1f}KB"
    num /= 1024
    if num < 1024:
        return f"{num:.1f}MB"
    num /= 1024
    return f"{num:.1f}GB"


class _DownloadStdoutCapture(io.TextIOBase):
    """Forward stdout while reporting stripped lines to a progress callback."""

    def __init__(self, original: io.TextIOBase, on_line: Callable[[str], None]) -> None:
        self._original = original
        self._on_line = on_line
        self._buffer = ""

    def write(self, s: str) -> int:
        self._original.write(s)
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            text = line.strip()
            if text:
                self._on_line(text)
        return len(s)

    def flush(self) -> None:
        self._original.flush()
        text = self._buffer.strip()
        if text:
            self._on_line(text)
            self._buffer = ""

    def __getattr__(self, name: str):
        return getattr(self._original, name)


@contextlib.contextmanager
def track_tqdm_model_download(
    download_id: str,
    *,
    start_message: str | None = None,
    label: str = "",
    tqdm_module: object,
    on_progress: Callable[[str, float | None], None] | None = None,
    manage_lifecycle: bool = True,
) -> Iterator[None]:
    """
    Capture tqdm/stdout progress while a third-party library downloads model weights.

    Args:
        download_id: Stable key for UI polling (e.g. ``remove_pixel_phi``, ``enable_harmonize``).
        start_message: Initial status line (used when ``label`` is empty).
        label: Optional model name shown after ``Downloading:`` with byte progress.
        tqdm_module: Module object whose ``tqdm`` attribute will be patched (e.g. ``totalsegmentator.libs``).
        on_progress: Optional ``(message, fraction)`` callback on each update.
        manage_lifecycle: When False, only report updates; caller owns begin/end_model_download.
    """
    resolved_start_message = start_message or _("Downloading…")
    resolved_start = _("Downloading: {label}…").format(label=label) if label else resolved_start_message
    if manage_lifecycle or get_model_download_progress(download_id) is None:
        begin_model_download(download_id, message=resolved_start)
    if on_progress is not None:
        on_progress(resolved_start, None)

    def _progress_message(byte_part: str) -> str:
        if label:
            return _("Downloading: {label} — {byte_part}").format(label=label, byte_part=byte_part)
        return _("Downloading: {byte_part}").format(byte_part=byte_part)

    def _report(message: str, *, fraction: float | None | object = ...) -> None:
        resolved = None if fraction is ... else fraction
        update_model_download(download_id, message=message, fraction=fraction)
        if on_progress is not None:
            on_progress(message, resolved)

    class ProgressTqdm(orig_tqdm):
        monitor_interval = 0

        def update(self, n=1):
            result = super().update(n)
            if self.total:
                fraction = min(1.0, self.n / self.total)
                byte_part = f"{_format_download_bytes(self.n)}/{_format_download_bytes(self.total)}"
            else:
                fraction = None
                byte_part = _format_download_bytes(self.n)
            _report(_progress_message(byte_part), fraction=fraction)
            return result

        def close(self):
            return super().close()

    original_tqdm = tqdm_module.tqdm
    tqdm_module.tqdm = ProgressTqdm
    captured_stdout = _DownloadStdoutCapture(sys.stdout, lambda line: _report(line))
    saved_stdout = sys.stdout
    sys.stdout = captured_stdout
    try:
        yield
    finally:
        sys.stdout = saved_stdout
        captured_stdout.flush()
        tqdm_module.tqdm = original_tqdm
        if manage_lifecycle:
            end_model_download(download_id)
