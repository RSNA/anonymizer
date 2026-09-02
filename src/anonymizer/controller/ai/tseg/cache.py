"""TotalSegmentator / harmonize per-series cache directory helpers."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from anonymizer.controller.ai.tseg.config import TSEG_CACHE_DIRNAME

logger = logging.getLogger(__name__)


def resolve_series_cache_dir(series_directory: Path) -> Path:
    """Return the TS cache directory for a series (``0_TS_SEG/`` at the series root)."""
    return Path(series_directory).resolve() / TSEG_CACHE_DIRNAME


@dataclass(frozen=True)
class TsegCacheSummary:
    path: Path
    exists: bool
    file_count: int
    size_bytes: int


def _measure_tree(directory: Path) -> tuple[int, int]:
    file_count = 0
    size_bytes = 0
    for path in directory.rglob("*"):
        if path.is_file():
            file_count += 1
            try:
                size_bytes += path.stat().st_size
            except OSError:
                continue
    return file_count, size_bytes


def tseg_cache_summary(series_directory: Path) -> TsegCacheSummary:
    """Summarize the on-disk TS cache for a series."""
    cache_dir = resolve_series_cache_dir(series_directory)
    if cache_dir.is_dir():
        file_count, size_bytes = _measure_tree(cache_dir)
        return TsegCacheSummary(
            path=cache_dir,
            exists=True,
            file_count=file_count,
            size_bytes=size_bytes,
        )
    return TsegCacheSummary(
        path=cache_dir,
        exists=False,
        file_count=0,
        size_bytes=0,
    )


def clear_tseg_series_cache(series_directory: Path) -> bool:
    """
    Remove harmonize / TotalSegmentator cache for a series.

    Does not modify DICOM images or series metadata. Returns True when a cache dir was removed.
    """
    cache_dir = resolve_series_cache_dir(series_directory)
    if not cache_dir.is_dir():
        return False
    shutil.rmtree(cache_dir)
    logger.info("Cleared TS cache at %s", cache_dir)
    return True


def clear_series_tseg_cache(
    series_directory: Path,
    *,
    anon_model=None,
    anon_series_uid: str | None = None,
) -> bool:
    """
    Remove on-disk TS cache and clear harmonize metadata in the project database.

    Face blur records and pixel PHI instance metadata are not changed.
    """
    removed = clear_tseg_series_cache(series_directory)
    if anon_model is not None and anon_series_uid:
        anon_model.clear_series_tseg_metadata(anon_series_uid)
    return removed
