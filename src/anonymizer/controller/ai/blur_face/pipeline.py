"""CT face de-identification: segment face mask, blur in-mask HU voxels, export derived DICOM.

Planned batch pipeline (PHI Index, not implemented here):
  iter studies/series → optional remove_pixel_phi → harmonize description → blur face
  with project prefs; log dialog like ImportFilesDialog; no per-series review modal.
  Manual preview runs in Series View with a companion image stack beside the primary viewer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path

import cv2
import numpy as np
import pydicom
import SimpleITK as sitk
from pydicom import Dataset, dcmread
from pydicom.uid import generate_uid
from scipy.ndimage import median_filter

from anonymizer.controller.ai.tseg.config import MIN_STRUCTURE_VOXELS
from anonymizer.controller.ai.tseg.dicom_geometry import SeriesGeometryResult, build_sitk_volume_from_series_frames
from anonymizer.controller.ai.tseg.segment import (
    analyze_tseg_face,
    body_parts_present,
    collect_structure_voxels,
    count_mask_voxels,
    dominant_region_from_voxels,
    face_mask_cache_path,
    invalidate_stale_tseg_volume_cache,
    series_cache_dir,
)
from anonymizer.controller.series_io import load_series_frames
from anonymizer.controller.series_overlay import PolygonPoint, Segmentation
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

# --- Config -----------------------------------------------------------------

DEFAULT_FACE_BLUR_OUTPUT_DIRNAME = "face_blurred"

# Primary user-facing control: approximate Gaussian standard deviation in millimetres
# (full width at half maximum ≈ 2.355 × sigma_mm for each in-plane axis).
DEFAULT_FACE_BLUR_SIGMA_MM = 8.0

# Minimum pixel sigma passed to OpenCV when spacing is very fine or sigma_mm is small.
MIN_FACE_BLUR_SIGMA_PX = 0.5

# In-plane Gaussian sigma (pixels) applied to the face mask before blur and overlay contours.
# Softens jagged segmentation edges so the final blur feathers instead of a hard pixel stair-step.
FACE_MASK_SMOOTH_SIGMA_PX = 1.5

# Ignore sub-HU noise outside the feathered mask when checking QA (float32 + soft blend).
QA_OUTSIDE_HU_TOLERANCE = 0.5

# Maximum in-plane median kernel (pixels). Larger effective radii use downsample → median → upsample.
MAX_MEDIAN_KERNEL_PX = 15

# Soft-tissue HU band for ``fill_noise`` mode.
FACE_BLUR_NOISE_HU_MIN = 20.0
FACE_BLUR_NOISE_HU_MAX = 60.0


class FaceBlurMode(StrEnum):
    GAUSSIAN = "gaussian"
    MEDIAN = "median"
    PIXELATE = "pixelate"
    FILL_NOISE = "fill_noise"


DEFAULT_FACE_BLUR_MODE = FaceBlurMode.GAUSSIAN

# --- Eligibility gate -------------------------------------------------------

MIN_FACE_MASK_VOXELS = MIN_STRUCTURE_VOXELS


class FaceBlurGateDecision(StrEnum):
    ALLOW = auto()
    CONFIRM = auto()
    BLOCK = auto()


class FaceBlurGateReason(StrEnum):
    MODALITY = auto()
    FEATURE_DISABLED = auto()
    GEOMETRY = auto()
    CACHED_REGIONS_HEAD = auto()
    CACHED_REGIONS_NON_HEAD = auto()
    CACHED_REGIONS_MULTI = auto()
    METADATA_HEAD = auto()
    METADATA_NON_HEAD = auto()
    AMBIGUOUS = auto()
    INSUFFICIENT_FACE_MASK = auto()
    ALREADY_APPLIED = auto()


class MetadataSignal(StrEnum):
    HEAD = auto()
    NON_HEAD = auto()
    AMBIGUOUS = auto()


class CachedRegionSignal(StrEnum):
    HEAD = auto()
    NON_HEAD = auto()
    MULTI_REGION = auto()
    UNAVAILABLE = auto()


@dataclass(frozen=True)
class FaceBlurEligibility:
    decision: FaceBlurGateDecision
    reason: FaceBlurGateReason


_REASON_MSGIDS: dict[FaceBlurGateReason, str] = {
    FaceBlurGateReason.MODALITY: "Face blur is available for CT and MR series only.",
    FaceBlurGateReason.FEATURE_DISABLED: "Face blur is not enabled in this installation.",
    FaceBlurGateReason.GEOMETRY: "This series type is not suitable for face segmentation.",
    FaceBlurGateReason.CACHED_REGIONS_HEAD: "Head anatomy detected from prior segmentation.",
    FaceBlurGateReason.CACHED_REGIONS_NON_HEAD: ("This series appears to be a chest or abdomen study, not a head CT."),
    FaceBlurGateReason.CACHED_REGIONS_MULTI: (
        "This series spans multiple body regions. Face blur is intended for head CT. Continue?"
    ),
    FaceBlurGateReason.METADATA_HEAD: "Series metadata indicates a head study.",
    FaceBlurGateReason.METADATA_NON_HEAD: "Series metadata indicates this is not a head CT.",
    FaceBlurGateReason.AMBIGUOUS: (
        "Could not confirm this is a head CT. Face blur is intended for head studies. Continue?"
    ),
    FaceBlurGateReason.INSUFFICIENT_FACE_MASK: (
        "This appears to be a head CT, but TotalSegmentator found no face region to blur. "
        "The series may already be face-blurred or otherwise unsuitable for re-blur."
    ),
    FaceBlurGateReason.ALREADY_APPLIED: ("Face blur has already been applied to this series and cannot be run again."),
}

# DICOM keyword heuristics (not user-facing).
_HEAD_KEYWORDS: tuple[str, ...] = (
    "HEAD",
    "BRAIN",
    "SKULL",
    "NECK",
    "ORBIT",
    "SINUS",
    "FACIAL",
    "CEREB",
    "STROKE",
    "CTA HEAD",
    "HEAD NECK",
)

_NON_HEAD_KEYWORDS: tuple[str, ...] = (
    "CHEST",
    "THOR",
    "ABDOM",
    "PELV",
    "LUNG",
    "LIVER",
    "RENAL",
    "KUB",
    "EXTREM",
    "LOWER LIMB",
    "UPPER LIMB",
    "FOOT",
    "ANKLE",
    "KNEE",
    "HIP",
)

_CACHED_SIGNAL_ELIGIBILITY: dict[
    CachedRegionSignal,
    FaceBlurEligibility | None,
] = {
    CachedRegionSignal.HEAD: FaceBlurEligibility(
        FaceBlurGateDecision.ALLOW,
        FaceBlurGateReason.CACHED_REGIONS_HEAD,
    ),
    CachedRegionSignal.NON_HEAD: FaceBlurEligibility(
        FaceBlurGateDecision.BLOCK,
        FaceBlurGateReason.CACHED_REGIONS_NON_HEAD,
    ),
    CachedRegionSignal.MULTI_REGION: FaceBlurEligibility(
        FaceBlurGateDecision.CONFIRM,
        FaceBlurGateReason.CACHED_REGIONS_MULTI,
    ),
    CachedRegionSignal.UNAVAILABLE: None,
}

_METADATA_SIGNAL_ELIGIBILITY: dict[MetadataSignal, FaceBlurEligibility] = {
    MetadataSignal.HEAD: FaceBlurEligibility(
        FaceBlurGateDecision.ALLOW,
        FaceBlurGateReason.METADATA_HEAD,
    ),
    MetadataSignal.NON_HEAD: FaceBlurEligibility(
        FaceBlurGateDecision.BLOCK,
        FaceBlurGateReason.METADATA_NON_HEAD,
    ),
    MetadataSignal.AMBIGUOUS: FaceBlurEligibility(
        FaceBlurGateDecision.CONFIRM,
        FaceBlurGateReason.AMBIGUOUS,
    ),
}


def face_blur_gate_message(reason: FaceBlurGateReason) -> str:
    """Return the translated user-facing message for a gate reason."""
    return _(_REASON_MSGIDS[reason])


def face_blur_status_applicable(
    eligibility: FaceBlurEligibility,
    *,
    already_applied: bool,
) -> bool:
    """Return whether Series View should show the Face blur segment in processing status."""
    if already_applied:
        return True
    if eligibility.decision in {FaceBlurGateDecision.ALLOW, FaceBlurGateDecision.CONFIRM}:
        return True
    return eligibility.reason not in {
        FaceBlurGateReason.MODALITY,
        FaceBlurGateReason.FEATURE_DISABLED,
        FaceBlurGateReason.GEOMETRY,
        FaceBlurGateReason.CACHED_REGIONS_NON_HEAD,
        FaceBlurGateReason.METADATA_NON_HEAD,
    }


def face_blur_context_hint(
    eligibility: FaceBlurEligibility,
    geometry: SeriesGeometryResult | None,
) -> str | None:
    """
    Optional geometry-line suffix when the block reason is not already covered there.

    Geometry blocks are omitted because the Series View geometry line already states
    segmentation suitability; non-head blocks after Harmonize get a explicit cause.
    """
    if eligibility.decision != FaceBlurGateDecision.BLOCK:
        return None
    if eligibility.reason == FaceBlurGateReason.GEOMETRY:
        return None
    if geometry is None:
        return None
    if eligibility.reason in {
        FaceBlurGateReason.CACHED_REGIONS_NON_HEAD,
        FaceBlurGateReason.METADATA_NON_HEAD,
    }:
        return face_blur_gate_message(eligibility.reason)
    return None


def face_mask_is_substantial(face_voxel_count: int) -> bool:
    return face_voxel_count >= MIN_FACE_MASK_VOXELS


def _dicom_search_text(ds: Dataset | None) -> str:
    if ds is None:
        return ""
    parts = [
        getattr(ds, "BodyPartExamined", None),
        getattr(ds, "SeriesDescription", None),
        getattr(ds, "ProtocolName", None),
        getattr(ds, "StudyDescription", None),
    ]
    return " ".join(str(part).strip() for part in parts if part).upper()


def metadata_signal(ds: Dataset | None) -> MetadataSignal:
    text = _dicom_search_text(ds)
    if not text:
        return MetadataSignal.AMBIGUOUS
    has_head = any(keyword in text for keyword in _HEAD_KEYWORDS)
    has_non_head = any(keyword in text for keyword in _NON_HEAD_KEYWORDS)
    if has_head and not has_non_head:
        return MetadataSignal.HEAD
    if has_non_head and not has_head:
        return MetadataSignal.NON_HEAD
    return MetadataSignal.AMBIGUOUS


def cached_region_signal(series_directory: Path) -> CachedRegionSignal:
    """
    Infer head vs non-head from cached TotalSegmentator ROI masks (``0_TS_SEG/seg/``).

    Returns ``UNAVAILABLE`` when harmonize/regions has not populated the cache.
    """
    from anonymizer.controller.ai.tseg.modality_profile import (
        ct_modality_profile,
        resolve_profile_for_series,
    )

    seg_dir = series_cache_dir(series_directory) / "seg"
    if not seg_dir.is_dir():
        return CachedRegionSignal.UNAVAILABLE

    profile = resolve_profile_for_series(series_directory) or ct_modality_profile()
    structure_voxels = collect_structure_voxels(seg_dir, list(profile.roi_subset))
    if not any(count >= MIN_STRUCTURE_VOXELS for count in structure_voxels.values()):
        return CachedRegionSignal.UNAVAILABLE

    region = dominant_region_from_voxels(
        structure_voxels,
        structure_to_region=profile.structure_to_region,
    )
    regions_label = body_parts_present(region.region_voxels)
    if not regions_label:
        return CachedRegionSignal.UNAVAILABLE

    head_present = "Head" in regions_label.split("+")
    if "+" in regions_label and head_present:
        return CachedRegionSignal.MULTI_REGION
    if region.dominant_region == "Head" or head_present:
        return CachedRegionSignal.HEAD
    if region.dominant_region in {"Chest", "Abdomen"}:
        return CachedRegionSignal.NON_HEAD
    return CachedRegionSignal.UNAVAILABLE


def _eligibility(
    decision: FaceBlurGateDecision,
    reason: FaceBlurGateReason,
) -> FaceBlurEligibility:
    return FaceBlurEligibility(decision, reason)


def evaluate_face_blur_eligibility(
    series_directory: Path,
    *,
    ds: Dataset | None = None,
    geometry: SeriesGeometryResult | None = None,
    modality: str | None = None,
    enable_tseg_face: bool = True,
    face_blur_already_applied: bool = False,
) -> FaceBlurEligibility:
    """
    Decide whether Blur Face should run, prompt for confirmation, or stay disabled.

    Cached anatomy regions (when present) override DICOM metadata heuristics.
    """
    from anonymizer.utils.modalities import is_tseg_modality, normalize_modality

    if face_blur_already_applied:
        return _eligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.ALREADY_APPLIED)

    series_directory = Path(series_directory).resolve()
    resolved_modality = modality
    if resolved_modality is None and ds is not None:
        resolved_modality = getattr(ds, "Modality", None)

    if not is_tseg_modality(resolved_modality):
        return _eligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.MODALITY)
    if not enable_tseg_face:
        return _eligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.FEATURE_DISABLED)
    if geometry is None or not geometry.ts_suitable:
        return _eligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.GEOMETRY)

    # MR without face_mr weights: block clearly (CT still auto-downloads on demand).
    if normalize_modality(resolved_modality) == "MR":
        from anonymizer.controller.ai.tseg.model_cache import mr_face_model_ready

        if not mr_face_model_ready():
            return _eligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.FEATURE_DISABLED)

    cached = cached_region_signal(series_directory)
    cached_eligibility = _CACHED_SIGNAL_ELIGIBILITY[cached]
    if cached_eligibility is not None:
        logger.debug("Face blur gate: %s (cached signal=%s)", cached_eligibility.reason.name, cached.name)
        return cached_eligibility

    meta = metadata_signal(ds)
    meta_eligibility = _METADATA_SIGNAL_ELIGIBILITY[meta]
    logger.debug("Face blur gate: %s (metadata signal=%s)", meta_eligibility.reason.name, meta.name)
    return meta_eligibility


# --- Results ----------------------------------------------------------------


@dataclass(frozen=True)
class QaStats:
    max_abs_diff_outside: float
    n_violating_voxels: int
    n_outside_voxels: int
    n_face_voxels: int
    mean_abs_diff_inside: float

    @property
    def outside_clean(self) -> bool:
        return self.n_violating_voxels == 0


@dataclass(frozen=True)
class FaceBlurResult:
    series_directory: Path
    output_directory: Path
    face_mask_path: Path | None
    slice_count: int
    qa_stats: QaStats | None
    error: str | None = None


@dataclass(frozen=True)
class SeriesVolumeContext:
    """Preloaded Series View slice stack (same order and processing as ``load_series_frames``)."""

    reference_ds: Dataset
    slice_frames: np.ndarray
    slice_paths: tuple[Path, ...]
    slice_spacing_mm: float | None = None


@dataclass(frozen=True)
class FaceBlurPreviewResult:
    """In-memory face blur preview; does not write DICOM.

    Memory layout:
    - ``mask``: kept for review overlay only; released on teardown.
    - ``blurred_slice_frames``: stored-pixel blurred stack for Series View (when precomputed).
    - ``hu_after``: float HU stack retained only for batch DICOM export paths.
    Neither stack is written to disk until the user saves pixel changes.
    """

    series_directory: Path
    face_mask_path: Path | None
    slice_paths: tuple[Path, ...]
    mask: np.ndarray
    slice_count: int
    qa_stats: QaStats | None
    sigma_mm: float
    blur_mode: FaceBlurMode
    pixel_spacing_mm: tuple[float, float]
    hu_after: np.ndarray | None = None
    blurred_slice_frames: np.ndarray | None = None
    error: str | None = None


@dataclass(frozen=True)
class FaceBlurProgress:
    stage: str
    message: str
    fraction: float


FaceBlurProgressCallback = Callable[[FaceBlurProgress], None]


# --- Face mask resolution ---------------------------------------------------


def resolve_face_mask_path(
    series_directory: Path,
    *,
    run_if_missing: bool = True,
    force_segmentation: bool = False,
    profile=None,
) -> Path:
    """
    Return the face mask NIfTI for ``series_directory``.

    Uses ``<series>/0_TS_SEG/seg/face.nii.gz`` (CT) or ``face_mr.nii.gz`` (MR).
    When no mask exists and ``run_if_missing`` is true, run ``analyze_tseg_face``.
    """
    from anonymizer.controller.ai.tseg.modality_profile import (
        ct_modality_profile,
        resolve_profile_for_series,
    )

    series_directory = Path(series_directory).resolve()
    resolved = profile if profile is not None else resolve_profile_for_series(series_directory)
    if resolved is None:
        resolved = ct_modality_profile()
    profile = resolved

    cache_path = face_mask_cache_path(series_directory, profile=profile)
    invalidate_stale_tseg_volume_cache(
        series_directory,
        series_cache_dir(series_directory) / "volume.nii.gz",
        face_mask_path=cache_path,
    )

    if cache_path.is_file() and not force_segmentation:
        face_voxels = count_mask_voxels(cache_path)
        if face_mask_is_substantial(face_voxels):
            logger.info("Face blur: using cached mask %s", cache_path)
            return cache_path
        message = face_blur_gate_message(FaceBlurGateReason.INSUFFICIENT_FACE_MASK)
        logger.warning(
            "Face blur: cached mask has insufficient face voxels (%d) for %s",
            face_voxels,
            series_directory,
        )
        raise RuntimeError(message)

    if not run_if_missing:
        raise FileNotFoundError(
            f"Face mask not found at {cache_path}. "
            "Run face segmentation first (ts_seg_face.py or analyze_tseg_face)."
        )

    if force_segmentation:
        logger.info("Face blur: force_segmentation=True; running analyze_tseg_face for %s", series_directory)
    else:
        logger.info("Face blur: mask missing; running analyze_tseg_face for %s", series_directory)
    result = analyze_tseg_face(series_directory, force=force_segmentation, profile=profile)
    if result.error is not None:
        raise RuntimeError(result.error)
    if result.face_mask_path is None or not result.face_mask_path.is_file():
        raise FileNotFoundError(f"analyze_tseg_face completed without writing a mask for {series_directory}")
    if not face_mask_is_substantial(result.face_voxel_count):
        raise RuntimeError(face_blur_gate_message(FaceBlurGateReason.INSUFFICIENT_FACE_MASK))
    logger.info(
        "Face blur: mask ready %s (%d voxels, inference %.1fs)",
        result.face_mask_path,
        result.face_voxel_count,
        result.inference_seconds,
    )
    return result.face_mask_path


# --- Volume I/O -------------------------------------------------------------


def hu_stack_from_series_frames(frames: np.ndarray) -> np.ndarray:
    """Return HU values from a ``load_series_frames`` grayscale stack."""
    if frames.ndim != 3:
        raise ValueError(f"Face blur requires grayscale slice stack (Z, Y, X), got shape {frames.shape}")
    hu = np.asarray(frames, dtype=np.float32)
    logger.info(
        "Face blur: HU stack from series frames shape=%s range=[%.1f, %.1f]",
        hu.shape,
        float(hu.min()),
        float(hu.max()),
    )
    return hu


def load_series_volume_for_blur(series_directory: Path) -> tuple[sitk.Image, np.ndarray, tuple[Path, ...]]:
    """Load CT volume + HU stack via ``load_series_frames`` (Series View loader)."""
    series_directory = Path(series_directory).resolve()
    loaded = load_series_frames(series_directory)
    reference_ds, frames, slice_paths = loaded.metadata, loaded.frames, loaded.slice_paths
    paths = tuple(slice_paths)
    if not paths:
        raise ValueError(f"No DICOM slices with pixel data found in {series_directory}")
    logger.info("Face blur: loading series volume (%d slices) from %s", len(paths), series_directory)
    volume = build_sitk_volume_from_series_frames(reference_ds, frames, paths)
    hu = hu_stack_from_series_frames(frames)
    size = volume.GetSize()
    spacing = volume.GetSpacing()
    logger.info(
        "Face blur: reference volume size=%s spacing=%s origin=%s",
        size,
        tuple(round(float(value), 4) for value in spacing),
        tuple(round(float(value), 2) for value in volume.GetOrigin()),
    )
    return volume, hu, paths


def read_reference_volume(series_directory: Path) -> tuple[sitk.Image, tuple[Path, ...]]:
    """Build 3D SimpleITK volume using the Series View DICOM loader."""
    volume, _hu, paths = load_series_volume_for_blur(series_directory)
    return volume, paths


def align_mask_to_volume(mask_path: Path, volume: sitk.Image) -> sitk.Image:
    mask_path = Path(mask_path).resolve()
    mask = sitk.ReadImage(str(mask_path))
    same_geometry = (
        mask.GetSize() == volume.GetSize()
        and mask.GetSpacing() == volume.GetSpacing()
        and mask.GetOrigin() == volume.GetOrigin()
        and mask.GetDirection() == volume.GetDirection()
    )
    if same_geometry:
        logger.info("Face blur: mask geometry matches volume (%s)", mask_path)
        return mask

    logger.info("Face blur: resampling mask to reference volume geometry (%s)", mask_path)
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(volume)
    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
    resampler.SetDefaultPixelValue(0)
    return resampler.Execute(mask)


def mask_array_from_volume(mask_image: sitk.Image) -> np.ndarray:
    array = sitk.GetArrayFromImage(mask_image)
    return array > 0


def load_hu_stack(slice_paths: tuple[Path, ...]) -> np.ndarray:
    """Load per-slice HU in the same order as readable stackable DICOM paths."""
    slices: list[np.ndarray] = []
    for path in slice_paths:
        ds = dcmread(str(path))
        if not hasattr(ds, "PixelData"):
            raise ValueError(f"DICOM slice has no pixel data: {path.name}")
        pixels = ds.pixel_array.astype(np.float32)
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        slices.append(pixels * slope + intercept)
    stack = np.stack(slices, axis=0).astype(np.float32, copy=False)
    logger.info(
        "Face blur: loaded HU stack shape=%s range=[%.1f, %.1f]",
        stack.shape,
        float(stack.min()),
        float(stack.max()),
    )
    return stack


# --- In-mask blur -----------------------------------------------------------


def smooth_face_mask_slice(
    slice_mask: np.ndarray,
    *,
    smooth_sigma: float = FACE_MASK_SMOOTH_SIGMA_PX,
) -> np.ndarray:
    """Return float32 blend weights in [0, 1] with softened mask edges (one axial slice)."""
    binary = (slice_mask > 0).astype(np.float32)
    if not binary.any() or smooth_sigma <= 0:
        return binary
    return cv2.GaussianBlur(binary, (0, 0), smooth_sigma)


def face_mask_blend_weights(
    mask: np.ndarray,
    *,
    smooth_sigma: float = FACE_MASK_SMOOTH_SIGMA_PX,
) -> np.ndarray:
    """Return per-voxel blend weights for face blur (Z, Y, X), same smoothing as overlay contours."""
    weights = np.empty(mask.shape, dtype=np.float32)
    for z in range(mask.shape[0]):
        weights[z] = smooth_face_mask_slice(mask[z], smooth_sigma=smooth_sigma)
    return weights


def _median_kernel_size(sigma_px: float) -> int:
    kernel = max(3, int(round(sigma_px * 2)))
    if kernel % 2 == 0:
        kernel += 1
    return min(kernel, MAX_MEDIAN_KERNEL_PX)


def _median_face_slice(
    hu_slice: np.ndarray,
    *,
    sigma_mm: float,
    pixel_spacing_mm: tuple[float, float],
    sigma_x: float,
    sigma_y: float,
) -> np.ndarray:
    """Median de-id on one slice; downsample when sigma_mm implies a large in-plane radius."""
    slice_f32 = hu_slice.astype(np.float32)
    kernel = _median_kernel_size(min(sigma_x, sigma_y))
    block_px = _pixelate_block_size(sigma_mm, pixel_spacing_mm)

    if block_px <= MAX_MEDIAN_KERNEL_PX:
        return median_filter(slice_f32, size=kernel)

    height, width = slice_f32.shape
    small_h = max(1, height // block_px)
    small_w = max(1, width // block_px)
    small = cv2.resize(slice_f32, (small_w, small_h), interpolation=cv2.INTER_AREA)
    small_kernel = min(
        _median_kernel_size(max(small_h, small_w) / 4),
        MAX_MEDIAN_KERNEL_PX,
    )
    if small_kernel >= 3 and min(small_h, small_w) >= small_kernel:
        small = median_filter(small, size=small_kernel)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)


def _pixelate_block_size(sigma_mm: float, pixel_spacing_mm: tuple[float, float]) -> int:
    row_spacing, col_spacing = pixel_spacing_mm
    min_spacing = min(row_spacing, col_spacing)
    return max(4, int(round(sigma_mm / min_spacing)))


def _transform_face_hu_slice(
    hu_slice: np.ndarray,
    *,
    blur_mode: FaceBlurMode,
    sigma_x: float,
    sigma_y: float,
    pixel_spacing_mm: tuple[float, float],
    sigma_mm: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Apply the selected in-mask de-identification operator on one axial slice."""
    slice_f32 = hu_slice.astype(np.float32)
    if blur_mode == FaceBlurMode.GAUSSIAN:
        return cv2.GaussianBlur(slice_f32, ksize=(0, 0), sigmaX=sigma_x, sigmaY=sigma_y)
    if blur_mode == FaceBlurMode.MEDIAN:
        return _median_face_slice(
            hu_slice,
            sigma_mm=sigma_mm,
            pixel_spacing_mm=pixel_spacing_mm,
            sigma_x=sigma_x,
            sigma_y=sigma_y,
        )
    if blur_mode == FaceBlurMode.PIXELATE:
        block_px = _pixelate_block_size(sigma_mm, pixel_spacing_mm)
        height, width = slice_f32.shape
        small_h = max(1, height // block_px)
        small_w = max(1, width // block_px)
        small = cv2.resize(slice_f32, (small_w, small_h), interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)
    if blur_mode == FaceBlurMode.FILL_NOISE:
        return rng.uniform(
            FACE_BLUR_NOISE_HU_MIN,
            FACE_BLUR_NOISE_HU_MAX,
            size=slice_f32.shape,
        ).astype(np.float32)
    raise ValueError(f"Unsupported face blur mode: {blur_mode}")


def blur_face_hu_volume(
    hu: np.ndarray,
    mask: np.ndarray,
    *,
    sigma_mm: float = DEFAULT_FACE_BLUR_SIGMA_MM,
    blur_mode: FaceBlurMode | str = DEFAULT_FACE_BLUR_MODE,
    pixel_spacing_mm: tuple[float, float] = (1.0, 1.0),
    min_sigma_px: float = MIN_FACE_BLUR_SIGMA_PX,
    mask_smooth_sigma_px: float = FACE_MASK_SMOOTH_SIGMA_PX,
) -> np.ndarray:
    """
    In-plane face de-identification inside ``mask``, feathered at the boundary.

    For each slice: apply the selected de-id operator, then blend into the original
    using smoothed mask weights from ``smooth_face_mask_slice`` (same feathering as
    the Series View face overlay, avoiding jagged segmentation edges).

    ``hu`` and ``mask`` shape: (Z, Y, X).
    """
    if hu.shape != mask.shape:
        raise ValueError(f"HU shape {hu.shape} != mask shape {mask.shape}")

    mode = FaceBlurMode(blur_mode)
    row_spacing, col_spacing = pixel_spacing_mm
    sigma_y = max(sigma_mm / row_spacing, min_sigma_px)
    sigma_x = max(sigma_mm / col_spacing, min_sigma_px)
    logger.info(
        "Face blur: mode=%s sigma_mm=%.2f → sigma_px=(%.2f, %.2f) spacing_mm=(%.3f, %.3f) mask_smooth_sigma_px=%.2f",
        mode.value,
        sigma_mm,
        sigma_x,
        sigma_y,
        row_spacing,
        col_spacing,
        mask_smooth_sigma_px,
    )

    out = hu.copy()
    face = mask.astype(bool)
    rng = np.random.default_rng()
    slices_with_face = 0
    for z in range(hu.shape[0]):
        if not face[z].any():
            continue
        slices_with_face += 1
        blend = smooth_face_mask_slice(face[z], smooth_sigma=mask_smooth_sigma_px)
        transformed = _transform_face_hu_slice(
            hu[z],
            blur_mode=mode,
            sigma_x=sigma_x,
            sigma_y=sigma_y,
            pixel_spacing_mm=pixel_spacing_mm,
            sigma_mm=sigma_mm,
            rng=rng,
        )
        out[z] = transformed * blend + hu[z] * (1.0 - blend)
    logger.info(
        "Face blur: %s applied on %d / %d axial slices (%d face voxels, feathered edges)",
        mode.value,
        slices_with_face,
        hu.shape[0],
        int(face.sum()),
    )
    return out


def blur_face_intensity_volume(
    volume: np.ndarray,
    mask: np.ndarray,
    *,
    low_percentile: float = 20.0,
    high_percentile: float = 40.0,
    mask_smooth_sigma_px: float = FACE_MASK_SMOOTH_SIGMA_PX,
) -> np.ndarray:
    """
    MR-safe face fill: replace in-mask voxels with intensities sampled from non-face percentiles.

    CT callers should continue to use ``blur_face_hu_volume`` unchanged.
    """
    if volume.shape != mask.shape:
        raise ValueError(f"Volume shape {volume.shape} != mask shape {mask.shape}")

    face = mask.astype(bool)
    outside = ~face
    if not face.any():
        return volume.copy()

    sample = volume[outside]
    if sample.size == 0:
        sample = volume.ravel()
    low = float(np.percentile(sample, low_percentile))
    high = float(np.percentile(sample, high_percentile))
    if high < low:
        low, high = high, low
    logger.info(
        "Face blur: intensity fill from non-face percentiles [%.1f, %.1f] → [%.3f, %.3f]",
        low_percentile,
        high_percentile,
        low,
        high,
    )

    out = volume.copy().astype(np.float32, copy=False)
    rng = np.random.default_rng()
    for z in range(volume.shape[0]):
        if not face[z].any():
            continue
        blend = smooth_face_mask_slice(face[z], smooth_sigma=mask_smooth_sigma_px)
        fill = rng.uniform(low, high, size=volume[z].shape).astype(np.float32)
        out[z] = fill * blend + volume[z].astype(np.float32) * (1.0 - blend)
    return out


def blur_face_volume_for_profile(
    volume: np.ndarray,
    mask: np.ndarray,
    *,
    profile,
    sigma_mm: float = DEFAULT_FACE_BLUR_SIGMA_MM,
    blur_mode: FaceBlurMode | str = DEFAULT_FACE_BLUR_MODE,
    pixel_spacing_mm: tuple[float, float] = (1.0, 1.0),
) -> np.ndarray:
    """Dispatch face fill by modality profile; CT path keeps ``blur_face_hu_volume``."""
    mode = FaceBlurMode(blur_mode)
    if profile.face_fill == "intensity_percentile" and mode == FaceBlurMode.FILL_NOISE:
        return blur_face_intensity_volume(volume, mask)
    return blur_face_hu_volume(
        volume,
        mask,
        sigma_mm=sigma_mm,
        blur_mode=blur_mode,
        pixel_spacing_mm=pixel_spacing_mm,
    )


# --- QA ---------------------------------------------------------------------


def compute_qa_stats(
    hu_before: np.ndarray,
    hu_after: np.ndarray,
    mask: np.ndarray,
    *,
    mask_smooth_sigma_px: float = FACE_MASK_SMOOTH_SIGMA_PX,
) -> QaStats:
    """Quantify whether voxels outside the feathered face mask changed."""
    face = mask.astype(bool)
    blend = face_mask_blend_weights(mask, smooth_sigma=mask_smooth_sigma_px)
    outside = blend <= 1e-6
    diff = np.abs(hu_after.astype(np.float32) - hu_before.astype(np.float32))

    outside_diff = diff[outside]
    inside_diff = diff[face]

    n_violating = int(np.sum(outside_diff > QA_OUTSIDE_HU_TOLERANCE)) if outside_diff.size else 0
    max_outside = float(outside_diff.max()) if outside_diff.size else 0.0
    mean_inside = float(inside_diff.mean()) if inside_diff.size else 0.0

    return QaStats(
        max_abs_diff_outside=max_outside,
        n_violating_voxels=n_violating,
        n_outside_voxels=int(outside.sum()),
        n_face_voxels=int(face.sum()),
        mean_abs_diff_inside=mean_inside,
    )


def mask_slice_segmentations(
    mask: np.ndarray,
    slice_index: int,
    *,
    smooth_sigma: float = FACE_MASK_SMOOTH_SIGMA_PX,
    contour_epsilon_ratio: float = 0.002,
) -> list[Segmentation]:
    """Extract smoothed face-mask contours for one axial slice (viewer overlay polygons)."""
    if slice_index < 0 or slice_index >= mask.shape[0]:
        return []
    if not (mask[slice_index] > 0).any():
        return []

    smoothed = smooth_face_mask_slice(mask[slice_index], smooth_sigma=smooth_sigma)
    slice_mask = (smoothed >= 0.5).astype(np.uint8)

    contours, _ = cv2.findContours(slice_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    segmentations: list[Segmentation] = []
    for contour in contours:
        if contour.shape[0] < 3:
            continue
        if contour_epsilon_ratio > 0:
            epsilon = contour_epsilon_ratio * cv2.arcLength(contour, True)
            contour = cv2.approxPolyDP(contour, epsilon, True)
        if contour.shape[0] < 3:
            continue
        points = [PolygonPoint(x=int(point[0][0]), y=int(point[0][1])) for point in contour]
        segmentations.append(Segmentation(points=points))
    return segmentations


def hu_stack_to_viewer_frames(
    hu: np.ndarray,
    slice_paths: tuple[Path, ...],
    *,
    reference_ds: Dataset | None = None,
    frame_dtype: np.dtype | None = None,
) -> np.ndarray:
    """Convert an HU stack to per-slice frames for ``ImageViewer`` / ``save_series_frames``.

    Integer ``frame_dtype`` returns stored pixels (DICOM encoding). Floating ``frame_dtype``
    returns HU values in the same space as ``load_series_frames`` (post-modality-LUT floats).
    """
    if hu.shape[0] != len(slice_paths):
        raise ValueError(f"HU stack depth {hu.shape[0]} != slice count {len(slice_paths)}")

    if reference_ds is not None and frame_dtype is not None:
        frames: list[np.ndarray] = []
        for index in range(hu.shape[0]):
            source_path = slice_paths[index]
            source_ds = dcmread(str(source_path))
            stored_dtype = source_ds.pixel_array.dtype
            slice_slope = float(getattr(source_ds, "RescaleSlope", 1) or 1)
            slice_intercept = float(getattr(source_ds, "RescaleIntercept", 0) or 0)
            if slice_slope in (0, 0.0):
                slice_slope = 1.0
            stored = hu_slice_to_stored_pixels(
                hu[index],
                rescale_slope=slice_slope,
                rescale_intercept=slice_intercept,
                dtype=stored_dtype,
            )
            if np.issubdtype(frame_dtype, np.floating):
                frames.append(stored.astype(np.float32) * slice_slope + slice_intercept)
            else:
                frames.append(stored.astype(frame_dtype, copy=False))
        return np.stack(frames, axis=0)

    frames = []
    for index, source_path in enumerate(slice_paths):
        ds = dcmread(str(source_path))
        source_dtype = ds.pixel_array.dtype
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        stored = hu_slice_to_stored_pixels(
            hu[index],
            rescale_slope=slope,
            rescale_intercept=intercept,
            dtype=source_dtype,
        )
        frames.append(stored)
    return np.stack(frames, axis=0)


def preview_blurred_slice_frames(
    preview: FaceBlurPreviewResult,
    *,
    reference_ds: Dataset | None = None,
    frame_dtype: np.dtype | None = None,
) -> np.ndarray:
    """Return the blurred slice stack from a face blur preview result."""
    if preview.blurred_slice_frames is not None:
        return preview.blurred_slice_frames
    if preview.hu_after is not None:
        return hu_stack_to_viewer_frames(
            preview.hu_after,
            preview.slice_paths,
            reference_ds=reference_ds,
            frame_dtype=frame_dtype,
        )
    raise ValueError("Face blur preview has no blurred slice data")


def apply_face_blur_preview_to_series_frames(
    frames: np.ndarray,
    preview: FaceBlurPreviewResult,
    *,
    single_frame: bool,
    reference_ds: Dataset | None = None,
    frame_dtype: np.dtype | None = None,
) -> np.ndarray:
    """Merge accepted blur preview into a SeriesView frame stack (slices only; projections unchanged)."""
    blurred_slices = preview_blurred_slice_frames(
        preview,
        reference_ds=reference_ds,
        frame_dtype=frame_dtype,
    )
    updated = frames.copy()
    slice_offset = 0 if single_frame else 3
    end = slice_offset + blurred_slices.shape[0]
    if end > updated.shape[0]:
        raise ValueError(
            f"Blurred slice count {blurred_slices.shape[0]} exceeds SeriesView frame slots "
            f"({updated.shape[0] - slice_offset} slices available)"
        )
    updated[slice_offset:end] = blurred_slices
    return updated


def _report_face_blur_progress(
    callback: FaceBlurProgressCallback | None,
    *,
    stage: str,
    message: str,
    fraction: float,
) -> None:
    if callback is None:
        return
    callback(
        FaceBlurProgress(
            stage=stage,
            message=message,
            fraction=min(1.0, max(0.0, fraction)),
        )
    )


def _preview_error(
    series_directory: Path,
    *,
    slice_paths: tuple[Path, ...] = (),
    error: str,
) -> FaceBlurPreviewResult:
    empty = np.empty(0)
    return FaceBlurPreviewResult(
        series_directory=Path(series_directory),
        face_mask_path=None,
        slice_paths=slice_paths,
        mask=empty,
        slice_count=len(slice_paths),
        qa_stats=None,
        sigma_mm=DEFAULT_FACE_BLUR_SIGMA_MM,
        blur_mode=DEFAULT_FACE_BLUR_MODE,
        pixel_spacing_mm=(1.0, 1.0),
        error=error,
    )


def preview_face_blur(
    series_directory: Path,
    *,
    sigma_mm: float = DEFAULT_FACE_BLUR_SIGMA_MM,
    blur_mode: FaceBlurMode | str = DEFAULT_FACE_BLUR_MODE,
    run_segmentation_if_missing: bool = True,
    force_segmentation: bool = False,
    volume_context: SeriesVolumeContext | None = None,
    progress: FaceBlurProgressCallback | None = None,
) -> FaceBlurPreviewResult:
    """
    Segment face (when needed), blur in-mask HU voxels, and return an in-memory preview.

    Does not write DICOM. Use ``apply_face_blur_preview_to_series_frames`` after user accept.
    """
    series_directory = Path(series_directory).resolve()
    from anonymizer.controller.ai.tseg.modality_profile import (
        ct_modality_profile,
        resolve_profile_for_series,
    )

    profile = resolve_profile_for_series(series_directory) or ct_modality_profile()
    _report_face_blur_progress(
        progress,
        stage="mask",
        message="Resolving face segmentation mask",
        fraction=0.05,
    )

    try:
        mask_path = resolve_face_mask_path(
            series_directory,
            run_if_missing=run_segmentation_if_missing,
            force_segmentation=force_segmentation,
            profile=profile,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("Face blur preview: mask resolution failed for %s: %s", series_directory, exc)
        return _preview_error(series_directory, error=str(exc))

    _report_face_blur_progress(
        progress,
        stage="volume",
        message="Loading CT volume and aligning face mask"
        if profile.modality == "CT"
        else "Loading volume and aligning face mask",
        fraction=0.25,
    )

    try:
        if volume_context is not None:
            slice_paths = volume_context.slice_paths
            if volume_context.slice_frames.shape[0] != len(slice_paths):
                message = (
                    f"Preloaded slice count {volume_context.slice_frames.shape[0]} != path count {len(slice_paths)}"
                )
                return _preview_error(series_directory, slice_paths=slice_paths, error=message)
            volume_img = build_sitk_volume_from_series_frames(
                volume_context.reference_ds,
                volume_context.slice_frames,
                slice_paths,
                slice_spacing_mm=volume_context.slice_spacing_mm,
            )
            hu_before = hu_stack_from_series_frames(volume_context.slice_frames)
            logger.info(
                "Face blur: using %d preloaded Series View slice(s) for %s",
                len(slice_paths),
                series_directory,
            )
        else:
            volume_img, hu_before, slice_paths = load_series_volume_for_blur(series_directory)
        mask_img = align_mask_to_volume(mask_path, volume_img)
        mask = mask_array_from_volume(mask_img)
        face_voxels = int(mask.sum())
        if not face_mask_is_substantial(face_voxels):
            message = face_blur_gate_message(FaceBlurGateReason.INSUFFICIENT_FACE_MASK)
            logger.warning(
                "Face blur preview: insufficient face voxels (%d) for %s",
                face_voxels,
                series_directory,
            )
            return _preview_error(series_directory, slice_paths=slice_paths, error=message)

        _report_face_blur_progress(
            progress,
            stage="load_hu",
            message="Loading Hounsfield unit stack",
            fraction=0.45,
        )
        if hu_before.shape != mask.shape:
            message = f"HU stack shape {hu_before.shape} != mask shape {mask.shape} after alignment"
            return _preview_error(series_directory, slice_paths=slice_paths, error=message)

        spacing = volume_img.GetSpacing()
        pixel_spacing_mm = (float(spacing[1]), float(spacing[0]))

        _report_face_blur_progress(
            progress,
            stage="blur",
            message=f"Applying in-mask {FaceBlurMode(blur_mode).value} de-identification",
            fraction=0.65,
        )
        hu_after = blur_face_volume_for_profile(
            hu_before,
            mask,
            profile=profile,
            sigma_mm=sigma_mm,
            blur_mode=blur_mode,
            pixel_spacing_mm=pixel_spacing_mm,
        )

        _report_face_blur_progress(
            progress,
            stage="qa",
            message="Checking pixels outside face mask",
            fraction=0.9,
        )
        stats = compute_qa_stats(hu_before, hu_after, mask)
        if not stats.outside_clean:
            logger.warning("Face blur preview: QA FAIL — blur changed voxels outside face mask")

        blurred_slice_frames: np.ndarray | None = None
        hu_after_for_result: np.ndarray | None = hu_after
        if volume_context is not None:
            blurred_slice_frames = hu_stack_to_viewer_frames(
                hu_after,
                slice_paths,
                reference_ds=volume_context.reference_ds,
                frame_dtype=volume_context.slice_frames.dtype,
            )
            hu_after_for_result = None

        _report_face_blur_progress(
            progress,
            stage="done",
            message="Face blur preview ready",
            fraction=1.0,
        )
        return FaceBlurPreviewResult(
            series_directory=series_directory,
            face_mask_path=mask_path,
            slice_paths=slice_paths,
            mask=mask,
            slice_count=len(slice_paths),
            qa_stats=stats,
            sigma_mm=sigma_mm,
            blur_mode=FaceBlurMode(blur_mode),
            pixel_spacing_mm=pixel_spacing_mm,
            hu_after=hu_after_for_result,
            blurred_slice_frames=blurred_slice_frames,
        )
    except Exception as exc:
        logger.exception("Face blur preview failed for %s", series_directory)
        return _preview_error(
            series_directory,
            slice_paths=slice_paths if "slice_paths" in locals() else (),
            error=f"{type(exc).__name__}: {exc}",
        )


# --- Derived DICOM export ---------------------------------------------------


def hu_slice_to_stored_pixels(
    hu_slice: np.ndarray,
    *,
    rescale_slope: float,
    rescale_intercept: float,
    dtype: np.dtype,
) -> np.ndarray:
    """Convert HU back to stored DICOM pixels using the source slice rescale tags."""
    slope = rescale_slope if rescale_slope not in (0, 0.0) else 1.0
    stored = (hu_slice - rescale_intercept) / slope
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        return np.clip(np.rint(stored), info.min, info.max).astype(dtype)
    return stored.astype(dtype)


_UTF8_CHARACTER_SET = "ISO_IR 192"


def _ensure_utf8_character_set(ds: Dataset) -> None:
    """Declare UTF-8 before writing derived text (e.g. em dash in series description)."""
    ds.SpecificCharacterSet = _UTF8_CHARACTER_SET


def _prepare_output_directory(output_directory: Path) -> int:
    output_directory.mkdir(parents=True, exist_ok=True)
    removed = 0
    for path in output_directory.iterdir():
        if path.is_file() and path.suffix.lower() in {".dcm", ".dicom"}:
            path.unlink()
            removed += 1
    return removed


def write_blurred_dicom_series(
    hu: np.ndarray,
    slice_paths: tuple[Path, ...],
    output_directory: Path,
    *,
    series_description_suffix: str = " — face blurred",
) -> tuple[Path, ...]:
    """
    Write ``hu`` as a DICOM series in the same patient space as ``slice_paths``.

    Each output slice copies geometry and pixel encoding from the matching source slice,
    assigns new Series/SOP Instance UIDs, and updates ``SeriesDescription``.
    """
    if hu.shape[0] != len(slice_paths):
        raise ValueError(f"HU stack depth {hu.shape[0]} != slice count {len(slice_paths)}")

    output_directory = Path(output_directory).resolve()
    removed = _prepare_output_directory(output_directory)
    if removed:
        logger.info("Face blur: cleared %d existing DICOM file(s) in %s", removed, output_directory)

    series_uid = generate_uid()
    logger.info(
        "Face blur: writing %d blurred slice(s) → %s (SeriesInstanceUID=%s)",
        len(slice_paths),
        output_directory,
        series_uid,
    )
    written: list[Path] = []
    for z, source_path in enumerate(slice_paths):
        ds = pydicom.dcmread(str(source_path))
        source_dtype = ds.pixel_array.dtype
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        stored = hu_slice_to_stored_pixels(
            hu[z],
            rescale_slope=slope,
            rescale_intercept=intercept,
            dtype=source_dtype,
        )

        ds.SeriesInstanceUID = series_uid
        ds.SOPInstanceUID = generate_uid()
        if hasattr(ds, "SeriesDescription"):
            base = str(ds.SeriesDescription).rstrip()
            ds.SeriesDescription = f"{base}{series_description_suffix}"
        else:
            ds.SeriesDescription = "Face blurred"
        if hasattr(ds, "ImageType"):
            image_type = list(getattr(ds, "ImageType", []))
            if image_type:
                image_type[0] = "DERIVED"
                if len(image_type) > 1:
                    image_type[1] = "SECONDARY"
                ds.ImageType = image_type

        ds.PixelData = stored.tobytes()
        _ensure_utf8_character_set(ds)
        out_path = output_directory / f"{ds.SOPInstanceUID}.dcm"
        ds.save_as(str(out_path))
        written.append(out_path)

    if not written:
        raise RuntimeError(f"No DICOM slices written to {output_directory}")
    logger.info("Face blur: wrote %d DICOM slice(s) to %s", len(written), output_directory)
    return tuple(written)


# --- Public orchestration ---------------------------------------------------


def _error_result(series_directory: Path, output_directory: Path, error: str) -> FaceBlurResult:
    return FaceBlurResult(
        series_directory=Path(series_directory),
        output_directory=output_directory,
        face_mask_path=None,
        slice_count=0,
        qa_stats=None,
        error=error,
    )


def blur_face_series(
    series_directory: Path,
    *,
    output_directory: Path | None = None,
    sigma_mm: float = DEFAULT_FACE_BLUR_SIGMA_MM,
    blur_mode: FaceBlurMode | str = DEFAULT_FACE_BLUR_MODE,
    run_segmentation_if_missing: bool = True,
    force_segmentation: bool = False,
    progress: FaceBlurProgressCallback | None = None,
) -> FaceBlurResult:
    """
    Segment face (when needed), blur in-mask HU voxels, and write derived DICOM.

    Reads/writes under ``series_directory``; default output is ``face_blurred/``.
    """
    series_directory = Path(series_directory).resolve()
    out_dir = (
        Path(output_directory).resolve()
        if output_directory is not None
        else series_directory / DEFAULT_FACE_BLUR_OUTPUT_DIRNAME
    )

    preview = preview_face_blur(
        series_directory,
        sigma_mm=sigma_mm,
        blur_mode=blur_mode,
        run_segmentation_if_missing=run_segmentation_if_missing,
        force_segmentation=force_segmentation,
        progress=progress,
    )
    if preview.error is not None:
        return _error_result(series_directory, out_dir, preview.error)
    if preview.hu_after is None:
        return _error_result(series_directory, out_dir, "Face blur preview missing HU export stack")

    try:
        write_blurred_dicom_series(preview.hu_after, preview.slice_paths, out_dir)
    except Exception as exc:
        logger.exception("Face blur: export failed for %s", series_directory)
        return _error_result(series_directory, out_dir, f"{type(exc).__name__}: {exc}")

    logger.info(
        "Face blur: complete for %s — %d slices, mask=%s, output=%s",
        series_directory,
        preview.slice_count,
        preview.face_mask_path,
        out_dir,
    )
    return FaceBlurResult(
        series_directory=series_directory,
        output_directory=out_dir,
        face_mask_path=preview.face_mask_path,
        slice_count=preview.slice_count,
        qa_stats=preview.qa_stats,
    )


def apply_series_face_blur_metadata(anon_model, anon_series_uid: str, algorithm: str) -> bool:
    """Record the face blur algorithm applied to a series in the project database."""
    return anon_model.set_series_face_blur_algorithm(anon_series_uid, algorithm)
