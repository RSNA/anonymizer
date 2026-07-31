"""TotalSegmentator / harmonize per-series cache directory helpers."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from anonymizer.controller.tseg.config import TSEG_CACHE_DIRNAME

logger = logging.getLogger(__name__)

LEGACY_TSEG_CACHE_DIRNAME = ".tseg_cache"


@dataclass(frozen=True)
class TsegCacheSummary:
    path: Path
    exists: bool
    file_count: int
    size_bytes: int


def resolve_series_cache_dir(series_directory: Path) -> Path:
    """
    Return the TS cache directory for a series, migrating legacy ``.tseg_cache`` when needed.

    New caches are written under ``A_TS_SEG/`` at the series root (visible, sorts first).
    """
    series_directory = Path(series_directory).resolve()
    cache_dir = series_directory / TSEG_CACHE_DIRNAME
    legacy_dir = series_directory / LEGACY_TSEG_CACHE_DIRNAME

    if cache_dir.is_dir():
        return cache_dir

    if legacy_dir.is_dir():
        try:
            legacy_dir.rename(cache_dir)
            logger.info("Migrated TS cache %s -> %s", legacy_dir.name, cache_dir.name)
        except OSError as exc:
            logger.warning("Could not migrate TS cache to %s: %s; using legacy path", cache_dir.name, exc)
            return legacy_dir
        return cache_dir

    return cache_dir


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
    """Summarize the on-disk TS cache for a series (includes legacy dir if not yet migrated)."""
    series_directory = Path(series_directory).resolve()
    cache_dir = resolve_series_cache_dir(series_directory)
    legacy_dir = series_directory / LEGACY_TSEG_CACHE_DIRNAME

    if cache_dir.is_dir():
        file_count, size_bytes = _measure_tree(cache_dir)
        return TsegCacheSummary(
            path=cache_dir,
            exists=True,
            file_count=file_count,
            size_bytes=size_bytes,
        )

    if legacy_dir.is_dir():
        file_count, size_bytes = _measure_tree(legacy_dir)
        return TsegCacheSummary(
            path=legacy_dir,
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
    Remove harmonize / TotalSegmentator cache directories for a series.

    Does not modify DICOM images or series metadata. Returns True when a cache dir was removed.
    """
    series_directory = Path(series_directory).resolve()
    removed = False

    for dirname in (TSEG_CACHE_DIRNAME, LEGACY_TSEG_CACHE_DIRNAME):
        cache_dir = series_directory / dirname
        if not cache_dir.is_dir():
            continue
        shutil.rmtree(cache_dir)
        logger.info("Cleared TS cache at %s", cache_dir)
        removed = True

    return removed


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
