"""Tests for face blur save integrity CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import SimpleITK as sitk

from anonymizer.controller.tseg.segment import face_mask_cache_path
from prototyping.ffr.face.save_integrity import (
    default_output_directory,
    run_series_view_face_blur_save,
    verify_series_integrity,
)
from tests.controller.tseg.fixtures import synthetic_head_series


def _write_mask(mask_path: Path, *, shape: tuple[int, int, int]) -> None:
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros(shape, dtype=np.uint8)
    array[:, 32:64, 32:64] = 1
    sitk.WriteImage(sitk.GetImageFromArray(array), str(mask_path))


@patch("prototyping.ffr.face.save_integrity.resolve_face_mask_path")
def test_save_integrity_passes_on_synthetic_series(
    mock_resolve,
    synthetic_head_series: Path,
    tmp_path: Path,
) -> None:
    from anonymizer.controller.blur_face import read_reference_volume

    volume_img, slice_paths = read_reference_volume(synthetic_head_series)
    shape = sitk.GetArrayFromImage(volume_img).shape
    mask_path = face_mask_cache_path(synthetic_head_series)
    _write_mask(mask_path, shape=shape)
    mock_resolve.return_value = mask_path

    output_dir = tmp_path / "1_blurred_face"
    save_ok, error = run_series_view_face_blur_save(synthetic_head_series, output_dir)
    assert save_ok, error
    assert output_dir.is_dir()
    assert len(list(output_dir.glob("*.dcm"))) == len(slice_paths)

    report = verify_series_integrity(synthetic_head_series, output_dir)
    assert report.ok, [issue.message for issue in report.issues if issue.severity.value == "ERROR"]


def test_default_output_directory(synthetic_head_series: Path) -> None:
    assert default_output_directory(synthetic_head_series).name == "1_blurred_face"
