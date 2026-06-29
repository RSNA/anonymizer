"""TotalSegmentator segmentation, anatomy regions, and series analysis entry point."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import SimpleITK as sitk
from pydicom import dcmread

from anonymizer.controller.tseg.config import (
    BODY_PARTS,
    ENABLE_TS_CONTRAST,
    MIN_DICOM_SLICES,
    MIN_REGION_FRACTION,
    MIN_STRUCTURE_VOXELS,
    ROI_SUBSET,
    SEGMENTATION_MODE,
    TSEG_CACHE_DIRNAME,
)
from anonymizer.controller.tseg.contrast import (
    ContrastResult,
    analyze_contrast_phase,
    load_contrast_statistics,
    log_memory_usage,
    release_before_contrast,
    release_working_memory,
)
from anonymizer.controller.tseg.radlex import format_radlex_ct_series_description
from anonymizer.controller.tseg.runtime import sequential_ml_context

logger = logging.getLogger(__name__)

# Rough wall time for TotalSegmentator 3 mm on Apple Silicon (~272 axial slices, incl. model load).
_SEG_SECONDS_PER_SLICE = 0.11
_SEG_BASE_SECONDS = 30.0
_CONTRAST_ESTIMATE_SECONDS = 35.0


@dataclass(frozen=True)
class AnalysisProgress:
    stage: str
    message: str
    fraction: float
    elapsed_sec: float
    remaining_sec: float | None = None


ProgressCallback = Callable[[AnalysisProgress], None]

STRUCTURE_TO_REGION: dict[str, str] = {
    "brain": "Head",
    "skull": "Head",
    "spinal_cord": "Head",
    "lung_upper_lobe_left": "Chest",
    "lung_lower_lobe_left": "Chest",
    "lung_upper_lobe_right": "Chest",
    "lung_middle_lobe_right": "Chest",
    "lung_lower_lobe_right": "Chest",
    "heart": "Chest",
    "trachea": "Chest",
    "esophagus": "Chest",
    "liver": "Abdomen",
    "spleen": "Abdomen",
    "kidney_left": "Abdomen",
    "kidney_right": "Abdomen",
    "stomach": "Abdomen",
    "pancreas": "Abdomen",
    "gallbladder": "Abdomen",
    "colon": "Abdomen",
    "small_bowel": "Abdomen",
    "urinary_bladder": "Abdomen",
    "hip_left": "Abdomen",
    "hip_right": "Abdomen",
    "sacrum": "Abdomen",
}


@dataclass(frozen=True)
class RegionResult:
    dominant_region: str
    region_voxels: dict[str, int]
    structures_present: dict[str, int]
    region_fraction: float


@dataclass(frozen=True)
class TS_result:
    series_directory: Path
    dominant_region: str
    body_parts_present: str
    multi_region: bool
    region_fraction: float
    iv_contrast: bool
    contrast_phase: str
    phase_probability: float
    radlex_series_description: str
    error: str | None = None


def _looks_like_dicom(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".dcm") or name.endswith(".dicom") or "." not in path.name


def sorted_dicom_paths(series_directory: Path) -> list[Path]:
    paths = [
        path
        for path in series_directory.iterdir()
        if path.is_file() and not path.name.startswith(".") and _looks_like_dicom(path)
    ]
    if not paths:
        raise ValueError(f"No DICOM files found in {series_directory}")
    return sorted(
        paths,
        key=lambda path: float(dcmread(path, stop_before_pixels=True).ImagePositionPatient[2]),
    )


def dicom_series_to_nifti(series_directory: Path, output_path: Path) -> int:
    """Convert one DICOM series directory to NIfTI. Returns slice count."""
    series_directory = series_directory.resolve()
    slice_paths = sorted_dicom_paths(series_directory)
    n_slices = len(slice_paths)
    if n_slices < MIN_DICOM_SLICES:
        raise ValueError(f"Need at least {MIN_DICOM_SLICES} DICOM slices, got {n_slices}")

    reader = sitk.ImageSeriesReader()
    reader.SetFileNames([str(path) for path in slice_paths])
    image = reader.Execute()
    try:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sitk.WriteImage(image, str(output_path))
    finally:
        del image
        del reader
    return n_slices


def _require_totalsegmentator():
    try:
        from totalsegmentator.python_api import totalsegmentator
    except ImportError as exc:
        raise ImportError(
            'TotalSegmentator is required for anatomy analysis. Install with: pip install "rsna-anonymizer[tseg]"'
        ) from exc
    return totalsegmentator


def resolve_device(device: str | None) -> str:
    import torch

    if device:
        return device
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "gpu"
    return "cpu"


def count_mask_voxels(mask_path: Path) -> int:
    image = sitk.ReadImage(str(mask_path))
    try:
        array = sitk.GetArrayFromImage(image)
        return int((array > 0).sum())
    finally:
        del image


def collect_structure_voxels(segmentation_dir: Path, structures: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for structure in structures:
        mask_path = segmentation_dir / f"{structure}.nii.gz"
        if not mask_path.is_file():
            counts[structure] = 0
            continue
        counts[structure] = count_mask_voxels(mask_path)
    return counts


def region_from_structure(name: str) -> str | None:
    return STRUCTURE_TO_REGION.get(name)


def dominant_region_from_voxels(
    structure_voxels: dict[str, int],
    *,
    min_voxels: int = MIN_STRUCTURE_VOXELS,
) -> RegionResult:
    """Pick the region with the largest summed structure voxel count."""
    region_voxels = {region: 0 for region in BODY_PARTS}
    structures_present: dict[str, int] = {}

    for structure, count in structure_voxels.items():
        if count < min_voxels:
            continue
        region = region_from_structure(structure)
        if region is None:
            continue
        structures_present[structure] = count
        region_voxels[region] += count

    ranked = sorted(region_voxels.items(), key=lambda item: (-item[1], BODY_PARTS.index(item[0])))
    top_region, top_count = ranked[0]
    second_count = ranked[1][1]
    total = sum(region_voxels.values())

    if total == 0:
        return RegionResult(
            dominant_region="",
            region_voxels=region_voxels,
            structures_present=structures_present,
            region_fraction=0.0,
        )

    dominant_region = top_region if top_count > 0 else ""
    region_fraction = float(top_count / total) if dominant_region else 0.0
    if dominant_region and top_count == second_count:
        region_fraction = 0.5

    return RegionResult(
        dominant_region=dominant_region,
        region_voxels=region_voxels,
        structures_present=structures_present,
        region_fraction=region_fraction,
    )


def body_parts_present(
    region_voxels: dict[str, int],
    *,
    min_fraction: float = MIN_REGION_FRACTION,
    min_voxels: int = MIN_STRUCTURE_VOXELS,
) -> str:
    """Regions with substantial voxel mass, joined as e.g. ``Chest+Abdomen``."""
    total = sum(region_voxels.values())
    if total == 0:
        return ""
    present = [
        region
        for region in BODY_PARTS
        if region_voxels.get(region, 0) >= min_voxels
        and region_voxels[region] / total >= min_fraction
    ]
    return "+".join(present)


def is_multi_region(body_parts_present_label: str) -> bool:
    return "+" in body_parts_present_label


def _estimate_segmentation_seconds(n_slices: int) -> float:
    return _SEG_BASE_SECONDS + n_slices * _SEG_SECONDS_PER_SLICE


def _report_progress(
    callback: ProgressCallback | None,
    *,
    stage: str,
    message: str,
    fraction: float,
    started: float,
    remaining_sec: float | None = None,
) -> None:
    if callback is None:
        return
    callback(
        AnalysisProgress(
            stage=stage,
            message=message,
            fraction=fraction,
            elapsed_sec=time.perf_counter() - started,
            remaining_sec=remaining_sec,
        )
    )


def run_segmentation(
    nifti_path: Path,
    output_dir: Path,
    *,
    mode: str = SEGMENTATION_MODE,
    device: str | None = None,
    roi_subset: list[str] | None = None,
    progress: ProgressCallback | None = None,
    analysis_started: float | None = None,
    n_slices: int | None = None,
) -> float:
    """Run TotalSegmentator ``total`` task for anatomy regions. Returns inference wall time in seconds."""
    totalsegmentator = _require_totalsegmentator()
    subset = roi_subset or list(ROI_SUBSET)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = analysis_started if analysis_started is not None else time.perf_counter()
    estimate = _estimate_segmentation_seconds(n_slices or 100)

    fast = mode == "3mm"
    fastest = mode == "6mm"
    if mode not in {"3mm", "6mm", "1.5mm"}:
        raise ValueError(f"Unsupported TS mode: {mode!r}")

    kwargs: dict = {
        "task": "total",
        "body_seg": True,
        "roi_subset": subset,
        "device": resolve_device(device),
        "quiet": True,
        "fast": fast,
        "fastest": fastest,
        "nr_thr_resamp": 1,
        "nr_thr_saving": 1,
    }
    if mode == "1.5mm":
        kwargs["fast"] = False
        kwargs["fastest"] = False

    _report_progress(
        progress,
        stage="segment",
        message="Segmenting anatomy",
        fraction=0.12,
        started=started,
        remaining_sec=estimate,
    )

    seg_started = time.perf_counter()
    with sequential_ml_context("ts_segmentation"):
        totalsegmentator(str(nifti_path), str(output_dir), **kwargs)
    release_working_memory(stage="ts_segmentation_end")

    return time.perf_counter() - seg_started


def _error_result(series_directory: Path, error: str) -> TS_result:
    return TS_result(
        series_directory=Path(series_directory),
        dominant_region="",
        body_parts_present="",
        multi_region=False,
        region_fraction=0.0,
        iv_contrast=False,
        contrast_phase="",
        phase_probability=0.0,
        radlex_series_description="",
        error=error,
    )


def series_cache_dir(series_directory: Path) -> Path:
    """Per-series cache under ``<series>/.tseg_cache/`` (NIfTI, seg masks, contrast stats)."""
    return Path(series_directory).resolve() / TSEG_CACHE_DIRNAME


def _segmentation_cache_valid(seg_dir: Path, structures: list[str]) -> bool:
    """True when ROI segmentation masks from a prior run are present."""
    if not seg_dir.is_dir():
        return False
    return any((seg_dir / f"{structure}.nii.gz").is_file() for structure in structures)


def _nifti_slice_count(nifti_path: Path) -> int:
    image = sitk.ReadImage(str(nifti_path))
    return int(image.GetSize()[2])


def _region_ts_result(
    series_directory: Path,
    *,
    region: RegionResult,
    regions_label: str,
) -> TS_result:
    return TS_result(
        series_directory=series_directory,
        dominant_region=region.dominant_region,
        body_parts_present=regions_label,
        multi_region=is_multi_region(regions_label),
        region_fraction=region.region_fraction,
        iv_contrast=False,
        contrast_phase="",
        phase_probability=0.0,
        radlex_series_description="",
    )


def analyze_tseg_regions(
    series_directory: Path,
    *,
    progress: ProgressCallback | None = None,
) -> tuple[TS_result, Path | None]:
    """
    DICOM→NIfTI, TotalSegmentator ROI segmentation, and region summary.

    Intermediate artifacts are cached under ``<series_directory>/.tseg_cache/`` and
    reused when present. Returns ``(result, nifti_path)``. Contrast fields on
    ``result`` are empty when regions succeeded; contrast uses a separate pass.
    """
    series_directory = Path(series_directory)
    work_dir = series_cache_dir(series_directory)
    work_dir.mkdir(parents=True, exist_ok=True)
    nifti_path = work_dir / "volume.nii.gz"
    seg_dir = work_dir / "seg"
    analysis_started = time.perf_counter()

    logger.info("TS regions: starting for %s (cache=%s)", series_directory, work_dir)
    log_memory_usage("ts_regions_start")

    with sequential_ml_context("ts_regions"):
        try:
            _report_progress(
                progress,
                stage="prepare",
                message="Preparing CT volume",
                fraction=0.05,
                started=analysis_started,
            )
            if nifti_path.is_file():
                n_slices = _nifti_slice_count(nifti_path)
                logger.info("TS regions: reusing cached NIfTI %s (%d slices)", nifti_path, n_slices)
            else:
                logger.info("TS regions: converting DICOM to NIfTI: %s", series_directory)
                n_slices = dicom_series_to_nifti(series_directory, nifti_path)
                release_working_memory(stage="ts_regions_after_dicom_to_nifti")
                logger.info("TS regions: wrote %s (%d slices)", nifti_path, n_slices)

            roi_structures = list(ROI_SUBSET)
            if _segmentation_cache_valid(seg_dir, roi_structures):
                logger.info("TS regions: reusing cached segmentation in %s", seg_dir)
            else:
                logger.info("TS regions: running segmentation for %s", series_directory)
                seg_seconds = run_segmentation(
                    nifti_path,
                    seg_dir,
                    progress=progress,
                    analysis_started=analysis_started,
                    n_slices=n_slices,
                )
                logger.info("TS regions: segmentation finished in %.1fs", seg_seconds)
                release_working_memory(stage="ts_regions_after_segmentation")

            _report_progress(
                progress,
                stage="regions",
                message="Summarizing anatomy regions",
                fraction=0.72,
                started=analysis_started,
            )
            structure_voxels = collect_structure_voxels(seg_dir, list(ROI_SUBSET))
            region = dominant_region_from_voxels(structure_voxels)
            regions_label = body_parts_present(region.region_voxels)
            del structure_voxels

            if not regions_label:
                logger.warning("TS regions: no anatomy regions detected for %s", series_directory)
                return (
                    _error_result(series_directory, "No anatomy regions detected in volume"),
                    nifti_path,
                )

            logger.info(
                "TS regions: %s dominant=%s label=%s fraction=%.3f",
                series_directory,
                region.dominant_region,
                regions_label,
                region.region_fraction,
            )
            return (
                _region_ts_result(series_directory, region=region, regions_label=regions_label),
                nifti_path,
            )
        except Exception as exc:
            logger.exception("TS regions failed for %s: %s", series_directory, exc)
            return (_error_result(series_directory, f"{type(exc).__name__}: {exc}"), None)
        finally:
            release_working_memory(stage="ts_regions_end")


def analyze_tseg_contrast(
    series_directory: Path,
    nifti_path: Path,
    region_result: TS_result,
    *,
    progress: ProgressCallback | None = None,
) -> TS_result:
    """
    Run TotalSegmentator organ HU statistics + XGBoost contrast-phase classification.

    Contrast organ statistics are cached under ``<series>/.tseg_cache/contrast_stats.json``.
    """
    series_directory = Path(series_directory)
    analysis_started = time.perf_counter()

    if not region_result.body_parts_present.strip():
        return region_result

    release_before_contrast(stage="ts_contrast_after_anatomy_release")

    _report_progress(
        progress,
        stage="contrast",
        message="Analyzing contrast phase",
        fraction=0.78,
        started=analysis_started,
        remaining_sec=_CONTRAST_ESTIMATE_SECONDS,
    )
    logger.info("TS contrast: starting for %s (volume=%s)", series_directory, nifti_path)
    log_memory_usage("ts_contrast_before_load")

    existing_stats = None
    contrast_stats_path = series_cache_dir(series_directory) / "contrast_stats.json"
    if contrast_stats_path.is_file():
        existing_stats = load_contrast_statistics(contrast_stats_path)
        logger.info("TS contrast: loaded cached contrast statistics from %s", contrast_stats_path)

    try:
        with sequential_ml_context("ts_contrast_pipeline"):
            contrast = analyze_contrast_phase(
                nifti_path,
                existing_stats=existing_stats,
                stats_output_path=contrast_stats_path if existing_stats is None else None,
            )
        radlex_description = format_radlex_ct_series_description(
            region_result.body_parts_present,
            contrast.iv_contrast,
        )
        _report_progress(
            progress,
            stage="done",
            message="Anatomy analysis complete",
            fraction=0.9,
            started=analysis_started,
            remaining_sec=0.0,
        )
        return TS_result(
            series_directory=series_directory,
            dominant_region=region_result.dominant_region,
            body_parts_present=region_result.body_parts_present,
            multi_region=region_result.multi_region,
            region_fraction=region_result.region_fraction,
            iv_contrast=contrast.iv_contrast,
            contrast_phase=contrast.phase,
            phase_probability=contrast.probability,
            radlex_series_description=radlex_description,
        )
    except Exception as contrast_exc:
        logger.exception("TS contrast failed for %s: %s", series_directory, contrast_exc)
        return TS_result(
            series_directory=series_directory,
            dominant_region=region_result.dominant_region,
            body_parts_present=region_result.body_parts_present,
            multi_region=region_result.multi_region,
            region_fraction=region_result.region_fraction,
            iv_contrast=False,
            contrast_phase="",
            phase_probability=0.0,
            radlex_series_description="",
            error=f"{type(contrast_exc).__name__}: {contrast_exc}",
        )
    finally:
        release_working_memory(stage="ts_contrast_pipeline_end")


def analyze_series(
    series_directories: list[Path],
    *,
    progress: ProgressCallback | None = None,
) -> list[TS_result]:
    """
    Run TotalSegmentator anatomy and XGBoost contrast analysis on CT series directories.
    """
    if not series_directories:
        logger.error("No series directories provided for anatomy analysis.")
        return []

    logger.info("Anatomy analysis starting for %d series", len(series_directories))
    results: list[TS_result] = []

    for series_dir in series_directories:
        series_dir = Path(series_dir)
        region_result, nifti_path = analyze_tseg_regions(series_dir, progress=progress)
        if (
            ENABLE_TS_CONTRAST
            and nifti_path is not None
            and region_result.body_parts_present.strip()
            and region_result.error is None
        ):
            results.append(
                analyze_tseg_contrast(
                    series_dir,
                    nifti_path,
                    region_result,
                    progress=progress,
                )
            )
        else:
            if not ENABLE_TS_CONTRAST and region_result.body_parts_present.strip():
                logger.info("TS contrast skipped (ENABLE_TS_CONTRAST=False) for %s", series_dir)
            results.append(region_result)

    logger.info("Anatomy analysis finished: %d result(s)", len(results))
    return results
