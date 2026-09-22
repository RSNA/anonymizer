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


def clear_tseg_series_cache(
    series_directory: Path,
    *,
    also_clear_annotations: bool = False,
) -> bool:
    """
    Remove harmonize / TotalSegmentator cache for a series.

    By default preserves ``annotations/`` (user ROI labels and TS edits). Pass
    ``also_clear_annotations=True`` to delete the entire cache tree.

    Does not modify DICOM images or series metadata. Returns True when anything was removed.
    """
    from anonymizer.controller.annotations.store import ANNOTATIONS_DIRNAME

    cache_dir = resolve_series_cache_dir(series_directory)
    if not cache_dir.is_dir():
        return False
    if also_clear_annotations:
        shutil.rmtree(cache_dir)
        logger.info("Cleared TS cache (including annotations) at %s", cache_dir)
        return True

    removed_any = False
    for child in list(cache_dir.iterdir()):
        if child.name == ANNOTATIONS_DIRNAME:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)
        removed_any = True
    # Drop empty cache dir only when annotations were also gone.
    if not any(cache_dir.iterdir()):
        cache_dir.rmdir()
    if removed_any:
        logger.info("Cleared TS cache (kept annotations/) at %s", cache_dir)
    return removed_any


def clear_series_tseg_cache(
    series_directory: Path,
    *,
    anon_model=None,
    anon_series_uid: str | None = None,
    also_clear_annotations: bool = False,
) -> bool:
    """
    Remove on-disk TS cache and clear harmonize metadata in the project database.

    Face blur records and pixel PHI instance metadata are not changed.
    User ROI ``annotations/`` are preserved unless ``also_clear_annotations`` is True.
    """
    removed = clear_tseg_series_cache(
        series_directory, also_clear_annotations=also_clear_annotations
    )
    if anon_model is not None and anon_series_uid:
        anon_model.clear_series_tseg_metadata(anon_series_uid)
    return removed
