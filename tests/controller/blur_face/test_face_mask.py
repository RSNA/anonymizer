"""Tests for face mask path resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import SimpleITK as sitk

from anonymizer.controller.blur_face import (
    LEGACY_FACE_MASK_REL,
    FaceBlurGateReason,
    face_blur_gate_message,
    resolve_face_mask_path,
)
from anonymizer.controller.tseg.config import FACE_MASK_FILENAME
from anonymizer.controller.tseg.segment import FaceSegResult, face_mask_cache_path


def _write_face_mask(path: Path, *, voxel_count: int = 1500) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros((24, 64, 64), dtype=np.uint8)
    flat = array.ravel()
    count = min(voxel_count, flat.size)
    flat[:count] = 1
    array = flat.reshape(array.shape)
    sitk.WriteImage(sitk.GetImageFromArray(array), str(path))


def test_resolve_face_mask_path_prefers_cache(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = face_mask_cache_path(series)
    legacy = series / LEGACY_FACE_MASK_REL
    _write_face_mask(cache)
    _write_face_mask(legacy)

    assert resolve_face_mask_path(series) == cache


def test_resolve_face_mask_path_legacy_fallback(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    series = tmp_path / "series"
    series.mkdir()
    legacy = series / LEGACY_FACE_MASK_REL
    _write_face_mask(legacy)

    with caplog.at_level("WARNING"):
        resolved = resolve_face_mask_path(series, run_if_missing=False)

    assert resolved == legacy
    assert "legacy" in caplog.text.lower()


@patch("anonymizer.controller.blur_face.analyze_tseg_face")
def test_resolve_face_mask_path_runs_segmentation(mock_analyze: MagicMock, tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = face_mask_cache_path(series)

    def _create_mask(directory: Path, **kwargs) -> FaceSegResult:
        _write_face_mask(cache)
        return FaceSegResult(
            series_directory=directory,
            face_mask_path=cache,
            slice_count=24,
            face_voxel_count=1000,
            inference_seconds=1.5,
        )

    mock_analyze.side_effect = _create_mask

    assert resolve_face_mask_path(series) == cache
    mock_analyze.assert_called_once()


def test_resolve_face_mask_path_missing_without_run(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()

    with pytest.raises(FileNotFoundError, match=FACE_MASK_FILENAME):
        resolve_face_mask_path(series, run_if_missing=False)


def test_resolve_face_mask_path_rejects_cached_empty_mask(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = face_mask_cache_path(series)
    _write_face_mask(cache, voxel_count=0)

    message = face_blur_gate_message(FaceBlurGateReason.INSUFFICIENT_FACE_MASK)
    with pytest.raises(RuntimeError, match=message.split(".")[0]):
        resolve_face_mask_path(series, run_if_missing=False)
