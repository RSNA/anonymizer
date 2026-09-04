"""Tests for blur_face_series orchestration (mocked segmentation)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import SimpleITK as sitk

from anonymizer.controller.ai.blur_face import blur_face_series, read_reference_volume
from anonymizer.controller.ai.tseg.segment import face_mask_cache_path


def _write_mask(mask_path: Path, *, shape: tuple[int, int, int]) -> None:
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros(shape, dtype=np.uint8)
    array[:, 32:64, 32:64] = 1
    sitk.WriteImage(sitk.GetImageFromArray(array), str(mask_path))


@patch("anonymizer.controller.ai.blur_face.pipeline.resolve_face_mask_path")
def test_blur_face_series_success(
    mock_resolve: MagicMock,
    synthetic_head_series: Path,
    tmp_path: Path,
) -> None:
    volume_img, slice_paths = read_reference_volume(synthetic_head_series)
    shape = sitk.GetArrayFromImage(volume_img).shape
    mask_path = face_mask_cache_path(synthetic_head_series)
    _write_mask(mask_path, shape=shape)
    mock_resolve.return_value = mask_path

    out_dir = tmp_path / "blurred"
    result = blur_face_series(synthetic_head_series, output_directory=out_dir)

    assert result.error is None
    assert result.output_directory == out_dir.resolve()
    assert result.face_mask_path == mask_path
    assert result.slice_count == len(slice_paths)
    assert result.qa_stats is not None
    assert result.qa_stats.outside_clean
    assert out_dir.is_dir()
    assert any(out_dir.glob("*.dcm"))


@patch("anonymizer.controller.ai.blur_face.pipeline.resolve_face_mask_path")
def test_blur_face_series_returns_error(mock_resolve: MagicMock, synthetic_head_series: Path) -> None:
    mock_resolve.side_effect = RuntimeError("Series not suitable for TotalSegmentator")

    result = blur_face_series(synthetic_head_series)

    assert result.error is not None
    assert "not suitable" in result.error.lower()
    assert result.qa_stats is None
