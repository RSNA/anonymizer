"""Tests for anatomy NIfTI → series overlay conversion (no UI)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import SimpleITK as sitk

from anonymizer.controller.ai.anatomy_overlay import (
    PRIMARY_SEGMENT_COLORS_BGR,
    color_bgr_for_structure,
    ensure_roi_palette_complete,
    mask_volume_to_slice_segmentations,
    merge_structure_overlays,
    structure_mask_overlays_for_series,
)
from anonymizer.controller.ai.tseg.config import PRIMARY_SEGMENT_GROUPS, PRIMARY_SEGMENT_ORDER, ROI_SUBSET
from anonymizer.controller.series_overlay import PolygonPoint, Segmentation


def _write_mask(path: Path, voxels: int, shape: tuple[int, int, int] = (4, 16, 16)) -> None:
    arr = np.zeros(shape, dtype=np.uint8)
    flat = arr.reshape(-1)
    flat[:voxels] = 1
    image = sitk.GetImageFromArray(arr.reshape(shape))
    path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(path))


def test_roi_palette_covers_primary_groups() -> None:
    ensure_roi_palette_complete()
    for name in PRIMARY_SEGMENT_ORDER:
        assert name in PRIMARY_SEGMENT_COLORS_BGR
        assert len(color_bgr_for_structure(name)) == 3
    covered = {stem for files in PRIMARY_SEGMENT_GROUPS.values() for stem in files}
    assert set(ROI_SUBSET) <= covered


def test_primary_segments_merge_sides_and_include_skeleton() -> None:
    assert "lungs" in PRIMARY_SEGMENT_ORDER
    assert "kidneys" in PRIMARY_SEGMENT_ORDER
    assert "spine" in PRIMARY_SEGMENT_ORDER
    assert "ribs" in PRIMARY_SEGMENT_ORDER
    assert "clavicles" in PRIMARY_SEGMENT_ORDER
    assert "spinal_cord" in PRIMARY_SEGMENT_ORDER
    assert "brainstem" in PRIMARY_SEGMENT_ORDER
    assert "frontal_lobe" in PRIMARY_SEGMENT_ORDER
    assert "cerebellum" in PRIMARY_SEGMENT_ORDER
    assert "kidney_left" not in PRIMARY_SEGMENT_ORDER
    assert "lung_upper_lobe_left" not in PRIMARY_SEGMENT_ORDER
    assert len(PRIMARY_SEGMENT_GROUPS["lungs"]) >= 5
    assert "clavicula_left" in PRIMARY_SEGMENT_GROUPS["clavicles"]
    assert any(name.startswith("vertebrae_") for name in PRIMARY_SEGMENT_GROUPS["spine"])
    assert any(name.startswith("rib_") for name in PRIMARY_SEGMENT_GROUPS["ribs"])


def test_shift_overlays_to_viewer_frames_skips_projections() -> None:
    from anonymizer.controller.ai.anatomy_overlay import shift_overlays_to_viewer_frames
    from anonymizer.controller.series_io import SERIES_VIEW_PROJECTION_COUNT

    by_slice = {
        0: [Segmentation(points=[PolygonPoint(0, 0), PolygonPoint(1, 0), PolygonPoint(0, 1)], structure_name="brain")],
        2: [Segmentation(points=[PolygonPoint(2, 2), PolygonPoint(3, 2), PolygonPoint(2, 3)], structure_name="brain")],
    }
    shifted = shift_overlays_to_viewer_frames(by_slice, frame_offset=SERIES_VIEW_PROJECTION_COUNT)
    assert set(shifted.keys()) == {3, 5}
    assert shifted[3][0].structure_name == "brain"


def test_primary_colors_are_distinct() -> None:
    colors = list(PRIMARY_SEGMENT_COLORS_BGR.values())
    assert len(colors) == len(set(colors))
    heart = color_bgr_for_structure("heart")
    lungs = color_bgr_for_structure("lungs")
    assert heart != lungs
    assert heart[2] > heart[0]  # red channel dominant in BGR


def test_structure_button_label_and_width() -> None:
    from anonymizer.controller.ai.anatomy_overlay import latch_button_width_px, structure_button_label

    assert structure_button_label("kidneys") == "kidneys"
    assert latch_button_width_px("heart") < latch_button_width_px("clavicles")


def test_heart_legend_hex_is_red() -> None:
    """Button legend and OpenCV BGR must agree: heart is red, not blue/purple."""
    from anonymizer.controller.ai.anatomy_overlay import bgr_to_hex, color_bgr_for_structure

    heart_bgr = color_bgr_for_structure("heart")
    assert heart_bgr[2] > heart_bgr[0]  # R channel dominant in BGR layout
    assert bgr_to_hex(heart_bgr).startswith("#")
    assert bgr_to_hex(heart_bgr)[1:3] > bgr_to_hex(heart_bgr)[5:7]  # RR > BB in hex RGB


def test_order_structures_by_voxels_descending() -> None:
    from anonymizer.controller.ai.anatomy_overlay import order_structures_by_voxels

    ordered = order_structures_by_voxels({"liver": 10, "heart": 50, "brain": 50})
    assert [name for name, _ in ordered] == ["brain", "heart", "liver"]


def test_bgr_to_hex() -> None:
    from anonymizer.controller.ai.anatomy_overlay import bgr_to_hex

    assert bgr_to_hex((0, 0, 255)) == "#ff0000"
    assert bgr_to_hex((255, 0, 0)) == "#0000ff"


def test_collect_primary_segment_voxels_sums_bilateral(tmp_path: Path) -> None:
    from anonymizer.controller.ai.anatomy_overlay import collect_primary_segment_voxels

    seg_dir = tmp_path / "seg"
    shape = (8, 32, 32)
    _write_mask(seg_dir / "kidney_left.nii.gz", 600, shape=shape)
    _write_mask(seg_dir / "kidney_right.nii.gz", 500, shape=shape)
    _write_mask(seg_dir / "heart.nii.gz", 1200, shape=shape)
    present = collect_primary_segment_voxels(seg_dir, min_voxels=1000)
    assert present["kidneys"] == 1100
    assert present["heart"] == 1200
    assert "kidney_left" not in present


def test_primary_segment_overlays_unions_masks(tmp_path: Path) -> None:
    from anonymizer.controller.ai.anatomy_overlay import primary_segment_overlays_for_series

    seg_dir = tmp_path / "seg"
    seg_dir.mkdir(parents=True, exist_ok=True)
    left = np.zeros((3, 16, 16), dtype=np.uint8)
    right = np.zeros((3, 16, 16), dtype=np.uint8)
    left[1, 2:6, 2:6] = 1
    right[1, 10:14, 10:14] = 1
    sitk.WriteImage(sitk.GetImageFromArray(left), str(seg_dir / "kidney_left.nii.gz"))
    sitk.WriteImage(sitk.GetImageFromArray(right), str(seg_dir / "kidney_right.nii.gz"))
    overlays = primary_segment_overlays_for_series(seg_dir, "kidneys")
    assert 1 in overlays
    assert len(overlays[1]) >= 2


def test_mask_volume_contours_only_nonempty_slices() -> None:
    mask = np.zeros((3, 32, 32), dtype=np.uint8)
    mask[1, 8:24, 8:24] = 1
    by_slice = mask_volume_to_slice_segmentations(
        mask,
        structure_name="heart",
        color_bgr=(0, 0, 255),
    )
    assert set(by_slice.keys()) == {1}
    for seg in by_slice[1]:
        assert seg.structure_name == "heart"
        assert seg.color_bgr == (0, 0, 255)
        assert len(seg.points) >= 3


def test_merge_and_remesh_structure_overlays() -> None:
    a = {
        0: [Segmentation(points=[PolygonPoint(0, 0), PolygonPoint(1, 0), PolygonPoint(0, 1)], structure_name="a")],
        1: [Segmentation(points=[PolygonPoint(0, 0), PolygonPoint(2, 0), PolygonPoint(0, 2)], structure_name="a")],
    }
    b = {
        1: [Segmentation(points=[PolygonPoint(3, 3), PolygonPoint(4, 3), PolygonPoint(3, 4)], structure_name="b")],
    }
    merged = merge_structure_overlays({"a": a, "b": b})
    assert len(merged[0]) == 1
    assert len(merged[1]) == 2
    remeshed = merge_structure_overlays({"b": b})
    assert 0 not in remeshed
    assert len(remeshed[1]) == 1
    assert remeshed[1][0].structure_name == "b"


def test_structure_mask_overlays_loads_once_not_on_slice_change(tmp_path: Path) -> None:
    mask = np.zeros((4, 16, 16), dtype=np.uint8)
    mask[2, 4:12, 4:12] = 1
    calls: list[Path] = []

    def load_mask(path: Path) -> np.ndarray:
        calls.append(path)
        return mask.copy()

    path = tmp_path / "heart.nii.gz"
    overlays = structure_mask_overlays_for_series(
        path,
        structure_name="heart",
        load_mask=load_mask,
    )
    assert len(calls) == 1
    for slice_index in range(4):
        _ = overlays.get(slice_index, [])
    assert len(calls) == 1


def test_structure_mask_overlays_missing_loader_raises(tmp_path: Path) -> None:
    path = tmp_path / "missing.nii.gz"
    load_mask = MagicMock(side_effect=FileNotFoundError(path))
    with pytest.raises(FileNotFoundError):
        structure_mask_overlays_for_series(path, structure_name="heart", load_mask=load_mask)
    assert load_mask.call_count == 1


def test_resolve_spine_prefers_vertebrae_body_super_segment(tmp_path: Path) -> None:
    from anonymizer.controller.ai.anatomy_overlay import resolve_primary_segment_files
    from anonymizer.controller.ai.tseg.config import PRIMARY_SEGMENT_GROUPS

    seg_dir = tmp_path / "seg"
    seg_dir.mkdir()
    (seg_dir / "vertebrae_body.nii.gz").write_bytes(b"x")
    (seg_dir / "vertebrae_C1.nii.gz").write_bytes(b"x")
    assert resolve_primary_segment_files(seg_dir, "spine") == ("vertebrae_body",)
    (seg_dir / "vertebrae_body.nii.gz").unlink()
    assert resolve_primary_segment_files(seg_dir, "spine") == PRIMARY_SEGMENT_GROUPS["spine"]


def test_collect_spine_voxels_uses_super_segment_when_present(tmp_path: Path) -> None:
    from anonymizer.controller.ai.anatomy_overlay import collect_primary_segment_voxels

    seg_dir = tmp_path / "seg"
    shape = (8, 32, 32)
    _write_mask(seg_dir / "vertebrae_body.nii.gz", 1500, shape=shape)
    _write_mask(seg_dir / "vertebrae_C1.nii.gz", 800, shape=shape)
    present = collect_primary_segment_voxels(seg_dir, min_voxels=1000)
    assert present["spine"] == 1500


def test_load_primary_segment_mask_reads_reference_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from anonymizer.controller.ai import anatomy_overlay as mod

    seg_dir = tmp_path / "seg"
    shape = (2, 8, 8)
    _write_mask(seg_dir / "kidney_left.nii.gz", 20, shape=shape)
    _write_mask(seg_dir / "kidney_right.nii.gz", 20, shape=shape)
    volume = tmp_path / "volume.nii.gz"
    _write_mask(volume, 1, shape=shape)

    reads: list[str] = []
    real_read = sitk.ReadImage

    def counting_read(path: str, *args, **kwargs):
        reads.append(Path(path).name)
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(mod.sitk, "ReadImage", counting_read)
    mask = mod.load_primary_segment_mask(seg_dir, "kidneys", reference_volume_path=volume)
    assert mask.shape == shape
    assert reads.count("volume.nii.gz") == 1
    assert reads.count("kidney_left.nii.gz") == 1
    assert reads.count("kidney_right.nii.gz") == 1


def test_load_spine_mask_prefers_super_segment_over_vertebrae(tmp_path: Path) -> None:
    from anonymizer.controller.ai.anatomy_overlay import load_primary_segment_mask

    seg_dir = tmp_path / "seg"
    seg_dir.mkdir(parents=True, exist_ok=True)
    shape = (3, 16, 16)
    super_mask = np.zeros(shape, dtype=np.uint8)
    super_mask[1, 2:10, 2:10] = 1
    c1 = np.zeros(shape, dtype=np.uint8)
    c1[0, 0:4, 0:4] = 1
    sitk.WriteImage(sitk.GetImageFromArray(super_mask), str(seg_dir / "vertebrae_body.nii.gz"))
    sitk.WriteImage(sitk.GetImageFromArray(c1), str(seg_dir / "vertebrae_C1.nii.gz"))
    loaded = load_primary_segment_mask(seg_dir, "spine")
    assert loaded.shape == shape
    assert int(loaded.sum()) == int(super_mask.sum())
    assert loaded[0].sum() == 0  # C1-only voxels not included


def test_load_spine_mask_falls_back_to_vertebrae_union(tmp_path: Path) -> None:
    from anonymizer.controller.ai.anatomy_overlay import load_primary_segment_mask

    seg_dir = tmp_path / "seg"
    seg_dir.mkdir(parents=True, exist_ok=True)
    shape = (3, 16, 16)
    c1 = np.zeros(shape, dtype=np.uint8)
    c1[0, 0:4, 0:4] = 1
    c2 = np.zeros(shape, dtype=np.uint8)
    c2[1, 4:8, 4:8] = 1
    sitk.WriteImage(sitk.GetImageFromArray(c1), str(seg_dir / "vertebrae_C1.nii.gz"))
    sitk.WriteImage(sitk.GetImageFromArray(c2), str(seg_dir / "vertebrae_C2.nii.gz"))
    loaded = load_primary_segment_mask(seg_dir, "spine")
    assert int(loaded.sum()) == int(c1.sum() + c2.sum())
    assert loaded[0].any() and loaded[1].any()


def test_contour_mask_slice_and_remaining() -> None:
    from anonymizer.controller.ai.anatomy_overlay import contour_mask_slice, contour_mask_slices

    mask = np.zeros((4, 24, 24), dtype=np.uint8)
    mask[1, 4:12, 4:12] = 1
    mask[3, 8:16, 8:16] = 1
    one = contour_mask_slice(mask, 1, structure_name="spine", color_bgr=(1, 2, 3))
    assert len(one) >= 1
    assert one[0].structure_name == "spine"
    assert contour_mask_slice(mask, 0, structure_name="spine", color_bgr=(1, 2, 3)) == []

    cancelled = {"n": 0}

    def should_cancel() -> bool:
        cancelled["n"] += 1
        return cancelled["n"] > 2

    partial = contour_mask_slices(
        mask,
        range(mask.shape[0]),
        structure_name="spine",
        color_bgr=(1, 2, 3),
        should_cancel=should_cancel,
    )
    assert len(partial) <= 2
