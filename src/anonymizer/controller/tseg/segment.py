"""TotalSegmentator segmentation, anatomy regions, and series analysis entry point."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import SimpleITK as sitk

from anonymizer.controller.series_io import load_series_frames
from anonymizer.controller.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.tseg.config import (
    BODY_PARTS,
    CONTRAST_PHASE_CACHE_FILENAME,
    CONTRAST_STATS_FILENAME,
    CONTRAST_STATS_HN_FILENAME,
    ENABLE_TS_CONTRAST,
    ENABLE_TSEG_FACE,
    FACE_MASK_FILENAME,
    FACE_TASK,
    MIN_DICOM_SLICES,
    MIN_REGION_FRACTION,
    MIN_STRUCTURE_VOXELS,
    ROI_SUBSET,
    SEGMENTATION_MODE,
)
from anonymizer.controller.tseg.contrast import (
    ContrastProgressCallback,
    analyze_contrast_phase,
    contrast_phase_cache_is_valid,
    estimate_contrast_remaining_sec,
    load_contrast_statistics,
    log_memory_usage,
    needs_head_neck_vessel_stats,
    release_before_contrast,
    release_working_memory,
)
from anonymizer.controller.tseg.dicom_geometry import (
    SeriesGeometryResult,
    build_sitk_volume_from_series_frames,
    resolve_series_geometry,
    stackable_dicom_paths,
    ts_regions_eligible,
)
from anonymizer.controller.tseg.radlex import format_radlex_ct_series_description
from anonymizer.controller.tseg.runtime import sequential_ml_context
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

# Rough wall time for TotalSegmentator 3 mm on Apple Silicon (~272 axial slices, incl. model load).
_SEG_SECONDS_PER_SLICE = 0.11
_SEG_BASE_SECONDS = 30.0
_FACE_SEG_ESTIMATE_SECONDS = 90.0
_FACE_LICENSE_ERROR = "TotalSegmentator face task requires academic license (totalseg_set_license -l aca_...)"


@dataclass(frozen=True)
class AnalysisProgress:
    stage: str
    message: str
    fraction: float
    elapsed_sec: float
    remaining_sec: float | None = None
    geometry: SeriesGeometryResult | None = None
    tseg: TS_result | None = None
    radlex_series_description: str | None = None


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
    structures_present: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def format_anatomy_regions_summary(result: TS_result) -> str:
    """Compact anatomy summary for batch progress when segmentation cache is reused."""
    regions = result.body_parts_present.replace("+", ", ")
    if not regions:
        return ""
    if result.dominant_region:
        return f"{regions} ({_('dominant')}: {result.dominant_region})"
    return regions


def format_anatomy_regions_progress_message(result: TS_result, *, seg_cached: bool) -> str:
    summary = format_anatomy_regions_summary(result)
    if not summary:
        return _("Summarizing anatomy regions")
    prefix = _("Anatomy (cached segmentation)") if seg_cached else _("Anatomy")
    return f"{prefix}: {summary}"


@dataclass(frozen=True)
class FaceSegResult:
    series_directory: Path
    face_mask_path: Path | None
    slice_count: int
    face_voxel_count: int
    inference_seconds: float
    error: str | None = None


def dicom_series_to_nifti(series_directory: Path, output_path: Path) -> int:
    """Convert one DICOM series directory to NIfTI. Returns slice count."""
    series_directory = series_directory.resolve()
    loaded = load_series_frames(series_directory)
    reference_ds, frames, slice_paths = loaded.metadata, loaded.frames, loaded.slice_paths
    n_slices = len(slice_paths)
    if n_slices < MIN_DICOM_SLICES:
        raise ValueError(f"Need at least {MIN_DICOM_SLICES} DICOM slices, got {n_slices}")

    image = build_sitk_volume_from_series_frames(reference_ds, frames, slice_paths)
    try:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sitk.WriteImage(image, str(output_path))
    finally:
        del image
    return n_slices


def _require_totalsegmentator():
    try:
        from totalsegmentator.python_api import totalsegmentator
    except ImportError as exc:
        raise ImportError(
            "TotalSegmentator is required for anatomy analysis. Install with: pip install rsna-anonymizer"
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
        if region_voxels.get(region, 0) >= min_voxels and region_voxels[region] / total >= min_fraction
    ]
    return "+".join(present)


def is_multi_region(body_parts_present_label: str) -> bool:
    return "+" in body_parts_present_label


def cached_body_parts_label(series_directory: Path) -> str | None:
    """ROI anatomy label from ``A_TS_SEG`` segmentation cache, if available."""
    cache_dir = series_cache_dir(series_directory)
    seg_dir = cache_dir / "seg"
    structures = list(ROI_SUBSET)
    if not _segmentation_cache_valid(seg_dir, structures):
        return None
    structure_voxels = collect_structure_voxels(seg_dir, structures)
    region = dominant_region_from_voxels(structure_voxels)
    label = body_parts_present(region.region_voxels)
    return label or None


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


def _wrap_contrast_progress(
    callback: ProgressCallback | None,
    *,
    started: float,
    remaining_sec: float | None,
) -> ContrastProgressCallback | None:
    if callback is None:
        return None

    def wrapped(stage: str, message: str, fraction: float) -> None:
        _report_progress(
            callback,
            stage=stage,
            message=message,
            fraction=fraction,
            started=started,
            remaining_sec=remaining_sec,
        )

    return wrapped


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


def run_face_segmentation(
    nifti_path: Path,
    output_dir: Path,
    *,
    device: str | None = None,
    progress: ProgressCallback | None = None,
    analysis_started: float | None = None,
) -> float:
    """Run TotalSegmentator ``face`` task. Returns inference wall time in seconds."""
    totalsegmentator = _require_totalsegmentator()
    output_dir.mkdir(parents=True, exist_ok=True)
    face_path = output_dir / FACE_MASK_FILENAME
    started = analysis_started if analysis_started is not None else time.perf_counter()

    _report_progress(
        progress,
        stage="face_segment",
        message="Segmenting face mask",
        fraction=0.15,
        started=started,
        remaining_sec=_FACE_SEG_ESTIMATE_SECONDS,
    )

    seg_started = time.perf_counter()
    with sequential_ml_context("ts_face_segmentation"):
        totalsegmentator(
            str(nifti_path),
            str(output_dir),
            task=FACE_TASK,
            fast=False,
            fastest=False,
            quiet=True,
            device=resolve_device(device),
            nr_thr_resamp=1,
            nr_thr_saving=1,
        )
    release_working_memory(stage="ts_face_segmentation_end")

    if not face_path.is_file():
        raise FileNotFoundError(f"TotalSegmentator did not write {face_path}")

    return time.perf_counter() - seg_started


def analyze_tseg_face(
    series_directory: Path,
    *,
    progress: ProgressCallback | None = None,
    force: bool = False,
) -> FaceSegResult:
    """
    DICOM→NIfTI, TotalSegmentator ``face`` task, and cached face mask path.

    Reuses ``<series_directory>/.tseg_cache/volume.nii.gz`` when present (same as
    anatomy regions). Face mask is cached at ``seg/face.nii.gz``.
    """
    series_directory = Path(series_directory)
    if not ENABLE_TSEG_FACE:
        return _face_error_result(
            series_directory,
            "Face segmentation is disabled (ENABLE_TSEG_FACE=False)",
        )

    work_dir = series_cache_dir(series_directory)
    work_dir.mkdir(parents=True, exist_ok=True)
    nifti_path = work_dir / "volume.nii.gz"
    seg_dir = work_dir / "seg"
    mask_path = face_mask_cache_path(series_directory)
    analysis_started = time.perf_counter()

    geometry = resolve_series_geometry(series_directory)
    logger.info(
        "TS face: geometry plane=%s dimensionality=%s provenance=%s ts_suitable=%s",
        geometry.plane,
        geometry.dimensionality,
        geometry.provenance,
        geometry.ts_suitable,
    )
    if not ts_regions_eligible(geometry):
        message = geometry.notes or f"Series not suitable for TotalSegmentator ({geometry.dimensionality})"
        logger.info("TS face: skipped for %s (%s)", series_directory, message)
        return _face_error_result(series_directory, message)

    logger.info("TS face: starting for %s (cache=%s)", series_directory, work_dir)
    log_memory_usage("ts_face_start")
    invalidate_stale_tseg_volume_cache(series_directory, nifti_path, face_mask_path=mask_path)

    try:
        with sequential_ml_context("ts_face"):
            _report_progress(
                progress,
                stage="prepare",
                message="Preparing CT volume",
                fraction=0.05,
                started=analysis_started,
            )
            if nifti_path.is_file():
                n_slices = _nifti_slice_count(nifti_path)
                logger.info("TS face: reusing cached NIfTI %s (%d slices)", nifti_path, n_slices)
            else:
                logger.info("TS face: converting DICOM to NIfTI: %s", series_directory)
                n_slices = dicom_series_to_nifti(series_directory, nifti_path)
                release_working_memory(stage="ts_face_after_dicom_to_nifti")
                logger.info("TS face: wrote %s (%d slices)", nifti_path, n_slices)

            inference_seconds = 0.0
            if _face_cache_valid(mask_path) and not force:
                logger.info("TS face: reusing cached mask %s", mask_path)
            else:
                logger.info("TS face: running face segmentation for %s", series_directory)
                inference_seconds = run_face_segmentation(
                    nifti_path,
                    seg_dir,
                    progress=progress,
                    analysis_started=analysis_started,
                )
                logger.info("TS face: segmentation finished in %.1fs", inference_seconds)
                release_working_memory(stage="ts_face_after_segmentation")

            face_voxels = count_mask_voxels(mask_path)
            logger.info(
                "TS face: %s mask=%s slices=%d voxels=%d inference=%.1fs",
                series_directory,
                mask_path,
                n_slices,
                face_voxels,
                inference_seconds,
            )
            insufficient_error = _insufficient_face_mask_error(face_voxels)
            if insufficient_error is not None:
                logger.warning(
                    "TS face: insufficient face voxels (%d) for %s",
                    face_voxels,
                    series_directory,
                )
                return _face_error_result(series_directory, insufficient_error)
            return FaceSegResult(
                series_directory=series_directory,
                face_mask_path=mask_path,
                slice_count=n_slices,
                face_voxel_count=face_voxels,
                inference_seconds=inference_seconds,
            )
    except SystemExit:
        logger.error("TS face: TotalSegmentator license check failed for %s", series_directory)
        return _face_error_result(series_directory, _FACE_LICENSE_ERROR)
    except Exception as exc:
        logger.exception("TS face failed for %s: %s", series_directory, exc)
        return _face_error_result(series_directory, f"{type(exc).__name__}: {exc}")
    finally:
        release_working_memory(stage="ts_face_end")


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
    """Per-series cache under ``<series>/A_TS_SEG/`` (NIfTI, seg masks, contrast stats)."""
    return resolve_series_cache_dir(series_directory)


def estimate_tseg_contrast_remaining_sec(series_directory: Path) -> float:
    """Rough ETA for contrast analysis from per-series ``A_TS_SEG`` state."""
    cache_dir = series_cache_dir(series_directory)
    contrast_stats_path = cache_dir / CONTRAST_STATS_FILENAME
    contrast_stats_hn_path = cache_dir / CONTRAST_STATS_HN_FILENAME
    contrast_phase_path = cache_dir / CONTRAST_PHASE_CACHE_FILENAME

    existing_stats = None
    if contrast_stats_path.is_file():
        existing_stats = load_contrast_statistics(contrast_stats_path)

    body_parts_label = cached_body_parts_label(series_directory)
    needs_head_neck = bool(
        existing_stats
        and needs_head_neck_vessel_stats(
            existing_stats,
            body_parts_present=body_parts_label,
        )
    )
    stats_hn_cached = needs_head_neck and contrast_stats_hn_path.is_file()
    phase_cached = bool(
        existing_stats is not None
        and contrast_phase_cache_is_valid(
            contrast_phase_path,
            contrast_stats_path,
            stats_hn_path=contrast_stats_hn_path,
            require_stats_hn=needs_head_neck,
        )
    )
    return estimate_contrast_remaining_sec(
        stats_cached=existing_stats is not None,
        stats_hn_cached=stats_hn_cached,
        phase_cached=phase_cached,
        needs_head_neck=needs_head_neck,
    )


def face_mask_cache_path(series_directory: Path) -> Path:
    """Cached face mask under ``<series>/A_TS_SEG/seg/face.nii.gz``."""
    return series_cache_dir(series_directory) / "seg" / FACE_MASK_FILENAME


def _face_cache_valid(mask_path: Path) -> bool:
    return mask_path.is_file()


def _insufficient_face_mask_error(face_voxel_count: int) -> str | None:
    from anonymizer.controller.blur_face import (
        FaceBlurGateReason,
        face_blur_gate_message,
        face_mask_is_substantial,
    )

    if face_mask_is_substantial(face_voxel_count):
        return None
    return face_blur_gate_message(FaceBlurGateReason.INSUFFICIENT_FACE_MASK)


def _face_error_result(series_directory: Path, error: str) -> FaceSegResult:
    return FaceSegResult(
        series_directory=Path(series_directory),
        face_mask_path=None,
        slice_count=0,
        face_voxel_count=0,
        inference_seconds=0.0,
        error=error,
    )


def _segmentation_cache_valid(seg_dir: Path, structures: list[str]) -> bool:
    """True when ROI segmentation masks from a prior run are present."""
    if not seg_dir.is_dir():
        return False
    return any((seg_dir / f"{structure}.nii.gz").is_file() for structure in structures)


def _nifti_slice_count(nifti_path: Path) -> int:
    image = sitk.ReadImage(str(nifti_path))
    try:
        return int(image.GetSize()[2])
    finally:
        del image


def _tseg_volume_cache_stale(series_directory: Path, nifti_path: Path) -> bool:
    """True when cached ``volume.nii.gz`` no longer matches the stackable DICOM slice count."""
    if not nifti_path.is_file():
        return False
    expected_slices = len(stackable_dicom_paths(series_directory))
    cached_slices = _nifti_slice_count(nifti_path)
    return cached_slices != expected_slices


def invalidate_stale_tseg_volume_cache(
    series_directory: Path,
    nifti_path: Path,
    *,
    face_mask_path: Path | None = None,
) -> None:
    """Drop cached NIfTI and face mask when the DICOM stack has changed."""
    if not _tseg_volume_cache_stale(series_directory, nifti_path):
        return
    expected_slices = len(stackable_dicom_paths(series_directory))
    cached_slices = _nifti_slice_count(nifti_path)
    logger.warning(
        "TS cache: stale volume for %s (cached=%d slices, DICOM=%d); rebuilding",
        series_directory,
        cached_slices,
        expected_slices,
    )
    nifti_path.unlink(missing_ok=True)
    if face_mask_path is not None and face_mask_path.is_file():
        face_mask_path.unlink()


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
        structures_present=dict(region.structures_present),
    )


def analyze_tseg_regions(
    series_directory: Path,
    *,
    geometry: SeriesGeometryResult | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[TS_result, Path | None]:
    """
    DICOM→NIfTI, TotalSegmentator ROI segmentation, and region summary.

    Intermediate artifacts are cached under ``<series_directory>/A_TS_SEG/`` and
    reused when present. Returns ``(result, nifti_path)``. Contrast fields on
    ``result`` are empty when regions succeeded; contrast uses a separate pass.
    """
    series_directory = Path(series_directory)
    work_dir = series_cache_dir(series_directory)
    work_dir.mkdir(parents=True, exist_ok=True)
    nifti_path = work_dir / "volume.nii.gz"
    seg_dir = work_dir / "seg"
    analysis_started = time.perf_counter()

    geometry = geometry if geometry is not None else resolve_series_geometry(series_directory)
    logger.debug(
        "TS regions: geometry plane=%s dimensionality=%s provenance=%s ts_suitable=%s",
        geometry.plane,
        geometry.dimensionality,
        geometry.provenance,
        geometry.ts_suitable,
    )
    if not ts_regions_eligible(geometry):
        message = geometry.notes or f"Series not suitable for TotalSegmentator ({geometry.dimensionality})"
        logger.debug("TS regions: skipped for %s (%s)", series_directory, message)
        return (_error_result(series_directory, message), None)

    logger.debug("TS regions: starting for %s (cache=%s)", series_directory, work_dir)
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
                logger.debug("TS regions: reusing cached NIfTI %s (%d slices)", nifti_path, n_slices)
            else:
                logger.debug("TS regions: converting DICOM to NIfTI: %s", series_directory)
                n_slices = dicom_series_to_nifti(series_directory, nifti_path)
                release_working_memory(stage="ts_regions_after_dicom_to_nifti")
                logger.debug("TS regions: wrote %s (%d slices)", nifti_path, n_slices)

            roi_structures = list(ROI_SUBSET)
            seg_cached = _segmentation_cache_valid(seg_dir, roi_structures)
            if seg_cached:
                logger.debug("TS regions: reusing cached segmentation in %s", seg_dir)
                _report_progress(
                    progress,
                    stage="segment",
                    message=_("Using cached anatomy segmentation"),
                    fraction=0.35,
                    started=analysis_started,
                )
            else:
                logger.debug("TS regions: running segmentation for %s", series_directory)
                seg_seconds = run_segmentation(
                    nifti_path,
                    seg_dir,
                    progress=progress,
                    analysis_started=analysis_started,
                    n_slices=n_slices,
                )
                logger.debug("TS regions: segmentation finished in %.1fs", seg_seconds)
                _report_progress(
                    progress,
                    stage="segment",
                    message=f"Anatomy seg: inference {seg_seconds:.1f}s",
                    fraction=0.35,
                    started=analysis_started,
                )
                release_working_memory(stage="ts_regions_after_segmentation")

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

            region_result = _region_ts_result(
                series_directory,
                region=region,
                regions_label=regions_label,
            )
            logger.debug(
                "TS regions: %s dominant=%s label=%s fraction=%.3f",
                series_directory,
                region.dominant_region,
                regions_label,
                region.region_fraction,
            )
            _report_progress(
                progress,
                stage="regions",
                message=format_anatomy_regions_progress_message(region_result, seg_cached=seg_cached),
                fraction=0.95,
                started=analysis_started,
            )
            return (region_result, nifti_path)
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

    Contrast organ statistics are cached under ``<series>/A_TS_SEG/contrast_stats.json``;
    head/neck vessel statistics under ``contrast_stats_hn.json``; XGBoost output under
    ``contrast_phase.json``.
    """
    series_directory = Path(series_directory)
    analysis_started = time.perf_counter()

    if not region_result.body_parts_present.strip():
        return region_result

    release_before_contrast(stage="ts_contrast_after_anatomy_release")

    from anonymizer.controller.tseg.config import RELEASE_ANATOMY_PREDICTORS_BEFORE_CONTRAST
    from anonymizer.controller.tseg.model_cache import clear_predictor_cache

    if RELEASE_ANATOMY_PREDICTORS_BEFORE_CONTRAST:
        clear_predictor_cache()

    cache_dir = series_cache_dir(series_directory)
    contrast_stats_path = cache_dir / CONTRAST_STATS_FILENAME
    contrast_stats_hn_path = cache_dir / CONTRAST_STATS_HN_FILENAME
    contrast_phase_path = cache_dir / CONTRAST_PHASE_CACHE_FILENAME

    existing_stats = None
    if contrast_stats_path.is_file():
        existing_stats = load_contrast_statistics(contrast_stats_path)
        logger.debug("TS contrast: loaded cached contrast statistics from %s", contrast_stats_path)

    remaining_sec = estimate_tseg_contrast_remaining_sec(series_directory)

    _report_progress(
        progress,
        stage="contrast",
        message="Starting contrast phase analysis",
        fraction=0.0,
        started=analysis_started,
        remaining_sec=remaining_sec,
    )
    logger.debug("TS contrast: starting for %s (volume=%s)", series_directory, nifti_path)
    log_memory_usage("ts_contrast_before_load")

    try:
        with sequential_ml_context("ts_contrast_pipeline"):
            contrast_started = time.perf_counter()
            contrast = analyze_contrast_phase(
                nifti_path,
                existing_stats=existing_stats,
                stats_output_path=contrast_stats_path,
                stats_hn_output_path=contrast_stats_hn_path,
                phase_cache_path=contrast_phase_path,
                body_parts_present=region_result.body_parts_present or None,
                progress=_wrap_contrast_progress(
                    progress,
                    started=analysis_started,
                    remaining_sec=remaining_sec,
                ),
            )
            contrast_elapsed = time.perf_counter() - contrast_started
            if remaining_sec == 0.0:
                timing_message = "Contrast: cached phase"
            else:
                timing_message = f"Contrast: analysis {contrast_elapsed:.1f}s"
            _report_progress(
                progress,
                stage="contrast",
                message=timing_message,
                fraction=0.95,
                started=analysis_started,
                remaining_sec=0.0,
            )
        radlex_description = format_radlex_ct_series_description(
            region_result.body_parts_present,
            contrast.iv_contrast,
        )
        _report_progress(
            progress,
            stage="contrast",
            message="Contrast phase analysis complete",
            fraction=1.0,
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
            structures_present=dict(region_result.structures_present),
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
            structures_present=dict(region_result.structures_present),
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
