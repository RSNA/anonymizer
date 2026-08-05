"""Thread-safe download progress for AI feature model downloads."""

from __future__ import annotations

import contextlib
import io
import sys
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterator

if TYPE_CHECKING:
    from anonymizer.controller.tseg.runtime_status import TsWeightKind

FEATURE_KEYS = frozenset({"remove_pixel_phi", "enable_harmonize", "enable_face_blur"})

_TS_KIND_TO_KEY: dict[str, str] = {
    "anatomy": "enable_harmonize",
    "face": "enable_face_blur",
}

_lock = threading.Lock()
_progress: dict[str, DownloadProgress] = {}


@dataclass(frozen=True)
class DownloadProgress:
    message: str = ""
    fraction: float | None = None


def begin_download(key: str, *, message: str = "") -> None:
    with _lock:
        _progress[key] = DownloadProgress(message=message or "Downloading…", fraction=None)


def update_download(
    key: str,
    *,
    message: str | None = None,
    fraction: float | None | object = ...,
) -> None:
    with _lock:
        current = _progress.get(key)
        if current is None:
            return
        new_message = current.message if message is None else message
        new_fraction = current.fraction if fraction is ... else fraction
        _progress[key] = DownloadProgress(message=new_message, fraction=new_fraction)


def end_download(key: str) -> None:
    with _lock:
        _progress.pop(key, None)


def get_download_progress(key: str) -> DownloadProgress | None:
    with _lock:
        return _progress.get(key)


def is_download_active(key: str) -> bool:
    return get_download_progress(key) is not None


def any_download_active() -> bool:
    with _lock:
        return bool(_progress)


def _format_bytes(num: float) -> str:
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


def _sync_ts_weight_detail(kind: TsWeightKind, detail: str) -> None:
    from anonymizer.controller.tseg.runtime_status import update_weight_download_detail

    update_weight_download_detail(kind, detail)


class _StdoutCapture(io.TextIOBase):
    """Forward stdout while forwarding stripped lines to a progress callback."""

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
def track_segmentation_download(kind: TsWeightKind, *, task_id: int | None = None) -> Iterator[None]:
    """Capture TotalSegmentator weight download progress for one AI feature."""
    import totalsegmentator.libs as ts_libs
    from tqdm import tqdm as orig_tqdm

    key = _TS_KIND_TO_KEY[kind.value]
    start_message = f"Downloading model for Task {task_id} ..." if task_id is not None else "Downloading…"
    begin_download(key, message=start_message)
    _sync_ts_weight_detail(kind, start_message)

    def _report(message: str, *, fraction: float | None | object = ...) -> None:
        update_download(key, message=message, fraction=fraction)
        _sync_ts_weight_detail(kind, message)

    class ProgressTqdm(orig_tqdm):
        monitor_interval = 0

        def update(self, n=1):
            result = super().update(n)
            if self.total:
                fraction = min(1.0, self.n / self.total)
                message = f"Downloading: {_format_bytes(self.n)}/{_format_bytes(self.total)}"
            else:
                fraction = None
                message = f"Downloading: {_format_bytes(self.n)}"
            _report(message, fraction=fraction)
            return result

        def close(self):
            return super().close()

    original_tqdm = ts_libs.tqdm
    ts_libs.tqdm = ProgressTqdm
    captured_stdout = _StdoutCapture(sys.stdout, _report)
    saved_stdout = sys.stdout
    sys.stdout = captured_stdout
    try:
        yield
    finally:
        sys.stdout = saved_stdout
        captured_stdout.flush()
        ts_libs.tqdm = original_tqdm
        end_download(key)
