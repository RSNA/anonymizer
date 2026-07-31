"""Tests for in-memory face blur preview and display helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import SimpleITK as sitk

from anonymizer.controller.blur_face import (
    FaceBlurProgress,
    SeriesVolumeContext,
    apply_face_blur_preview_to_series_frames,
    compute_qa_stats,
    hu_stack_to_viewer_frames,
    load_series_volume_for_blur,
    mask_slice_segmentations,
    preview_face_blur,
    read_reference_volume,
)
from anonymizer.controller.tseg.segment import face_mask_cache_path
from anonymizer.view.blur_face_results import (
    format_face_blur_progress_status,
    format_face_blur_qa_summary,
)


def _write_mask(mask_path: Path, *, shape: tuple[int, int, int]) -> None:
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros(shape, dtype=np.uint8)
    array[:, 32:64, 32:64] = 1
    sitk.WriteImage(sitk.GetImageFromArray(array), str(mask_path))


@patch("anonymizer.controller.blur_face.resolve_face_mask_path")
def test_preview_face_blur_does_not_write_dicom(
    mock_resolve: MagicMock,
    synthetic_head_series: Path,
    tmp_path: Path,
) -> None:
    volume_img, _slice_paths = read_reference_volume(synthetic_head_series)
    shape = sitk.GetArrayFromImage(volume_img).shape
    mask_path = face_mask_cache_path(synthetic_head_series)
    _write_mask(mask_path, shape=shape)
    mock_resolve.return_value = mask_path

    out_dir = tmp_path / "face_blurred"
    progress: list[FaceBlurProgress] = []

    preview = preview_face_blur(
        synthetic_head_series,
        progress=progress.append,
    )

    assert preview.error is None
    assert preview.slice_count > 0
    assert preview.qa_stats is not None
    assert preview.qa_stats.outside_clean
    assert not out_dir.exists()
    stages = [item.stage for item in progress]
    assert stages == ["mask", "volume", "load_hu", "blur", "qa", "done"]


def test_format_face_blur_qa_summary_pass_and_fail() -> None:
    mask = np.zeros((2, 8, 8), dtype=np.uint8)
    mask[0, 2:6, 2:6] = 1
    hu_before = np.zeros((2, 8, 8), dtype=np.float32)
    hu_after = hu_before.copy()
    hu_after[0, 2:6, 2:6] += 50.0
    qa = compute_qa_stats(hu_before, hu_after, mask)

    pass_summary = format_face_blur_qa_summary(qa, sigma_mm=8.0, slice_count=1)
    assert "QA PASS" in pass_summary
    assert "8.0" in pass_summary
    assert str(qa.n_face_voxels) in pass_summary.replace(",", "")

    pending = format_face_blur_qa_summary(None, sigma_mm=0.0, slice_count=0)
    assert "pending" in pending.lower()

    hu_after[1, 0, 0] = 999.0
    fail_qa = compute_qa_stats(hu_before, hu_after, mask)
    fail_summary = format_face_blur_qa_summary(fail_qa, sigma_mm=8.0, slice_count=2)
    assert "QA FAIL" in fail_summary


def test_status_text_for_progress_includes_stage_and_percent() -> None:
    text = format_face_blur_progress_status(
        FaceBlurProgress(stage="blur", message="", fraction=0.65),
    )
    assert "65%" in text
    assert "de-identification" in text


def test_mask_slice_segmentations_returns_polygons() -> None:
    mask = np.zeros((1, 10, 10), dtype=np.uint8)
    mask[0, 2:8, 2:8] = 1
    segmentations = mask_slice_segmentations(mask, 0)
    assert segmentations
    assert all(len(seg.points) >= 3 for seg in segmentations)


def test_mask_slice_segmentations_smooths_jagged_mask() -> None:
    mask = np.zeros((1, 12, 12), dtype=np.uint8)
    mask[0, 4:8, 4:8] = 1
    mask[0, 5, 5] = 0
    mask[0, 6, 6] = 0
    raw = mask_slice_segmentations(mask, 0, smooth_sigma=0, contour_epsilon_ratio=0)
    smooth = mask_slice_segmentations(mask, 0)
    assert raw
    assert smooth
    assert len(smooth[0].points) <= len(raw[0].points)


def test_face_review_wl_ww_uses_post_blur_hu() -> None:
    from pydicom import Dataset

    from anonymizer.view.blur_face_results import FACE_REVIEW_WL_HU, FACE_REVIEW_WW_HU, face_review_wl_ww

    ds = Dataset()
    ds.RescaleSlope = 1
    ds.RescaleIntercept = -1024
    wl, ww = face_review_wl_ww(ds)
    assert wl == pytest.approx(FACE_REVIEW_WL_HU)
    assert ww == pytest.approx(FACE_REVIEW_WW_HU)


@patch("anonymizer.controller.blur_face.resolve_face_mask_path")
def test_apply_face_blur_preview_to_series_frames(
    mock_resolve: MagicMock,
    synthetic_head_series: Path,
) -> None:
    volume_img, slice_paths = read_reference_volume(synthetic_head_series)
    shape = sitk.GetArrayFromImage(volume_img).shape
    mask_path = face_mask_cache_path(synthetic_head_series)
    _write_mask(mask_path, shape=shape)
    mock_resolve.return_value = mask_path

    preview = preview_face_blur(synthetic_head_series)
    assert preview.error is None
    assert preview.hu_after is not None

    from anonymizer.controller.create_projections import load_series_frames

    reference_ds, source_frames, _paths = load_series_frames(synthetic_head_series)
    slice_frames = hu_stack_to_viewer_frames(
        preview.hu_after,
        preview.slice_paths,
        reference_ds=reference_ds,
        frame_dtype=source_frames.dtype,
    )
    h, w = slice_frames.shape[1], slice_frames.shape[2]
    projection_placeholder = np.zeros((h, w), dtype=slice_frames.dtype)
    frames = np.stack([projection_placeholder] * 3 + [np.zeros((h, w), dtype=slice_frames.dtype)] * len(slice_paths))
    updated = apply_face_blur_preview_to_series_frames(
        frames,
        preview,
        single_frame=False,
    )

    assert updated.shape == frames.shape
    assert not np.array_equal(updated[3 : 3 + len(slice_paths)], frames[3 : 3 + len(slice_paths)])
    assert np.array_equal(updated[:3], frames[:3])


@patch("anonymizer.controller.blur_face.resolve_face_mask_path")
def test_preview_face_blur_uses_series_volume_context(
    mock_resolve: MagicMock,
    synthetic_head_series: Path,
) -> None:
    from anonymizer.controller.create_projections import load_series_frames

    reference_ds, frames, slice_paths = load_series_frames(synthetic_head_series)
    volume_img, _hu, paths = load_series_volume_for_blur(synthetic_head_series)
    shape = sitk.GetArrayFromImage(volume_img).shape
    mask_path = face_mask_cache_path(synthetic_head_series)
    _write_mask(mask_path, shape=shape)
    mock_resolve.return_value = mask_path

    with patch("anonymizer.controller.blur_face.load_series_volume_for_blur") as mock_load:
        preview = preview_face_blur(
            synthetic_head_series,
            volume_context=SeriesVolumeContext(
                reference_ds=reference_ds,
                slice_frames=frames,
                slice_paths=paths,
            ),
        )
        mock_load.assert_not_called()

    assert preview.error is None
    assert preview.slice_paths == paths
    assert preview.blurred_slice_frames is not None
    assert preview.blurred_slice_frames.shape == frames.shape
    assert preview.hu_after is None
