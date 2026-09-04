from __future__ import annotations

from pathlib import Path

from prototyping.ffr.face.models import FaceVolumeData, QaStats
from prototyping.ffr.face.projections import build_face_projections
from prototyping.ffr.face.viz import modes

VIZ_MODES: tuple[str, ...] = (
    "J_front_side",
    "J_front_side_diff",
    "A_triptych",
    "B_violation",
    "C_contour",
    "D_multi_slice",
    "G_histogram",
    "I_diff_mip",
)


def render_all_modes(
    data: FaceVolumeData,
    stats: QaStats,
    output_dir: Path,
    *,
    slice_index: int,
    window_center: float,
    window_width: float,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: dict[str, Path] = {}

    projections = build_face_projections(
        data.hu_before,
        data.hu_after,
        data.mask,
        data.volume_img,
    )
    rendered["J_front_side"] = modes.render_front_side(
        data, output_dir, projections, window_center, window_width
    )
    rendered["J_front_side_diff"] = modes.render_front_side_diff(
        data, output_dir, projections, window_center, window_width
    )
    rendered["A_triptych"] = modes.render_triptych(
        data, output_dir, slice_index, window_center, window_width
    )
    rendered["B_violation"] = modes.render_violation_overlay(
        data, output_dir, slice_index, window_center, window_width
    )
    rendered["C_contour"] = modes.render_contour_overlay(
        data, output_dir, slice_index, window_center, window_width
    )
    rendered["D_multi_slice"] = modes.render_multi_slice(
        data, output_dir, window_center, window_width
    )
    rendered["G_histogram"] = modes.render_histogram(data, stats, output_dir)
    rendered["I_diff_mip"] = modes.render_diff_mip(data, stats, output_dir)

    return rendered
