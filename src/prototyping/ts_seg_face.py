#!/usr/bin/env python3
"""
Run TotalSegmentator ``face`` on one CT DICOM series directory via the tseg controller API.

Usage::

    uv sync --extra tseg --group dev
    uv run totalseg_set_license -l aca_XXXXXXXXXXXXXX   # once, academic license
    uv run python src/prototyping/ts_seg_face.py /path/to/ct_head_series
    uv run python src/prototyping/ts_seg_face.py /path/to/ct_head_series --force

Writes ``<series>/A_TS_SEG/seg/face.nii.gz`` (reuses ``A_TS_SEG/volume.nii.gz`` when present).

Licensed weights (Dataset303) download on first run. See:
https://backend.totalsegmentator.com/license-academic/
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from anonymizer.controller.tseg.dicom_geometry import sorted_dicom_paths
from anonymizer.controller.tseg.segment import AnalysisProgress, analyze_tseg_face, face_mask_cache_path

logger = logging.getLogger("ts_seg_face")


def _configure_logging(*, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    logging.getLogger("anonymizer.controller.tseg").setLevel(level)


def _log_progress(event: AnalysisProgress) -> None:
    remaining = ""
    if event.remaining_sec is not None:
        remaining = f" (~{event.remaining_sec:.0f}s left)"
    logger.info(
        "[%s] %s (%.0f%%)%s",
        event.stage,
        event.message,
        event.fraction * 100.0,
        remaining,
    )


def segment_face(series_directory: Path, *, force: bool = False) -> tuple[Path, int, int, float]:
    """
    Thin wrapper around ``analyze_tseg_face`` for scripts and notebooks.

    Returns ``(face_mask_path, slice_count, face_voxel_count, inference_seconds)``.
    """
    result = analyze_tseg_face(series_directory, progress=_log_progress, force=force)
    if result.error is not None:
        raise RuntimeError(result.error)
    assert result.face_mask_path is not None
    return (
        result.face_mask_path,
        result.slice_count,
        result.face_voxel_count,
        result.inference_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run TotalSegmentator face segmentation on a CT head DICOM series directory.",
    )
    parser.add_argument(
        "series_directory",
        type=Path,
        help="Directory containing one axial CT series (*.dcm)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run face segmentation even when A_TS_SEG/seg/face.nii.gz exists",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)
    _configure_logging(verbose=args.verbose)

    series_dir = args.series_directory.resolve()
    if not series_dir.is_dir():
        logger.error("Not a directory: %s", series_dir)
        return 2

    try:
        slice_paths = sorted_dicom_paths(series_dir)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    logger.info("Series directory: %s", series_dir)
    logger.info("DICOM instances (stack order): %d", len(slice_paths))
    logger.info("Face mask cache: %s", face_mask_cache_path(series_dir))

    total_started = time.perf_counter()
    try:
        face_path, n_slices, voxels, seg_seconds = segment_face(series_dir, force=args.force)
    except RuntimeError as exc:
        logger.error("%s", exc)
        if "academic license" in str(exc).lower():
            logger.error("Run: uv run totalseg_set_license -l aca_XXXXXXXXXXXXXX")
        return 1
    except Exception as exc:
        logger.exception("Face segmentation failed: %s", exc)
        return 1

    total_seconds = time.perf_counter() - total_started
    logger.info(
        "Done. slices=%d face_voxels=%d inference=%.1fs total=%.1fs",
        n_slices,
        voxels,
        seg_seconds,
        total_seconds,
    )
    print(f"face_mask={face_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
