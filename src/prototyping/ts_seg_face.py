#!/usr/bin/env python3
"""
Run TotalSegmentator ``face`` on one CT DICOM series directory.

Usage::

    uv run python src/prototyping/ts_seg_face.py /path/to/ct_head_series

Writes ``<series>/ts_seg/face.nii.gz`` only. DICOM is converted to a temporary
NIfTI for inference (TotalSegmentator requires a volume file path), then removed.

Requires ``uv sync --extra tseg`` and an academic license (``aca_*``, 18 chars)::

    uv run totalseg_set_license -l aca_XXXXXXXXXXXXXX

Licensed weights (Dataset303) download on first run. See:
https://backend.totalsegmentator.com/license-academic/
"""

from __future__ import annotations

import logging
import sys
import tempfile
import time
from pathlib import Path

import SimpleITK as sitk

from anonymizer.controller.tseg.dicom_geometry import sorted_dicom_paths
from anonymizer.controller.tseg.runtime import sequential_ml_context
from anonymizer.controller.tseg.segment import dicom_series_to_nifti, resolve_device

logger = logging.getLogger("ts_seg_face")


def _configure_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _require_totalsegmentator():
    try:
        from totalsegmentator.python_api import totalsegmentator
    except ImportError as exc:
        raise ImportError(
            'TotalSegmentator is required. Install with: uv sync --extra tseg'
        ) from exc
    return totalsegmentator


def count_mask_voxels(mask_path: Path) -> int:
    image = sitk.ReadImage(str(mask_path))
    try:
        array = sitk.GetArrayFromImage(image)
        return int((array > 0).sum())
    finally:
        del image


def run_face_segmentation(nifti_path: Path, output_dir: Path, *, device: str) -> tuple[Path, float]:
    """Run licensed TS ``face`` task. Returns ``(face.nii.gz path, inference seconds)``."""
    totalsegmentator = _require_totalsegmentator()
    output_dir.mkdir(parents=True, exist_ok=True)
    face_path = output_dir / "face.nii.gz"

    logger.info("TotalSegmentator face task starting (device=%s)", device)
    logger.info("  input volume: %s", nifti_path)
    logger.info("  output dir:   %s", output_dir)

    seg_started = time.perf_counter()
    with sequential_ml_context("ts_seg_face"):
        totalsegmentator(
            str(nifti_path),
            str(output_dir),
            task="face",
            fast=False,
            fastest=False,
            quiet=False,
            device=device,
            nr_thr_resamp=1,
            nr_thr_saving=1,
        )
    seg_seconds = time.perf_counter() - seg_started

    if not face_path.is_file():
        raise FileNotFoundError(f"TotalSegmentator did not write {face_path}")

    logger.info("TotalSegmentator face task finished in %.1fs", seg_seconds)
    return face_path, seg_seconds


def segment_face(series_directory: Path) -> tuple[Path, int, int, float]:
    """
    DICOM → temp NIfTI → face segmentation → ``ts_seg/face.nii.gz``.

    Returns ``(face_mask_path, slice_count, face_voxel_count, inference_seconds)``.
    """
    series_directory = series_directory.resolve()
    if not series_directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {series_directory}")

    output_dir = series_directory / "ts_seg"
    device = resolve_device(None)
    slice_paths = sorted_dicom_paths(series_directory)

    logger.info("Series directory: %s", series_directory)
    logger.info("DICOM instances (stack order): %d", len(slice_paths))
    logger.info("Output directory: %s", output_dir)
    logger.info("Resolved inference device: %s", device)

    with tempfile.TemporaryDirectory(prefix="ts_seg_face_") as tmp:
        nifti_path = Path(tmp) / "volume.nii.gz"
        logger.info("Converting DICOM series to temporary NIfTI …")
        convert_started = time.perf_counter()
        n_slices = dicom_series_to_nifti(series_directory, nifti_path)
        convert_seconds = time.perf_counter() - convert_started
        logger.info(
            "Temporary NIfTI ready: %s (%d slices, %.1fs); removed after inference",
            nifti_path,
            n_slices,
            convert_seconds,
        )

        face_path, seg_seconds = run_face_segmentation(nifti_path, output_dir, device=device)

    voxels = count_mask_voxels(face_path)
    logger.info("Face mask voxels (label > 0): %d", voxels)
    logger.info("Wrote %s", face_path)
    return face_path, n_slices, voxels, seg_seconds


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        logger.error(
            "Usage: uv run python src/prototyping/ts_seg_face.py /path/to/ct_head_series"
        )
        return 2

    series_dir = Path(args[0])
    try:
        sorted_dicom_paths(series_dir)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    total_started = time.perf_counter()
    try:
        face_path, n_slices, voxels, seg_seconds = segment_face(series_dir)
    except SystemExit as exc:
        logger.error(
            "TotalSegmentator exited (missing or invalid license?). "
            "Run: uv run totalseg_set_license -l aca_XXXXXXXXXXXXXX"
        )
        return int(exc.code) if isinstance(exc.code, int) else 1
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
