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
from pathlib import Path

import cv2
import numpy as np
import pydicom
import SimpleITK as sitk
from pydicom import Dataset, dcmread
from pydicom.uid import generate_uid

from anonymizer.controller.blur_face_gate import (
    FaceBlurGateReason,
    face_blur_gate_message,
    face_mask_is_substantial,
)
from anonymizer.controller.create_projections import load_series_frames
from anonymizer.controller.remove_pixel_phi import PolygonPoint, Segmentation
from anonymizer.controller.tseg.config import FACE_MASK_FILENAME
from anonymizer.controller.tseg.dicom_geometry import build_sitk_volume_from_series_frames
from anonymizer.controller.tseg.segment import (
    analyze_tseg_face,
    count_mask_voxels,
    face_mask_cache_path,
    invalidate_stale_tseg_volume_cache,
    series_cache_dir,
)

logger = logging.getLogger(__name__)

# --- Config -----------------------------------------------------------------

DEFAULT_FACE_BLUR_OUTPUT_DIRNAME = "face_blurred"

# Primary user-facing control: approximate Gaussian standard deviation in millimetres
# (full width at half maximum ≈ 2.355 × sigma_mm for each in-plane axis).
DEFAULT_FACE_BLUR_SIGMA_MM = 8.0

# Minimum pixel sigma passed to OpenCV when spacing is very fine or sigma_mm is small.
MIN_FACE_BLUR_SIGMA_PX = 0.5

LEGACY_FACE_MASK_REL = Path("ts_seg") / FACE_MASK_FILENAME

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
) -> Path:
    """
    Return the face mask NIfTI for ``series_directory``.

    Prefer ``<series>/A_TS_SEG/seg/face.nii.gz``. Fall back to legacy
    ``<series>/ts_seg/face.nii.gz`` with a deprecation warning. When no mask
    exists and ``run_if_missing`` is true, run ``analyze_tseg_face``.
    """
    series_directory = Path(series_directory).resolve()
    cache_path = face_mask_cache_path(series_directory)
    legacy_path = series_directory / LEGACY_FACE_MASK_REL
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

    if legacy_path.is_file() and not cache_path.is_file() and not force_segmentation:
        face_voxels = count_mask_voxels(legacy_path)
        if not face_mask_is_substantial(face_voxels):
            raise RuntimeError(face_blur_gate_message(FaceBlurGateReason.INSUFFICIENT_FACE_MASK))
        logger.warning(
            "Using legacy face mask at %s; new cache path is %s. "
            "Re-run face segmentation to migrate. Legacy lookup will be removed in a follow-up.",
            legacy_path,
            cache_path,
        )
        return legacy_path

    if not run_if_missing:
        raise FileNotFoundError(
            f"Face mask not found at {cache_path} (or legacy {legacy_path}). "
            "Run face segmentation first (ts_seg_face.py or analyze_tseg_face)."
        )

    if force_segmentation:
        logger.info("Face blur: force_segmentation=True; running analyze_tseg_face for %s", series_directory)
    else:
        logger.info("Face blur: mask missing; running analyze_tseg_face for %s", series_directory)
    result = analyze_tseg_face(series_directory, force=force_segmentation)
    if result.error is not None:
        raise RuntimeError(result.error)
    if result.face_mask_path is None or not result.face_mask_path.is_file():
        raise FileNotFoundError(
            f"analyze_tseg_face completed without writing a mask for {series_directory}"
        )
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
    hu = frames.astype(np.float64)
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
    reference_ds, frames, slice_paths = load_series_frames(series_directory)
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
        pixels = ds.pixel_array.astype(np.float64)
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        slices.append(pixels * slope + intercept)
    stack = np.stack(slices, axis=0)
    logger.info(
        "Face blur: loaded HU stack shape=%s range=[%.1f, %.1f]",
        stack.shape,
        float(stack.min()),
        float(stack.max()),
    )
    return stack


# --- In-mask blur -----------------------------------------------------------


def blur_face_hu_volume(
    hu: np.ndarray,
    mask: np.ndarray,
    *,
    sigma_mm: float = DEFAULT_FACE_BLUR_SIGMA_MM,
    pixel_spacing_mm: tuple[float, float] = (1.0, 1.0),
    min_sigma_px: float = MIN_FACE_BLUR_SIGMA_PX,
) -> np.ndarray:
    """
    In-plane Gaussian blur inside ``mask`` only; voxels outside ``mask`` unchanged.

    ``hu`` and ``mask`` shape: (Z, Y, X).
    """
    if hu.shape != mask.shape:
        raise ValueError(f"HU shape {hu.shape} != mask shape {mask.shape}")

    row_spacing, col_spacing = pixel_spacing_mm
    sigma_y = max(sigma_mm / row_spacing, min_sigma_px)
    sigma_x = max(sigma_mm / col_spacing, min_sigma_px)
    logger.info(
        "Face blur: Gaussian blur sigma_mm=%.2f → sigma_px=(%.2f, %.2f) spacing_mm=(%.3f, %.3f)",
        sigma_mm,
        sigma_x,
        sigma_y,
        row_spacing,
        col_spacing,
    )

    out = hu.copy()
    face = mask.astype(bool)
    slices_with_face = 0
    for z in range(hu.shape[0]):
        slice_mask = face[z]
        if not slice_mask.any():
            continue
        slices_with_face += 1
        blurred = cv2.GaussianBlur(
            hu[z].astype(np.float32),
            ksize=(0, 0),
            sigmaX=sigma_x,
            sigmaY=sigma_y,
        )
        out[z] = np.where(slice_mask, blurred, hu[z])
    logger.info(
        "Face blur: blurred %d / %d axial slices (%d face voxels)",
        slices_with_face,
        hu.shape[0],
        int(face.sum()),
    )
    return out


# --- QA ---------------------------------------------------------------------


def compute_qa_stats(hu_before: np.ndarray, hu_after: np.ndarray, mask: np.ndarray) -> QaStats:
    """Quantify whether any voxels outside the face mask changed."""
    face = mask.astype(bool)
    outside = ~face
    diff = np.abs(hu_after.astype(np.float64) - hu_before.astype(np.float64))

    outside_diff = diff[outside]
    inside_diff = diff[face]

    n_violating = int(np.sum(outside_diff > 0)) if outside_diff.size else 0
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
    smooth_sigma: float = 1.5,
    contour_epsilon_ratio: float = 0.002,
) -> list[Segmentation]:
    """Extract smoothed face-mask contours for one axial slice (viewer overlay polygons)."""
    if slice_index < 0 or slice_index >= mask.shape[0]:
        return []
    slice_mask = (mask[slice_index] > 0).astype(np.uint8)
    if not slice_mask.any():
        return []

    if smooth_sigma > 0:
        blurred = cv2.GaussianBlur(slice_mask.astype(np.float32), (0, 0), smooth_sigma)
        slice_mask = (blurred >= 0.5).astype(np.uint8)

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
    """Convert an HU stack to per-slice stored-pixel frames for ``ImageViewer``."""
    if hu.shape[0] != len(slice_paths):
        raise ValueError(f"HU stack depth {hu.shape[0]} != slice count {len(slice_paths)}")

    if reference_ds is not None and frame_dtype is not None:
        slope = float(getattr(reference_ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(reference_ds, "RescaleIntercept", 0) or 0)
        if slope in (0, 0.0):
            slope = 1.0
        return np.stack(
            [
                hu_slice_to_stored_pixels(
                    hu[index],
                    rescale_slope=slope,
                    rescale_intercept=intercept,
                    dtype=frame_dtype,
                )
                for index in range(hu.shape[0])
            ],
            axis=0,
        )

    frames: list[np.ndarray] = []
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


def apply_face_blur_preview_to_series_frames(
    frames: np.ndarray,
    preview: FaceBlurPreviewResult,
    *,
    single_frame: bool,
    reference_ds: Dataset | None = None,
    frame_dtype: np.dtype | None = None,
) -> np.ndarray:
    """Merge accepted blur preview into a SeriesView frame stack (slices only; projections unchanged)."""
    if preview.blurred_slice_frames is not None:
        blurred_slices = preview.blurred_slice_frames
    elif preview.hu_after is not None:
        blurred_slices = hu_stack_to_viewer_frames(
            preview.hu_after,
            preview.slice_paths,
            reference_ds=reference_ds,
            frame_dtype=frame_dtype,
        )
    else:
        raise ValueError("Face blur preview has no blurred slice data")
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
        pixel_spacing_mm=(1.0, 1.0),
        error=error,
    )


def preview_face_blur(
    series_directory: Path,
    *,
    sigma_mm: float = DEFAULT_FACE_BLUR_SIGMA_MM,
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
        )
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("Face blur preview: mask resolution failed for %s: %s", series_directory, exc)
        return _preview_error(series_directory, error=str(exc))

    _report_face_blur_progress(
        progress,
        stage="volume",
        message="Loading CT volume and aligning face mask",
        fraction=0.25,
    )

    try:
        if volume_context is not None:
            slice_paths = volume_context.slice_paths
            if volume_context.slice_frames.shape[0] != len(slice_paths):
                message = (
                    f"Preloaded slice count {volume_context.slice_frames.shape[0]} "
                    f"!= path count {len(slice_paths)}"
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
            message="Applying in-mask Gaussian blur",
            fraction=0.65,
        )
        hu_after = blur_face_hu_volume(
            hu_before,
            mask,
            sigma_mm=sigma_mm,
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
