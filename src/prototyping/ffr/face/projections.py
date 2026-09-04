from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import SimpleITK as sitk

from prototyping.ffr.face.orientation import VolumeAxes, array_axis_spacing_mm, classify_volume_axes


@dataclass(frozen=True)
class MaskBbox:
    z0: int
    z1: int
    y0: int
    y1: int
    x0: int
    x1: int


@dataclass(frozen=True)
class CropBounds2d:
    y0: int
    y1: int
    x0: int
    x1: int


@dataclass(frozen=True)
class SlabView:
    before: np.ndarray
    after: np.ndarray
    mask: np.ndarray
    aspect: float
    label: str


@dataclass(frozen=True)
class FaceProjections:
    """Coronal and sagittal slab means at several positions through the face mask."""

    frontal_slabs: tuple[SlabView, ...]
    side_slabs: tuple[SlabView, ...]


def mask_bbox_zyx(mask: np.ndarray, *, margin_voxels: int = 8) -> MaskBbox:
    coords = np.where(mask)
    if coords[0].size == 0:
        z, y, x = mask.shape
        mid_z, mid_y, mid_x = z // 2, y // 2, x // 2
        return MaskBbox(
            z0=max(0, mid_z - 1),
            z1=min(z - 1, mid_z + 1),
            y0=max(0, mid_y - 1),
            y1=min(y - 1, mid_y + 1),
            x0=max(0, mid_x - 1),
            x1=min(x - 1, mid_x + 1),
        )

    z0 = max(0, int(coords[0].min()) - margin_voxels)
    z1 = min(mask.shape[0] - 1, int(coords[0].max()) + margin_voxels)
    y0 = max(0, int(coords[1].min()) - margin_voxels)
    y1 = min(mask.shape[1] - 1, int(coords[1].max()) + margin_voxels)
    x0 = max(0, int(coords[2].min()) - margin_voxels)
    x1 = min(mask.shape[2] - 1, int(coords[2].max()) + margin_voxels)
    return MaskBbox(z0=z0, z1=z1, y0=y0, y1=y1, x0=x0, x1=x1)


def _crop_subvolume(hu: np.ndarray, mask: np.ndarray, bbox: MaskBbox) -> tuple[np.ndarray, np.ndarray]:
    return (
        hu[bbox.z0 : bbox.z1 + 1, bbox.y0 : bbox.y1 + 1, bbox.x0 : bbox.x1 + 1],
        mask[bbox.z0 : bbox.z1 + 1, bbox.y0 : bbox.y1 + 1, bbox.x0 : bbox.x1 + 1],
    )


def _mask_centroid_index(mask: np.ndarray, axis: int) -> int:
    coords = np.where(mask)
    if coords[0].size == 0:
        return mask.shape[axis] // 2
    return int(round(float(coords[axis].mean())))


def _midface_centroid_index(
    mask: np.ndarray,
    axis: int,
    axes: VolumeAxes,
    volume: sitk.Image,
    *,
    band_half_mm: float = 30.0,
) -> int:
    """Centroid along ``axis`` using only voxels near the mask SI midline (mid-face)."""
    si_center = _mask_centroid_index(mask, axes.si)
    si_spacing = array_axis_spacing_mm(volume, axes.si)
    si_half = max(4, int(round(band_half_mm / si_spacing)))
    coords = np.where(mask)
    in_band = np.abs(coords[axes.si] - si_center) <= si_half
    if not in_band.any():
        return _mask_centroid_index(mask, axis)
    return int(round(float(coords[axis][in_band].mean())))


def _slab_centers_and_labels(
    mask: np.ndarray,
    axis: int,
    axes: VolumeAxes,
    volume: sitk.Image,
    *,
    view_name: str,
    count: int,
) -> tuple[list[int], list[str]]:
    lo, hi = _mask_extent_on_axis(mask, axis)
    mid = _midface_centroid_index(mask, axis, axes, volume)
    if count == 1:
        return [mid], [f"{view_name} mid"]

    span = max(hi - lo, 1)
    offset = max(1, int(round(span * 0.22)))

    if view_name == "coronal":
        toward_anterior = -1 if axes.ap_sign > 0 else 1
        toward_posterior = -toward_anterior
        centers = [
            int(np.clip(mid + toward_posterior * offset, lo, hi)),
            mid,
            int(np.clip(mid + toward_anterior * offset, lo, hi)),
        ]
        labels = ["posterior", "mid", "anterior"]
    else:
        toward_left = 1 if axes.lr_sign > 0 else -1
        toward_right = -toward_left
        centers = [
            int(np.clip(mid + toward_right * offset, lo, hi)),
            mid,
            int(np.clip(mid + toward_left * offset, lo, hi)),
        ]
        labels = ["right", "mid", "left"]

    if count != 3:
        fractions = np.linspace(0.2, 0.8, count)
        centers = [int(round(lo + (hi - lo) * fraction)) for fraction in fractions]
        labels = [f"{view_name} {i + 1}/{count}" for i in range(count)]

    return centers, labels


def _union_crop_bounds(bounds_list: list[CropBounds2d]) -> CropBounds2d | None:
    if not bounds_list:
        return None
    return CropBounds2d(
        y0=min(bounds.y0 for bounds in bounds_list),
        y1=max(bounds.y1 for bounds in bounds_list),
        x0=min(bounds.x0 for bounds in bounds_list),
        x1=max(bounds.x1 for bounds in bounds_list),
    )


def _slab_half_width_voxels(spacing_mm: float, *, slab_half_mm: float) -> int:
    if spacing_mm <= 0:
        return 0
    return max(0, int(round(slab_half_mm / spacing_mm)))


def _masked_slab_mean_along_axis(
    hu: np.ndarray,
    mask: np.ndarray,
    axis: int,
    *,
    center: int,
    half_width: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Mean HU over a thin slab along ``axis`` (masked voxels only)."""
    lo = max(0, center - half_width)
    hi = min(hu.shape[axis], center + half_width + 1)

    indices = [slice(None)] * 3
    indices[axis] = slice(lo, hi)
    sub_hu = hu[tuple(indices)]
    sub_mask = mask[tuple(indices)]

    hu_a = np.moveaxis(sub_hu, axis, 0)
    mask_a = np.moveaxis(sub_mask, axis, 0)
    sum_hu = np.zeros(mask_a.shape[1:], dtype=np.float64)
    count = np.zeros(mask_a.shape[1:], dtype=np.int64)
    for i in range(hu_a.shape[0]):
        plane_mask = mask_a[i]
        sum_hu += np.where(plane_mask, hu_a[i], 0.0)
        count += plane_mask.astype(np.int64)

    fill = float(np.min(hu))
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, sum_hu / count, fill)
    proj_mask = count > 0
    return mean, proj_mask


def _orient_projection_plane(
    projection: np.ndarray,
    mask2d: np.ndarray,
    *,
    collapse_axis: int,
    row_axis: int,
    col_axis: int,
    flip_row: bool,
    flip_col: bool,
) -> tuple[np.ndarray, np.ndarray]:
    remaining = [axis for axis in range(3) if axis != collapse_axis]
    row_dim = remaining.index(row_axis)
    col_dim = remaining.index(col_axis)
    projection = np.moveaxis(projection, [row_dim, col_dim], [0, 1])
    mask2d = np.moveaxis(mask2d, [row_dim, col_dim], [0, 1])
    if flip_row:
        projection = np.flipud(projection)
        mask2d = np.flipud(mask2d)
    if flip_col:
        projection = np.fliplr(projection)
        mask2d = np.fliplr(mask2d)
    return projection, mask2d


def _frontal_display_flips(axes: VolumeAxes) -> tuple[bool, bool]:
    """Superior toward top; radiological coronal (patient left on viewer right)."""
    flip_row = axes.si_sign > 0
    flip_col = axes.lr_sign > 0
    return flip_row, flip_col


def _side_display_flips(axes: VolumeAxes) -> tuple[bool, bool]:
    """Superior toward top; anterior toward viewer left (profile facing right)."""
    flip_row = axes.si_sign > 0
    flip_col = axes.ap_sign > 0
    return flip_row, flip_col


def _projection_aspect(volume: sitk.Image, row_axis: int, col_axis: int) -> float:
    """Matplotlib imshow aspect: row spacing / col spacing for true physical proportions."""
    row_spacing = array_axis_spacing_mm(volume, row_axis)
    col_spacing = array_axis_spacing_mm(volume, col_axis)
    if col_spacing <= 0:
        return 1.0
    return row_spacing / col_spacing


def _crop_bounds_2d(mask2d: np.ndarray, *, margin: int) -> CropBounds2d | None:
    if not mask2d.any():
        return None
    ys, xs = np.where(mask2d)
    height, width = mask2d.shape
    return CropBounds2d(
        y0=max(0, int(ys.min()) - margin),
        y1=min(height - 1, int(ys.max()) + margin),
        x0=max(0, int(xs.min()) - margin),
        x1=min(width - 1, int(xs.max()) + margin),
    )


def _apply_crop_2d(image: np.ndarray, bounds: CropBounds2d) -> np.ndarray:
    return image[bounds.y0 : bounds.y1 + 1, bounds.x0 : bounds.x1 + 1]


def _crop_projection_triplet(
    before: np.ndarray,
    after: np.ndarray,
    mask2d: np.ndarray,
    *,
    margin: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bounds = _crop_bounds_2d(mask2d, margin=margin)
    if bounds is None:
        return before, after, mask2d
    return (
        _apply_crop_2d(before, bounds),
        _apply_crop_2d(after, bounds),
        _apply_crop_2d(mask2d, bounds),
    )


def _mask_extent_on_axis(mask: np.ndarray, axis: int) -> tuple[int, int]:
    coords = np.where(mask)
    if coords[0].size == 0:
        mid = mask.shape[axis] // 2
        return mid, mid
    values = coords[axis]
    return int(values.min()), int(values.max())


def _build_slab_views(
    sub_before: np.ndarray,
    sub_after: np.ndarray,
    sub_mask: np.ndarray,
    axes: VolumeAxes,
    volume: sitk.Image,
    *,
    view: str,
    slab_half_mm: float,
    crop_margin: int,
    count: int,
) -> tuple[SlabView, ...]:
    if view == "frontal":
        collapse = axes.ap
        row_axis, col_axis = axes.si, axes.lr
        flip_row, flip_col = _frontal_display_flips(axes)
        view_name = "coronal"
    elif view == "side":
        collapse = axes.lr
        row_axis, col_axis = axes.si, axes.ap
        flip_row, flip_col = _side_display_flips(axes)
        view_name = "sagittal"
    else:
        raise ValueError(f"Unknown view: {view}")

    centers, labels = _slab_centers_and_labels(
        sub_mask,
        collapse,
        axes,
        volume,
        view_name=view_name,
        count=count,
    )
    spacing = array_axis_spacing_mm(volume, collapse)
    half_width = _slab_half_width_voxels(spacing, slab_half_mm=slab_half_mm)
    aspect = _projection_aspect(volume, row_axis, col_axis)

    raw_slabs: list[tuple[np.ndarray, np.ndarray, np.ndarray, str]] = []
    for center, label in zip(centers, labels, strict=True):
        before, mask2d = _masked_slab_mean_along_axis(
            sub_before,
            sub_mask,
            collapse,
            center=center,
            half_width=half_width,
        )
        after, _ = _masked_slab_mean_along_axis(
            sub_after,
            sub_mask,
            collapse,
            center=center,
            half_width=half_width,
        )
        before, mask2d = _orient_projection_plane(
            before,
            mask2d,
            collapse_axis=collapse,
            row_axis=row_axis,
            col_axis=col_axis,
            flip_row=flip_row,
            flip_col=flip_col,
        )
        after, _ = _orient_projection_plane(
            after,
            mask2d,
            collapse_axis=collapse,
            row_axis=row_axis,
            col_axis=col_axis,
            flip_row=flip_row,
            flip_col=flip_col,
        )
        raw_slabs.append((before, after, mask2d, label))

    mid_index = len(raw_slabs) // 2
    shared_bounds = _crop_bounds_2d(raw_slabs[mid_index][2], margin=crop_margin)
    if shared_bounds is None:
        shared_bounds_list = [
            bounds
            for _, _, mask2d, _ in raw_slabs
            if (bounds := _crop_bounds_2d(mask2d, margin=crop_margin)) is not None
        ]
        shared_bounds = _union_crop_bounds(shared_bounds_list)

    slabs: list[SlabView] = []
    for before, after, mask2d, label in raw_slabs:
        if shared_bounds is not None:
            before = _apply_crop_2d(before, shared_bounds)
            after = _apply_crop_2d(after, shared_bounds)
            mask2d = _apply_crop_2d(mask2d, shared_bounds)
        slabs.append(
            SlabView(
                before=before,
                after=after,
                mask=mask2d,
                aspect=aspect,
                label=f"{view_name.capitalize()} — {label}",
            )
        )
    return tuple(slabs)


def build_face_projections(
    hu_before: np.ndarray,
    hu_after: np.ndarray,
    mask: np.ndarray,
    volume: sitk.Image,
    *,
    margin_voxels: int = 8,
    crop_margin: int = 6,
    slab_half_mm: float = 2.5,
    n_coronal_slabs: int = 3,
    n_sagittal_slabs: int = 3,
) -> FaceProjections:
    """
    Coronal and sagittal slab means at several positions through the face mask.

    Default: three coronal slabs (posterior / mid / anterior) and three sagittal
    slabs (right / mid / left).
    """
    axes = classify_volume_axes(volume)
    bbox = mask_bbox_zyx(mask, margin_voxels=margin_voxels)
    sub_before, sub_mask = _crop_subvolume(hu_before, mask, bbox)
    sub_after, _ = _crop_subvolume(hu_after, mask, bbox)

    slab_kwargs = {
        "slab_half_mm": slab_half_mm,
        "crop_margin": crop_margin,
    }
    frontal_slabs = _build_slab_views(
        sub_before,
        sub_after,
        sub_mask,
        axes,
        volume,
        view="frontal",
        count=n_coronal_slabs,
        **slab_kwargs,
    )
    side_slabs = _build_slab_views(
        sub_before,
        sub_after,
        sub_mask,
        axes,
        volume,
        view="side",
        count=n_sagittal_slabs,
        **slab_kwargs,
    )

    return FaceProjections(frontal_slabs=frontal_slabs, side_slabs=side_slabs)
