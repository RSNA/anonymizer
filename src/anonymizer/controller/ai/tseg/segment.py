"""TotalSegmentator segmentation, anatomy regions, and series analysis entry point."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import SimpleITK as sitk

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.ai.tseg.config import (
    BODY_PARTS,
    BRAIN_STRUCTURE_FILES,
    BRAIN_STRUCTURES_TASK,
    CONTRAST_PHASE_CACHE_FILENAME,
    CONTRAST_STATS_FILENAME,
    CONTRAST_STATS_HN_FILENAME,
    ENABLE_TS_CONTRAST,
    ENABLE_TSEG_BRAIN_STRUCTURES,
    ENABLE_TSEG_FACE,
    FACE_MASK_FILENAME,
    FACE_TASK,
    MIN_DICOM_SLICES,
    MIN_REGION_FRACTION,
    MIN_STRUCTURE_VOXELS,
    ROI_SUBSET,
    ROI_SUBSET_MANIFEST_FILENAME,
    SEGMENTATION_MODE,
    segmentation_mode_for_modality,
)
from anonymizer.controller.ai.tseg.contrast import (
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
from anonymizer.controller.ai.tseg.dicom_geometry import (
    SeriesGeometryResult,
    build_sitk_volume_from_series_frames,
    load_geometry_cache,
    resolve_series_geometry,
    stackable_dicom_paths,
    ts_regions_eligible,
)
from anonymizer.controller.ai.tseg.ml_env import sequential_ml_context
from anonymizer.controller.ai.tseg.seg_retention import (
    compact_seg_cache_if_needed,
    evict_tseg_volume,
    finalize_seg_cache,
    read_structure_voxels,
    resolve_harmonize_roi_subset,
    structure_voxels_sidecar_valid,
    widen_roi_tier,
)
from anonymizer.controller.series_io import load_series_frames
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

# Rough wall time for TotalSegmentator 3 mm on Apple Silicon (~272 axial slices, incl. model load).
_SEG_SECONDS_PER_SLICE = 0.11
_SEG_BASE_SECONDS = 30.0
_FACE_SEG_ESTIMATE_SECONDS = 90.0
_FACE_LICENSE_ERROR = "TotalSegmentator face task requires academic license (totalseg_set_license -l aca_...)"

# Returned in ``TS_result.error`` when harmonize cancellation is requested cooperatively.
HARMONIZE_CANCELLED_MESSAGE = "Cancelled"


def harmonize_cancel_requested(cancelled: Callable[[], bool] | None) -> bool:
    return cancelled is not None and cancelled()


@dataclass(frozen=True)
class AnalysisProgress:
    stage: str
    message: str
    fraction: float
    elapsed_sec: float
    remaining_sec: float | None = None
    geometry: SeriesGeometryResult | None = None
    tseg: TS_result | None = None


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
    "clavicula_left": "Chest",
    "clavicula_right": "Chest",
    **{f"rib_left_{i}": "Chest" for i in range(1, 13)},
    **{f"rib_right_{i}": "Chest" for i in range(1, 13)},
    **{f"vertebrae_C{i}": "Head" for i in range(1, 8)},
    **{f"vertebrae_T{i}": "Chest" for i in range(1, 13)},
    **{f"vertebrae_L{i}": "Abdomen" for i in range(1, 6)},
    "vertebrae_S1": "Abdomen",
    **{name: "Head" for name in (
        "brainstem",
        "subarachnoid_space",
        "venous_sinuses",
        "septum_pellucidum",
        "cerebellum",
        "caudate_nucleus",
        "lentiform_nucleus",
        "insular_cortex",
        "internal_capsule",
        "ventricle",
        "central_sulcus",
        "frontal_lobe",
        "parietal_lobe",
        "occipital_lobe",
        "temporal_lobe",
        "thalamus",
    )},
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


def collect_structure_voxels_from_masks(segmentation_dir: Path, structures: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for structure in structures:
        mask_path = segmentation_dir / f"{structure}.nii.gz"
        if not mask_path.is_file():
            counts[structure] = 0
            continue
        counts[structure] = count_mask_voxels(mask_path)
    return counts


def collect_structure_voxels(segmentation_dir: Path, structures: list[str]) -> dict[str, int]:
    seg_dir = Path(segmentation_dir)
    cache_dir = seg_dir.parent
    compact_seg_cache_if_needed(cache_dir, seg_dir, structures)
    cached = read_structure_voxels(cache_dir)
    if cached is not None and set(structures) <= set(cached.keys()):
        return {structure: int(cached.get(structure, 0)) for structure in structures}
    return collect_structure_voxels_from_masks(seg_dir, structures)


def region_from_structure(
    name: str,
    *,
    structure_to_region: dict[str, str] | None = None,
) -> str | None:
    mapping = structure_to_region if structure_to_region is not None else STRUCTURE_TO_REGION
    return mapping.get(name)


def dominant_region_from_voxels(
    structure_voxels: dict[str, int],
    *,
    min_voxels: int = MIN_STRUCTURE_VOXELS,
    structure_to_region: dict[str, str] | None = None,
) -> RegionResult:
    """Pick the region with the largest summed structure voxel count."""
    region_voxels = {region: 0 for region in BODY_PARTS}
    structures_present: dict[str, int] = {}

    for structure, count in structure_voxels.items():
        if count < min_voxels:
            continue
        region = region_from_structure(structure, structure_to_region=structure_to_region)
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
    """ROI anatomy label from ``0_TS_SEG`` segmentation cache, if available."""
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
    task: str | None = None,
    progress: ProgressCallback | None = None,
    analysis_started: float | None = None,
    n_slices: int | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> float:
    """Run TotalSegmentator anatomy task. Returns inference wall time in seconds.

    Defaults match today's CT path (``task=\"total\"``, ``ROI_SUBSET``).
    """
    totalsegmentator = _require_totalsegmentator()
    subset = roi_subset or list(ROI_SUBSET)
    anatomy_task = task or "total"
    output_dir.mkdir(parents=True, exist_ok=True)
    started = analysis_started if analysis_started is not None else time.perf_counter()
    estimate = _estimate_segmentation_seconds(n_slices or 100)

    fast = mode == "3mm"
    fastest = mode == "6mm"
    if mode not in {"3mm", "6mm", "1.5mm"}:
        raise ValueError(f"Unsupported TS mode: {mode!r}")

    kwargs: dict = {
        "task": anatomy_task,
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

    if harmonize_cancel_requested(cancelled):
        logger.info("TS segmentation: cancelled before inference for %s", nifti_path)
        return 0.0

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
    face_task: str | None = None,
    face_mask_filename: str | None = None,
) -> float:
    """Run TotalSegmentator face task. Returns inference wall time in seconds.

    Defaults match today's CT path (``face`` / ``face.nii.gz``).
    """
    totalsegmentator = _require_totalsegmentator()
    output_dir.mkdir(parents=True, exist_ok=True)
    mask_name = face_mask_filename or FACE_MASK_FILENAME
    task_name = face_task or FACE_TASK
    face_path = output_dir / mask_name
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
            task=task_name,
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


def run_brain_structures_segmentation(
    nifti_path: Path,
    output_dir: Path,
    *,
    device: str | None = None,
    progress: ProgressCallback | None = None,
    analysis_started: float | None = None,
) -> float:
    """Run TotalSegmentator ``brain_structures`` task. Returns inference wall time in seconds."""
    totalsegmentator = _require_totalsegmentator()
    output_dir.mkdir(parents=True, exist_ok=True)
    started = analysis_started if analysis_started is not None else time.perf_counter()

    _report_progress(
        progress,
        stage="brain_structures",
        message="Segmenting brain structures",
        fraction=0.4,
        started=started,
        remaining_sec=45.0,
    )

    seg_started = time.perf_counter()
    with sequential_ml_context("ts_brain_structures"):
        totalsegmentator(
            str(nifti_path),
            str(output_dir),
            task=BRAIN_STRUCTURES_TASK,
            fast=False,
            fastest=False,
            quiet=True,
            device=resolve_device(device),
            nr_thr_resamp=1,
            nr_thr_saving=1,
        )
    release_working_memory(stage="ts_brain_structures_end")
    return time.perf_counter() - seg_started


def _brain_structures_cache_valid(seg_dir: Path) -> bool:
    return any((seg_dir / f"{name}.nii.gz").is_file() for name in BRAIN_STRUCTURE_FILES)


def analyze_tseg_face(
    series_directory: Path,
    *,
    progress: ProgressCallback | None = None,
    force: bool = False,
    profile=None,
) -> FaceSegResult:
    """
    DICOM→NIfTI, TotalSegmentator face task, and cached face mask path.

    Reuses ``<series_directory>/0_TS_SEG/volume.nii.gz`` when present (same as
    anatomy regions). Face mask is cached at ``seg/face.nii.gz`` (CT) or
    ``seg/face_mr.nii.gz`` (MR).
    """
    from anonymizer.controller.ai.tseg.modality_profile import (
        resolve_profile_for_series,
    )
    from anonymizer.controller.ai.tseg.model_cache import profile_face_weights_ready

    series_directory = Path(series_directory)
    if not ENABLE_TSEG_FACE:
        return _face_error_result(
            series_directory,
            "Face segmentation is disabled (ENABLE_TSEG_FACE=False)",
        )

    resolved = profile if profile is not None else resolve_profile_for_series(series_directory)
    if resolved is None:
        return _face_error_result(series_directory, "Unsupported modality for face segmentation")
    profile = resolved

    if profile.modality != "CT" and not profile_face_weights_ready(profile):
        return _face_error_result(
            series_directory,
            f"TotalSegmentator {profile.face_task} weights (task {profile.face_task_id}) are not installed",
        )

    work_dir = series_cache_dir(series_directory)
    work_dir.mkdir(parents=True, exist_ok=True)
    nifti_path = work_dir / "volume.nii.gz"
    seg_dir = work_dir / "seg"
    mask_path = face_mask_cache_path(series_directory, profile=profile)
    analysis_started = time.perf_counter()

    geometry = resolve_series_geometry(series_directory)
    logger.info(
        "TS face: geometry plane=%s dimensionality=%s provenance=%s ts_suitable=%s modality=%s",
        geometry.plane,
        geometry.dimensionality,
        geometry.provenance,
        geometry.ts_suitable,
        profile.modality,
    )
    if not ts_regions_eligible(geometry):
        message = geometry.notes or f"Series not suitable for TotalSegmentator ({geometry.dimensionality})"
        logger.info("TS face: skipped for %s (%s)", series_directory, message)
        return _face_error_result(series_directory, message)

    logger.info("TS face: starting for %s (cache=%s task=%s)", series_directory, work_dir, profile.face_task)
    log_memory_usage("ts_face_start")
    invalidate_stale_tseg_volume_cache(series_directory, nifti_path, face_mask_path=mask_path)

    try:
        with sequential_ml_context("ts_face"):
            _report_progress(
                progress,
                stage="prepare",
                message="Preparing CT volume" if profile.modality == "CT" else "Preparing volume",
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
                    face_task=profile.face_task,
                    face_mask_filename=profile.face_mask_filename,
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
        error=error,
    )


def series_cache_dir(series_directory: Path) -> Path:
    """Per-series cache under ``<series>/0_TS_SEG/`` (NIfTI, seg masks, contrast stats)."""
    return resolve_series_cache_dir(series_directory)


def estimate_tseg_contrast_remaining_sec(series_directory: Path) -> float:
    """Rough ETA for contrast analysis from per-series ``0_TS_SEG`` state."""
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


def face_mask_cache_path(series_directory: Path, *, profile=None) -> Path:
    """Cached face mask under ``<series>/0_TS_SEG/seg/`` (CT ``face.nii.gz`` / MR ``face_mr.nii.gz``)."""
    from anonymizer.controller.ai.tseg.modality_profile import default_ct_profile

    resolved = profile if profile is not None else default_ct_profile()
    return series_cache_dir(series_directory) / "seg" / resolved.face_mask_filename


def _face_cache_valid(mask_path: Path) -> bool:
    return mask_path.is_file()


def _insufficient_face_mask_error(face_voxel_count: int) -> str | None:
    from anonymizer.controller.ai.blur_face import (
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


def _is_skeletal_roi(structure: str) -> bool:
    return (
        structure.startswith("vertebrae_")
        or structure.startswith("rib_")
        or structure.startswith("clavicula_")
        or structure in {"sacrum", "vertebrae"}
    )


def write_roi_subset_manifest(
    cache_dir: Path,
    structures: list[str],
    *,
    anatomy_task: str = "total",
    modality: str = "CT",
    roi_tier: str | None = None,
) -> None:
    """Record which TotalSegmentator ROI classes were requested for this series cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "roi_subset": sorted(structures),
        "anatomy_task": anatomy_task,
        "modality": modality,
    }
    if roi_tier is not None:
        payload["roi_tier"] = roi_tier
    path = cache_dir / ROI_SUBSET_MANIFEST_FILENAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_roi_subset_manifest(cache_dir: Path) -> tuple[set[str], str | None, str | None] | None:
    path = cache_dir / ROI_SUBSET_MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    recorded = data.get("roi_subset")
    if not isinstance(recorded, list):
        return None
    anatomy_task = data.get("anatomy_task")
    modality = data.get("modality")
    return (
        {str(name) for name in recorded},
        str(anatomy_task) if anatomy_task is not None else None,
        str(modality) if modality is not None else None,
    )


def _segmentation_cache_valid(
    seg_dir: Path,
    structures: list[str],
    *,
    anatomy_task: str = "total",
    modality: str = "CT",
) -> bool:
    """True when ROI masks exist and the cache covers the currently requested ROI subset.

    Soft-tissue-only legacy caches (pre-skeletal ROI expansion) are treated as stale so
    Harmonize re-runs and Series View can latch spine / ribs / clavicles.
    Manifest modality/task must match so a CT cache is never accepted for MR (and vice versa).
    """
    if not seg_dir.is_dir():
        return False

    cache_dir = seg_dir.parent
    recorded_bundle = _read_roi_subset_manifest(cache_dir)
    requested = set(structures)
    if recorded_bundle is not None:
        recorded, recorded_task, recorded_modality = recorded_bundle
        if recorded_task is not None and recorded_task != anatomy_task:
            return False
        if recorded_modality is not None and recorded_modality != modality:
            return False
        # Legacy manifests without modality/task: only accept for CT ``total``.
        if recorded_task is None and recorded_modality is None and (anatomy_task != "total" or modality != "CT"):
            return False
        if not requested <= recorded:
            return False
        if structure_voxels_sidecar_valid(cache_dir, structures):
            return True
        return any((seg_dir / f"{structure}.nii.gz").is_file() for structure in structures)

    # Legacy caches without a manifest: CT total only.
    if anatomy_task != "total" or modality != "CT":
        return False
    if structure_voxels_sidecar_valid(cache_dir, structures):
        return True
    if not any((seg_dir / f"{structure}.nii.gz").is_file() for structure in structures):
        return False
    skeletal_requested = [name for name in structures if _is_skeletal_roi(name)]
    if skeletal_requested and not any((seg_dir / f"{name}.nii.gz").is_file() for name in skeletal_requested):
        return False
    try:
        write_roi_subset_manifest(cache_dir, structures, anatomy_task=anatomy_task, modality=modality)
    except OSError:
        logger.debug("TS regions: could not backfill ROI subset manifest under %s", cache_dir)
    return True


def _nifti_slice_count(nifti_path: Path) -> int:
    image = sitk.ReadImage(str(nifti_path))
    try:
        return int(image.GetSize()[2])
    finally:
        del image


def _expected_stackable_slice_count(series_directory: Path) -> int | None:
    try:
        return len(stackable_dicom_paths(series_directory))
    except ValueError:
        return None


def _tseg_volume_cache_stale(series_directory: Path, nifti_path: Path) -> bool:
    """True when cached ``volume.nii.gz`` no longer matches the stackable DICOM slice count."""
    expected_slices = _expected_stackable_slice_count(series_directory)
    if expected_slices is None:
        return False
    if nifti_path.is_file():
        return _nifti_slice_count(nifti_path) != expected_slices
    geometry = load_geometry_cache(series_directory)
    if geometry is not None:
        return geometry.n_slices != expected_slices
    return False


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
        structures_present=dict(region.structures_present),
    )


def analyze_tseg_regions(
    series_directory: Path,
    *,
    geometry: SeriesGeometryResult | None = None,
    progress: ProgressCallback | None = None,
    include_brain_structures: bool = False,
    profile=None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[TS_result, Path | None]:
    """
    DICOM→NIfTI, TotalSegmentator ROI segmentation, and region summary.

    Intermediate artifacts are cached under ``<series_directory>/0_TS_SEG/`` and
    reused when present. Returns ``(result, nifti_path)``. Contrast fields on
    ``result`` are empty when regions succeeded; contrast uses a separate pass.

    ``profile`` defaults to the series modality profile (CT when omitted and
    series is CT). CT defaults match pre-MR behavior.
    """
    if harmonize_cancel_requested(cancelled):
        logger.info("TS regions: cancelled before start for %s", series_directory)
        return (_error_result(series_directory, HARMONIZE_CANCELLED_MESSAGE), None)

    from anonymizer.controller.ai.tseg.modality_profile import resolve_profile_for_series
    from anonymizer.controller.ai.tseg.model_cache import profile_anatomy_weights_ready

    series_directory = Path(series_directory)
    resolved = profile if profile is not None else resolve_profile_for_series(series_directory)
    if resolved is None:
        return (_error_result(series_directory, "Unsupported modality for TotalSegmentator"), None)
    profile = resolved

    if profile.modality != "CT" and not profile_anatomy_weights_ready(profile):
        missing = ", ".join(str(task_id) for task_id in profile.anatomy_task_ids)
        return (
            _error_result(
                series_directory,
                f"TotalSegmentator {profile.anatomy_task} weights missing (tasks {missing})",
            ),
            None,
        )

    work_dir = series_cache_dir(series_directory)
    work_dir.mkdir(parents=True, exist_ok=True)
    nifti_path = work_dir / "volume.nii.gz"
    seg_dir = work_dir / "seg"
    analysis_started = time.perf_counter()
    roi_tier: str | None = None
    if profile.modality == "CT":
        roi_subset, roi_tier = resolve_harmonize_roi_subset(series_directory)
        roi_structures = list(roi_subset)
    else:
        roi_structures = list(profile.roi_subset)

    geometry = geometry if geometry is not None else resolve_series_geometry(series_directory)
    logger.debug(
        "TS regions: geometry plane=%s dimensionality=%s provenance=%s ts_suitable=%s modality=%s",
        geometry.plane,
        geometry.dimensionality,
        geometry.provenance,
        geometry.ts_suitable,
        profile.modality,
    )
    if not ts_regions_eligible(geometry):
        message = geometry.notes or f"Series not suitable for TotalSegmentator ({geometry.dimensionality})"
        logger.debug("TS regions: skipped for %s (%s)", series_directory, message)
        return (_error_result(series_directory, message), None)

    logger.debug("TS regions: starting for %s (cache=%s task=%s)", series_directory, work_dir, profile.anatomy_task)
    log_memory_usage("ts_regions_start")

    with sequential_ml_context("ts_regions"):
        try:
            return _analyze_tseg_regions_impl(
                series_directory=series_directory,
                work_dir=work_dir,
                nifti_path=nifti_path,
                seg_dir=seg_dir,
                roi_structures=roi_structures,
                roi_tier=roi_tier,
                profile=profile,
                geometry=geometry,
                progress=progress,
                include_brain_structures=include_brain_structures,
                analysis_started=analysis_started,
                cancelled=cancelled,
            )
        except Exception as exc:
            logger.exception("TS regions failed for %s: %s", series_directory, exc)
            return (_error_result(series_directory, f"{type(exc).__name__}: {exc}"), None)
        finally:
            release_working_memory(stage="ts_regions_end")


def _analyze_tseg_regions_impl(
    *,
    series_directory: Path,
    work_dir: Path,
    nifti_path: Path,
    seg_dir: Path,
    roi_structures: list[str],
    roi_tier: str | None,
    profile,
    geometry: SeriesGeometryResult,
    progress: ProgressCallback | None,
    include_brain_structures: bool,
    analysis_started: float,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[TS_result, Path | None]:
    current_tier = roi_tier
    current_structures = list(roi_structures)

    while True:
        if harmonize_cancel_requested(cancelled):
            logger.info("TS regions: cancelled during analysis for %s", series_directory)
            return (_error_result(series_directory, HARMONIZE_CANCELLED_MESSAGE), nifti_path)

        _report_progress(
            progress,
            stage="prepare",
            message="Preparing CT volume" if profile.modality == "CT" else "Preparing volume",
            fraction=0.05,
            started=analysis_started,
        )
        if nifti_path.is_file():
            n_slices = _nifti_slice_count(nifti_path)
            logger.debug("TS regions: reusing cached NIfTI %s (%d slices)", nifti_path, n_slices)
        else:
            if harmonize_cancel_requested(cancelled):
                logger.info("TS regions: cancelled before DICOM→NIfTI for %s", series_directory)
                return (_error_result(series_directory, HARMONIZE_CANCELLED_MESSAGE), None)
            logger.debug("TS regions: converting DICOM to NIfTI: %s", series_directory)
            n_slices = dicom_series_to_nifti(series_directory, nifti_path)
            release_working_memory(stage="ts_regions_after_dicom_to_nifti")
            logger.debug("TS regions: wrote %s (%d slices)", nifti_path, n_slices)
            if harmonize_cancel_requested(cancelled):
                logger.info("TS regions: cancelled after DICOM→NIfTI for %s", series_directory)
                return (_error_result(series_directory, HARMONIZE_CANCELLED_MESSAGE), nifti_path)

        seg_cached = _segmentation_cache_valid(
            seg_dir,
            current_structures,
            anatomy_task=profile.anatomy_task,
            modality=profile.modality,
        )
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
            if harmonize_cancel_requested(cancelled):
                logger.info("TS regions: cancelled before segmentation for %s", series_directory)
                return (_error_result(series_directory, HARMONIZE_CANCELLED_MESSAGE), nifti_path)
            logger.debug("TS regions: running segmentation for %s", series_directory)
            seg_seconds = run_segmentation(
                nifti_path,
                seg_dir,
                mode=segmentation_mode_for_modality(profile.modality),
                progress=progress,
                analysis_started=analysis_started,
                n_slices=n_slices,
                roi_subset=current_structures,
                task=profile.anatomy_task,
                cancelled=cancelled,
            )
            if harmonize_cancel_requested(cancelled):
                logger.info("TS regions: cancelled after segmentation for %s", series_directory)
                return (_error_result(series_directory, HARMONIZE_CANCELLED_MESSAGE), nifti_path)
            write_roi_subset_manifest(
                work_dir,
                current_structures,
                anatomy_task=profile.anatomy_task,
                modality=profile.modality,
                roi_tier=current_tier,
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

        count_structures = list(
            dict.fromkeys(current_structures + list(BRAIN_STRUCTURE_FILES))
        )
        structure_voxels = collect_structure_voxels(seg_dir, count_structures)
        if (
            include_brain_structures
            and profile.modality == "CT"
            and ENABLE_TSEG_BRAIN_STRUCTURES
            and structure_voxels.get("brain", 0) >= MIN_STRUCTURE_VOXELS
            and not _brain_structures_cache_valid(seg_dir)
        ):
            from anonymizer.controller.ai.tseg.readiness import verify_face_license

            licensed, license_message = verify_face_license()
            if licensed:
                if harmonize_cancel_requested(cancelled):
                    logger.info("TS regions: cancelled before brain structures for %s", series_directory)
                    return (_error_result(series_directory, HARMONIZE_CANCELLED_MESSAGE), nifti_path)
                try:
                    brain_seconds = run_brain_structures_segmentation(
                        nifti_path,
                        seg_dir,
                        progress=progress,
                        analysis_started=analysis_started,
                    )
                    logger.debug(
                        "TS regions: brain_structures finished in %.1fs for %s",
                        brain_seconds,
                        series_directory,
                    )
                    release_working_memory(stage="ts_regions_after_brain_structures")
                    structure_voxels = collect_structure_voxels_from_masks(seg_dir, count_structures)
                except Exception as exc:
                    logger.warning(
                        "TS regions: brain_structures skipped for %s (%s)",
                        series_directory,
                        exc,
                    )
            else:
                logger.debug(
                    "TS regions: brain_structures skipped (license): %s",
                    license_message,
                )
        elif include_brain_structures and not ENABLE_TSEG_BRAIN_STRUCTURES:
            logger.debug("TS regions: brain_structures disabled in config")

        finalize_seg_cache(work_dir, seg_dir, structure_voxels)

        structure_to_region = profile.structure_to_region
        if profile.modality == "MR":
            from anonymizer.controller.ai.tseg.modality_profile import (
                load_series_header_dataset,
                mr_structure_to_region_for_series,
            )

            header_ds = load_series_header_dataset(series_directory)
            structure_to_region = mr_structure_to_region_for_series(header_ds)

        region = dominant_region_from_voxels(
            structure_voxels,
            structure_to_region=structure_to_region,
        )
        regions_label = body_parts_present(region.region_voxels)

        if not regions_label and current_tier is not None:
            widened = widen_roi_tier(current_tier)
            if widened is not None:
                wider_subset, wider_tier = widened
                logger.info(
                    "TS regions: widening ROI tier %s -> %s for %s",
                    current_tier,
                    wider_tier,
                    series_directory,
                )
                current_tier = wider_tier
                current_structures = list(wider_subset)
                continue

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
        return (region_result, nifti_path if nifti_path.is_file() else None)


def analyze_tseg_contrast(
    series_directory: Path,
    nifti_path: Path,
    region_result: TS_result,
    *,
    progress: ProgressCallback | None = None,
) -> TS_result:
    """
    Run TotalSegmentator organ HU statistics + XGBoost contrast-phase classification.

    Contrast organ statistics are cached under ``<series>/0_TS_SEG/contrast_stats.json``;
    head/neck vessel statistics under ``contrast_stats_hn.json``; XGBoost output under
    ``contrast_phase.json``.
    """
    series_directory = Path(series_directory)
    analysis_started = time.perf_counter()

    if not region_result.body_parts_present.strip():
        return region_result

    release_before_contrast(stage="ts_contrast_after_anatomy_release")

    from anonymizer.controller.ai.tseg.config import RELEASE_ANATOMY_PREDICTORS_BEFORE_CONTRAST
    from anonymizer.controller.ai.tseg.model_cache import clear_predictor_cache

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

    MR series skip contrast phase (no IV phase model) and return ``native`` / WO.
    """
    from anonymizer.controller.ai.tseg.modality_profile import resolve_profile_for_series

    if not series_directories:
        logger.error("No series directories provided for anatomy analysis.")
        return []

    logger.info("Anatomy analysis starting for %d series", len(series_directories))
    results: list[TS_result] = []

    for series_dir in series_directories:
        series_dir = Path(series_dir)
        region_result, nifti_path = analyze_tseg_regions(series_dir, progress=progress)
        profile = resolve_profile_for_series(series_dir)
        run_contrast = profile is None or profile.enable_contrast_phase
        if (
            run_contrast
            and ENABLE_TS_CONTRAST
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
            evict_tseg_volume(series_dir)
        elif profile is not None and not profile.enable_contrast_phase:
            evict_tseg_volume(series_dir)
            results.append(region_result)
        else:
            if not ENABLE_TS_CONTRAST and region_result.body_parts_present.strip():
                logger.info("TS contrast skipped (ENABLE_TS_CONTRAST=False) for %s", series_dir)
            evict_tseg_volume(series_dir)
            results.append(region_result)

    logger.info("Anatomy analysis finished: %d result(s)", len(results))
    return results
