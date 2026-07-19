from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

from prototyping.ffr.face.models import FaceVolumeData, QaStats
from prototyping.ffr.face.projections import FaceProjections, SlabView
from prototyping.ffr.face.volume import face_slice_indices
from prototyping.ffr.face.viz.windowing import auto_window_from_mask, window_hu_to_uint8

MODE_DESCRIPTIONS: dict[str, str] = {
    "J_front_side": (
        "Coronal and sagittal slabs at three positions each (posterior/mid/anterior and "
        "right/mid/left): before vs after blur. Green = TotalSegmentator face mask outline (QA)."
    ),
    "J_front_side_diff": "|HU diff| on frontal and side projections — should be zero outside face outline.",
    "A_triptych": "Original | blurred | |HU diff| on one axial slice — diff should be dark outside face.",
    "B_violation": "Red = any pixel outside face mask where before ≠ after (should be empty).",
    "C_contour": "Face mask contour on original vs inset blurred patch.",
    "D_multi_slice": "Triptych at several slices through the face extent.",
    "G_histogram": "HU histogram inside vs outside mask; outside curves should overlap before/after.",
    "I_diff_mip": "Maximum |diff| along stack — leaks outside face show as bright structure.",
}


def _save_figure(fig: Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def _abs_diff(hu_before: np.ndarray, hu_after: np.ndarray) -> np.ndarray:
    return np.abs(hu_after.astype(np.float64) - hu_before.astype(np.float64))


def _draw_contours(ax, mask2d: np.ndarray, *, color: str = "lime", linewidth: float = 1.2) -> None:
    from skimage.measure import find_contours

    for contour in find_contours(mask2d.astype(float), 0.5):
        ax.plot(contour[:, 1], contour[:, 0], color=color, linewidth=linewidth)


def _show_hu_panel(
    ax,
    hu: np.ndarray,
    mask2d: np.ndarray,
    *,
    wl: float,
    ww: float,
    title: str,
    show_contour: bool = True,
    aspect: float = 1.0,
) -> None:
    img = window_hu_to_uint8(hu, wl, ww)
    ax.imshow(img, cmap="gray", aspect=aspect)
    if show_contour and mask2d.any():
        _draw_contours(ax, mask2d)
    ax.set_title(title, pad=6)
    ax.axis("off")


def _window_for_slab(slab: SlabView) -> tuple[float, float]:
    return auto_window_from_mask(slab.before, slab.mask)


def _render_slab_row(
    axes_row: np.ndarray,
    slab: SlabView,
    *,
    wl: float,
    ww: float,
) -> None:
    _show_hu_panel(
        axes_row[0],
        slab.before,
        slab.mask,
        wl=wl,
        ww=ww,
        title=f"{slab.label} — before",
        aspect=slab.aspect,
    )
    _show_hu_panel(
        axes_row[1],
        slab.after,
        slab.mask,
        wl=wl,
        ww=ww,
        title=f"{slab.label} — after blur",
        aspect=slab.aspect,
    )


def render_front_side(
    data: FaceVolumeData,
    output_dir: Path,
    projections: FaceProjections,
    wl: float,
    ww: float,
) -> Path:
    n_rows = len(projections.frontal_slabs) + len(projections.side_slabs)
    fig, axes = plt.subplots(n_rows, 2, figsize=(10, 3.2 * n_rows))
    if n_rows == 1:
        axes = np.expand_dims(axes, axis=0)

    row = 0
    coronal_axes: list[np.ndarray] = []
    for slab in projections.frontal_slabs:
        wl, ww = _window_for_slab(slab)
        _render_slab_row(axes[row], slab, wl=wl, ww=ww)
        coronal_axes.append(axes[row])
        row += 1
    if projections.frontal_slabs:
        height, width = projections.frontal_slabs[0].before.shape
        for axis_pair in coronal_axes:
            for ax in axis_pair:
                ax.set_xlim(-0.5, width - 0.5)
                ax.set_ylim(height - 0.5, -0.5)
    sagittal_axes: list[np.ndarray] = []
    for slab in projections.side_slabs:
        wl, ww = _window_for_slab(slab)
        _render_slab_row(axes[row], slab, wl=wl, ww=ww)
        sagittal_axes.append(axes[row])
        row += 1
    if projections.side_slabs:
        height, width = projections.side_slabs[0].before.shape
        for axis_pair in sagittal_axes:
            for ax in axis_pair:
                ax.set_xlim(-0.5, width - 0.5)
                ax.set_ylim(height - 0.5, -0.5)

    fig.suptitle(
        "Mode J — coronal and sagittal face slabs\n(before | after blur)",
        fontsize=11,
        y=0.998,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    return _save_figure(fig, output_dir / "J_front_side.png")


def render_front_side_diff(
    data: FaceVolumeData,
    output_dir: Path,
    projections: FaceProjections,
    wl: float,
    ww: float,
) -> Path:
    n_coronal = len(projections.frontal_slabs)
    n_sagittal = len(projections.side_slabs)
    n_rows = max(n_coronal, n_sagittal)
    fig, axes = plt.subplots(n_rows, 2, figsize=(10, 3.2 * n_rows))
    if n_rows == 1:
        axes = np.expand_dims(axes, axis=0)

    for row, slab in enumerate(projections.frontal_slabs):
        diff = _abs_diff(slab.before, slab.after)
        scaled = np.clip(diff / max(diff.max(), 1.0) * 255, 0, 255).astype(np.uint8)
        axes[row, 0].imshow(scaled, cmap="hot", aspect=slab.aspect)
        _draw_contours(axes[row, 0], slab.mask, color="cyan", linewidth=1.0)
        axes[row, 0].set_title(f"{slab.label} |diff|")
        axes[row, 0].axis("off")

    for row in range(n_coronal, n_rows):
        axes[row, 0].axis("off")

    for row, slab in enumerate(projections.side_slabs):
        diff = _abs_diff(slab.before, slab.after)
        scaled = np.clip(diff / max(diff.max(), 1.0) * 255, 0, 255).astype(np.uint8)
        axes[row, 1].imshow(scaled, cmap="hot", aspect=slab.aspect)
        _draw_contours(axes[row, 1], slab.mask, color="cyan", linewidth=1.0)
        axes[row, 1].set_title(f"{slab.label} |diff|")
        axes[row, 1].axis("off")

    for row in range(n_sagittal, n_rows):
        axes[row, 1].axis("off")

    fig.suptitle("Mode J — diff on face slabs\n(cyan = face outline)", fontsize=11, y=0.998)
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    return _save_figure(fig, output_dir / "J_front_side_diff.png")


def render_triptych(
    data: FaceVolumeData,
    output_dir: Path,
    slice_index: int,
    wl: float,
    ww: float,
) -> Path:
    z = slice_index
    before = window_hu_to_uint8(data.hu_before[z], wl, ww)
    after = window_hu_to_uint8(data.hu_after[z], wl, ww)
    diff = _abs_diff(data.hu_before[z], data.hu_after[z])
    diff_vis = np.clip(diff / max(diff.max(), 1.0) * 255, 0, 255).astype(np.uint8)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for ax, img, title in zip(
        axes,
        [before, after, diff_vis],
        ["Before (windowed)", "After blur (windowed)", "|HU diff|"],
        strict=True,
    ):
        ax.imshow(img, cmap="gray", aspect="equal")
        ax.set_title(title)
        ax.axis("off")
    fig.suptitle(f"Mode A — slice z={z}")
    return _save_figure(fig, output_dir / "A_triptych.png")


def render_violation_overlay(
    data: FaceVolumeData,
    output_dir: Path,
    slice_index: int,
    wl: float,
    ww: float,
) -> Path:
    z = slice_index
    base = window_hu_to_uint8(data.hu_before[z], wl, ww)
    rgb = np.stack([base, base, base], axis=-1)
    outside = ~data.mask[z]
    diff = _abs_diff(data.hu_before[z], data.hu_after[z])
    violations = outside & (diff > 0)
    rgb[violations, 0] = 255
    rgb[violations, 1] = 0
    rgb[violations, 2] = 0

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(rgb)
    ax.set_title(f"Mode B — violations outside mask (red), z={z}")
    ax.axis("off")
    return _save_figure(fig, output_dir / "B_violation.png")


def render_contour_overlay(
    data: FaceVolumeData,
    output_dir: Path,
    slice_index: int,
    wl: float,
    ww: float,
) -> Path:
    from skimage.measure import find_contours

    z = slice_index
    before = window_hu_to_uint8(data.hu_before[z], wl, ww)
    after = window_hu_to_uint8(data.hu_after[z], wl, ww)

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    for ax, img, title in zip(
        axes,
        [before, after],
        ["Before + face contour", "After blur"],
        strict=True,
    ):
        ax.imshow(img, cmap="gray")
        contours = find_contours(data.mask[z].astype(float), 0.5)
        for contour in contours:
            ax.plot(contour[:, 1], contour[:, 0], color="lime", linewidth=1.2)
        ax.set_title(title)
        ax.axis("off")
    fig.suptitle(f"Mode C — z={z}")
    return _save_figure(fig, output_dir / "C_contour.png")


def render_multi_slice(
    data: FaceVolumeData,
    output_dir: Path,
    wl: float,
    ww: float,
) -> Path:
    indices = face_slice_indices(data.mask)
    n = len(indices)
    fig, axes = plt.subplots(n, 3, figsize=(12, 3 * n))
    if n == 1:
        axes = np.expand_dims(axes, axis=0)

    for row, z in enumerate(indices):
        before = window_hu_to_uint8(data.hu_before[z], wl, ww)
        after = window_hu_to_uint8(data.hu_after[z], wl, ww)
        diff = _abs_diff(data.hu_before[z], data.hu_after[z])
        diff_vis = np.clip(diff / max(diff.max(), 1.0) * 255, 0, 255).astype(np.uint8)
        for col, img in enumerate([before, after, diff_vis]):
            axes[row, col].imshow(img, cmap="gray")
            axes[row, col].axis("off")
            if row == 0:
                axes[row, col].set_title(["Before", "After", "|diff|"][col])
        axes[row, 0].set_ylabel(f"z={z}", rotation=0, labelpad=30, va="center")

    fig.suptitle("Mode D — multiple slices")
    return _save_figure(fig, output_dir / "D_multi_slice.png")


def render_histogram(data: FaceVolumeData, stats: QaStats, output_dir: Path) -> Path:
    face = data.mask.astype(bool)
    outside = ~face
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))

    for ax, region, title in zip(
        axes,
        [outside, face],
        ["Outside face mask", "Inside face mask"],
        strict=True,
    ):
        before = data.hu_before[region].ravel()
        after = data.hu_after[region].ravel()
        ax.hist(before, bins=80, alpha=0.5, label="before", density=True)
        ax.hist(after, bins=80, alpha=0.5, label="after", density=True)
        ax.set_title(title)
        ax.legend()
        ax.set_xlabel("HU")

    status = "PASS" if stats.outside_clean else "FAIL"
    fig.suptitle(f"Mode G — histogram QA ({status})")
    return _save_figure(fig, output_dir / "G_histogram.png")


def render_diff_mip(data: FaceVolumeData, stats: QaStats, output_dir: Path) -> Path:
    diff = _abs_diff(data.hu_before, data.hu_after)
    mip = diff.max(axis=0)
    outside_mip = np.where(data.mask.any(axis=0), 0, mip)

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    axes[0].imshow(mip, cmap="hot")
    axes[0].set_title("MIP |diff| (all voxels)")
    axes[0].axis("off")
    axes[1].imshow(outside_mip, cmap="hot")
    axes[1].set_title("MIP |diff| outside mask only (should be black)")
    axes[1].axis("off")
    status = "PASS" if stats.outside_clean else "FAIL"
    fig.suptitle(f"Mode I — diff MIP ({status})")
    return _save_figure(fig, output_dir / "I_diff_mip.png")
