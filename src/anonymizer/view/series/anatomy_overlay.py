"""Convert TotalSegmentator anatomy NIfTI masks into series overlay polygons."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import cv2
import numpy as np
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.config import (
    MIN_STRUCTURE_VOXELS,
    PRIMARY_SEGMENT_GROUPS,
    PRIMARY_SEGMENT_ORDER,
    PRIMARY_SEGMENT_PREFERRED_FILES,
    ROI_SUBSET,
)
from anonymizer.controller.series_overlay import PolygonPoint, Segmentation

# Distinct saturated BGR colors for latch overlays (visually separable on CT).
PRIMARY_SEGMENT_COLORS_BGR: dict[str, tuple[int, int, int]] = {
    "brain": (255, 180, 0),  # azure / bright blue
    "brainstem": (0, 140, 255),  # orange
    "subarachnoid_space": (200, 180, 100),
    "venous_sinuses": (40, 40, 220),
    "septum_pellucidum": (180, 220, 180),
    "cerebellum": (80, 200, 255),
    "caudate_nucleus": (255, 140, 80),
    "lentiform_nucleus": (160, 80, 255),
    "insular_cortex": (80, 200, 160),
    "internal_capsule": (200, 120, 200),
    "ventricle": (0, 255, 255),  # yellow
    "central_sulcus": (120, 120, 255),
    "frontal_lobe": (50, 200, 50),
    "parietal_lobe": (50, 200, 220),
    "occipital_lobe": (200, 100, 50),
    "temporal_lobe": (180, 80, 180),
    "thalamus": (100, 100, 220),
    "skull": (0, 220, 255),  # gold / amber
    "spinal_cord": (0, 200, 80),  # green
    "spine": (200, 0, 220),  # magenta
    "clavicles": (75, 86, 140),
    "ribs": (194, 119, 227),
    "heart": (40, 39, 214),  # red
    "trachea": (120, 187, 255),
    "lungs": (44, 160, 44),
    "liver": (14, 127, 255),
    "spleen": (34, 189, 188),
    "kidneys": (207, 190, 23),
    "stomach": (232, 199, 174),
    "pancreas": (150, 152, 255),
}

_DEFAULT_STRUCTURE_COLOR_BGR = (0, 165, 255)
# Soften mask edges before contouring so outlines are not pixel-stair jagged.
_ANATOMY_MASK_SMOOTH_SIGMA_PX = 1.8
_ANATOMY_CONTOUR_EPSILON_RATIO = 0.0
_ANATOMY_CONTOUR_SMOOTH_WINDOW = 7


def bgr_to_hex(color_bgr: tuple[int, int, int]) -> str:
    b, g, r = color_bgr
    return f"#{r:02x}{g:02x}{b:02x}"


def order_structures_by_voxels(structures_present: dict[str, int]) -> list[tuple[str, int]]:
    """Sort by voxel count descending; ties keep PRIMARY_SEGMENT_ORDER."""
    order_index = {name: i for i, name in enumerate(PRIMARY_SEGMENT_ORDER)}
    return sorted(
        structures_present.items(),
        key=lambda item: (-item[1], order_index.get(item[0], 999), item[0]),
    )


def color_bgr_for_structure(structure_name: str) -> tuple[int, int, int]:
    return PRIMARY_SEGMENT_COLORS_BGR.get(structure_name, _DEFAULT_STRUCTURE_COLOR_BGR)


def ensure_roi_palette_complete() -> None:
    """Raise if primary groups / ROI files drift from the palette or group map."""
    missing_primary = [name for name in PRIMARY_SEGMENT_ORDER if name not in PRIMARY_SEGMENT_COLORS_BGR]
    if missing_primary:
        raise RuntimeError(f"PRIMARY_SEGMENT_COLORS_BGR missing entries for: {missing_primary}")
    covered: set[str] = set()
    for files in PRIMARY_SEGMENT_GROUPS.values():
        covered.update(files)
    missing_files = [name for name in ROI_SUBSET if name not in covered]
    if missing_files:
        raise RuntimeError(f"PRIMARY_SEGMENT_GROUPS do not cover ROI_SUBSET: {missing_files}")
    colors = list(PRIMARY_SEGMENT_COLORS_BGR.values())
    if len(colors) != len(set(colors)):
        raise RuntimeError("PRIMARY_SEGMENT_COLORS_BGR has duplicate colors")


def structure_button_label(structure_name: str) -> str:
    """Short label for latch buttons (underscores → spaces)."""
    return structure_name.replace("_", " ")


def latch_button_width_px(label: str) -> int:
    """Compact CTk button width fitting the label text."""
    return max(36, len(label) * 7 + 18)


def resolve_primary_segment_files(seg_dir: Path, group_name: str) -> tuple[str, ...]:
    """Prefer a on-disk super-segment when configured; else the multi-file group list.

    MR ``total_mr`` writes combined ``vertebrae`` / whole-lung masks instead of CT
    per-vertebra and lobe files; detect those when the CT multi-file packs are absent.
    """
    fallback = PRIMARY_SEGMENT_GROUPS.get(group_name)
    if not fallback:
        raise KeyError(f"Unknown primary segment group: {group_name}")
    preferred = PRIMARY_SEGMENT_PREFERRED_FILES.get(group_name)
    if preferred and all((seg_dir / f"{stem}.nii.gz").is_file() for stem in preferred):
        return preferred

    if group_name == "spine" and (seg_dir / "vertebrae.nii.gz").is_file():
        has_ct_vertebrae = any(
            stem.startswith("vertebrae_") and (seg_dir / f"{stem}.nii.gz").is_file() for stem in fallback
        )
        if not has_ct_vertebrae:
            stems = ["vertebrae"]
            if (seg_dir / "sacrum.nii.gz").is_file():
                stems.append("sacrum")
            return tuple(stems)

    if group_name == "lungs":
        has_lobe = any((seg_dir / f"{stem}.nii.gz").is_file() for stem in fallback)
        if not has_lobe:
            mr_lungs = tuple(
                stem for stem in ("lung_left", "lung_right") if (seg_dir / f"{stem}.nii.gz").is_file()
            )
            if mr_lungs:
                return mr_lungs

    return fallback


def collect_primary_segment_voxels(
    seg_dir: Path,
    *,
    min_voxels: int = MIN_STRUCTURE_VOXELS,
) -> dict[str, int]:
    """Sum voxels across TS files for each primary UI group (bilateral / multi-part merged)."""
    present: dict[str, int] = {}
    for group_name in PRIMARY_SEGMENT_GROUPS:
        files = resolve_primary_segment_files(seg_dir, group_name)
        total = 0
        for file_stem in files:
            mask_path = seg_dir / f"{file_stem}.nii.gz"
            if not mask_path.is_file():
                continue
            image = sitk.ReadImage(str(mask_path))
            try:
                array = sitk.GetArrayFromImage(image)
                total += int((array > 0).sum())
            finally:
                del image
        if total >= min_voxels:
            present[group_name] = total
    return present


def _geometry_matches(a: sitk.Image, b: sitk.Image) -> bool:
    return (
        a.GetSize() == b.GetSize()
        and a.GetSpacing() == b.GetSpacing()
        and a.GetOrigin() == b.GetOrigin()
        and a.GetDirection() == b.GetDirection()
    )


def resample_mask_to_reference(mask: sitk.Image, reference: sitk.Image) -> sitk.Image:
    """Nearest-neighbor resample so mask voxels align with the Series View CT volume."""
    if _geometry_matches(mask, reference):
        return mask
    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(reference)
    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
    resampler.SetDefaultPixelValue(0)
    return resampler.Execute(mask)


def _mask_array_from_image(
    image: sitk.Image,
    *,
    reference: sitk.Image | None = None,
) -> np.ndarray:
    if reference is not None:
        image = resample_mask_to_reference(image, reference)
    array = sitk.GetArrayFromImage(image)
    return (array > 0).astype(np.uint8)


def load_structure_mask_array(
    mask_path: Path,
    *,
    reference_volume_path: Path | None = None,
    reference_image: sitk.Image | None = None,
) -> np.ndarray:
    """Load a binary-ish mask volume as ``(Z, Y, X)`` uint8 (0/1), aligned to CT when possible."""
    image = sitk.ReadImage(str(mask_path))
    try:
        reference = reference_image
        owned_reference = False
        if reference is None and reference_volume_path is not None and Path(reference_volume_path).is_file():
            reference = sitk.ReadImage(str(reference_volume_path))
            owned_reference = True
        try:
            return _mask_array_from_image(image, reference=reference)
        finally:
            if owned_reference and reference is not None:
                del reference
    finally:
        del image


def load_primary_segment_mask(
    seg_dir: Path,
    group_name: str,
    *,
    reference_volume_path: Path | None = None,
) -> np.ndarray:
    """Union preferred or fallback TS masks for a primary group into one binary volume."""
    files = resolve_primary_segment_files(seg_dir, group_name)
    if reference_volume_path is None:
        candidate = seg_dir.parent / "volume.nii.gz"
        reference_volume_path = candidate if candidate.is_file() else None

    reference: sitk.Image | None = None
    try:
        if reference_volume_path is not None and Path(reference_volume_path).is_file():
            reference = sitk.ReadImage(str(reference_volume_path))
        combined: np.ndarray | None = None
        for file_stem in files:
            mask_path = seg_dir / f"{file_stem}.nii.gz"
            if not mask_path.is_file():
                continue
            image = sitk.ReadImage(str(mask_path))
            try:
                part = _mask_array_from_image(image, reference=reference)
            finally:
                del image
            combined = part if combined is None else np.maximum(combined, part)
        if combined is None:
            raise FileNotFoundError(f"No masks found for primary segment {group_name!r} under {seg_dir}")
        return combined
    finally:
        if reference is not None:
            del reference


def _smooth_binary_slice(slice_mask: np.ndarray, *, smooth_sigma: float) -> np.ndarray:
    """Gaussian-smooth a binary mask slice and re-threshold for softer contours."""
    binary = (slice_mask > 0).astype(np.float32)
    if not binary.any() or smooth_sigma <= 0:
        return (binary > 0).astype(np.uint8)
    blurred = cv2.GaussianBlur(binary, (0, 0), smooth_sigma)
    return (blurred >= 0.5).astype(np.uint8)


def _smooth_closed_contour(
    contour: np.ndarray,
    *,
    window: int = _ANATOMY_CONTOUR_SMOOTH_WINDOW,
) -> np.ndarray:
    """Moving-average smooth a closed OpenCV contour to reduce pixel stair-steps."""
    if window < 3 or contour.shape[0] < window:
        return contour
    if window % 2 == 0:
        window += 1
    pts = contour.reshape(-1, 2).astype(np.float64)
    pad = window // 2
    wrapped = np.concatenate([pts[-pad:], pts, pts[:pad]], axis=0)
    kernel = np.ones(window, dtype=np.float64) / float(window)
    xs = np.convolve(wrapped[:, 0], kernel, mode="valid")
    ys = np.convolve(wrapped[:, 1], kernel, mode="valid")
    smoothed = np.stack([xs, ys], axis=1)
    return np.round(smoothed).astype(np.int32).reshape(-1, 1, 2)


def mask_slice_to_segmentations(
    slice_mask: np.ndarray,
    *,
    structure_name: str,
    color_bgr: tuple[int, int, int],
    contour_epsilon_ratio: float = _ANATOMY_CONTOUR_EPSILON_RATIO,
    smooth_sigma: float = _ANATOMY_MASK_SMOOTH_SIGMA_PX,
    contour_smooth_window: int = _ANATOMY_CONTOUR_SMOOTH_WINDOW,
) -> list[Segmentation]:
    """Contour a single axial binary mask slice."""
    if not np.any(slice_mask):
        return []
    smoothed = _smooth_binary_slice(slice_mask, smooth_sigma=smooth_sigma)
    if not np.any(smoothed):
        return []
    contours, _ = cv2.findContours(
        np.ascontiguousarray(smoothed),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    segmentations: list[Segmentation] = []
    for contour in contours:
        if contour.shape[0] < 3:
            continue
        contour = _smooth_closed_contour(contour, window=contour_smooth_window)
        if contour_epsilon_ratio > 0:
            epsilon = contour_epsilon_ratio * cv2.arcLength(contour, True)
            contour = cv2.approxPolyDP(contour, epsilon, True)
        if contour.shape[0] < 3:
            continue
        points = [PolygonPoint(x=int(point[0][0]), y=int(point[0][1])) for point in contour]
        segmentations.append(Segmentation(points=points, color_bgr=color_bgr, structure_name=structure_name))
    return segmentations


def contour_mask_slice(
    mask: np.ndarray,
    slice_index: int,
    *,
    structure_name: str,
    color_bgr: tuple[int, int, int],
) -> list[Segmentation]:
    """Contour one Z slice of a 3D mask (empty list if out of range or empty)."""
    if mask.ndim != 3:
        raise ValueError(f"Expected 3D mask, got shape {mask.shape}")
    if slice_index < 0 or slice_index >= mask.shape[0]:
        return []
    return mask_slice_to_segmentations(
        mask[slice_index],
        structure_name=structure_name,
        color_bgr=color_bgr,
    )


def contour_mask_slices(
    mask: np.ndarray,
    slice_indices: Iterable[int],
    *,
    structure_name: str,
    color_bgr: tuple[int, int, int],
    should_cancel: Callable[[], bool] | None = None,
) -> dict[int, list[Segmentation]]:
    """Contour selected Z slices; skip empties; stop early when ``should_cancel`` is true."""
    if mask.ndim != 3:
        raise ValueError(f"Expected 3D mask, got shape {mask.shape}")
    by_slice: dict[int, list[Segmentation]] = {}
    for slice_index in slice_indices:
        if should_cancel is not None and should_cancel():
            break
        if slice_index < 0 or slice_index >= mask.shape[0]:
            continue
        segs = mask_slice_to_segmentations(
            mask[slice_index],
            structure_name=structure_name,
            color_bgr=color_bgr,
        )
        if segs:
            by_slice[slice_index] = segs
    return by_slice


def mask_volume_to_slice_segmentations(
    mask: np.ndarray,
    *,
    structure_name: str,
    color_bgr: tuple[int, int, int],
    contour_epsilon_ratio: float = _ANATOMY_CONTOUR_EPSILON_RATIO,
    smooth_sigma: float = _ANATOMY_MASK_SMOOTH_SIGMA_PX,
    contour_smooth_window: int = _ANATOMY_CONTOUR_SMOOTH_WINDOW,
) -> dict[int, list[Segmentation]]:
    """Contour every axial slice; empty slices omitted from the dict.

    Keys are anatomical slice indices (0 = first DICOM slice), not Series View frame indices.
    """
    if mask.ndim != 3:
        raise ValueError(f"Expected 3D mask, got shape {mask.shape}")

    by_slice: dict[int, list[Segmentation]] = {}
    for slice_index in range(mask.shape[0]):
        segmentations = mask_slice_to_segmentations(
            mask[slice_index],
            structure_name=structure_name,
            color_bgr=color_bgr,
            contour_epsilon_ratio=contour_epsilon_ratio,
            smooth_sigma=smooth_sigma,
            contour_smooth_window=contour_smooth_window,
        )
        if segmentations:
            by_slice[slice_index] = segmentations
    return by_slice


def shift_overlays_to_viewer_frames(
    by_slice: dict[int, list[Segmentation]],
    *,
    frame_offset: int,
) -> dict[int, list[Segmentation]]:
    """Map anatomical slice indices → Series View frame indices (skip projection prefix)."""
    if frame_offset == 0:
        return by_slice
    return {slice_index + frame_offset: segs for slice_index, segs in by_slice.items()}


def structure_mask_overlays_for_series(
    mask_path: Path,
    *,
    structure_name: str,
    color_bgr: tuple[int, int, int] | None = None,
    load_mask: Callable[[Path], np.ndarray] | None = None,
    reference_volume_path: Path | None = None,
) -> dict[int, list[Segmentation]]:
    """Load one structure NIfTI once, contour all slices, drop the volume."""
    color = color_bgr if color_bgr is not None else color_bgr_for_structure(structure_name)
    if load_mask is not None:
        mask = load_mask(mask_path)
    else:
        mask = load_structure_mask_array(mask_path, reference_volume_path=reference_volume_path)
    try:
        return mask_volume_to_slice_segmentations(mask, structure_name=structure_name, color_bgr=color)
    finally:
        del mask


def primary_segment_overlays_for_series(
    seg_dir: Path,
    group_name: str,
    *,
    color_bgr: tuple[int, int, int] | None = None,
    load_group_mask: Callable[[Path, str], np.ndarray] | None = None,
    reference_volume_path: Path | None = None,
) -> dict[int, list[Segmentation]]:
    """Load/union primary-group masks once, contour all slices, drop the volume."""
    color = color_bgr if color_bgr is not None else color_bgr_for_structure(group_name)
    if load_group_mask is not None:
        mask = load_group_mask(seg_dir, group_name)
    else:
        mask = load_primary_segment_mask(
            seg_dir,
            group_name,
            reference_volume_path=reference_volume_path,
        )
    try:
        return mask_volume_to_slice_segmentations(mask, structure_name=group_name, color_bgr=color)
    finally:
        del mask


def merge_structure_overlays(
    by_name: dict[str, dict[int, list[Segmentation]]],
) -> dict[int, list[Segmentation]]:
    """Merge per-structure all-slice overlays into one frame→polygons map."""
    merged: dict[int, list[Segmentation]] = {}
    for frame_map in by_name.values():
        for frame_index, segs in frame_map.items():
            merged.setdefault(frame_index, []).extend(segs)
    return merged
