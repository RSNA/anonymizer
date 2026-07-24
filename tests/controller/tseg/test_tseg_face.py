"""Tests for TotalSegmentator face segmentation API (mocked inference)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import numpy as np
import SimpleITK as sitk

from anonymizer.controller.blur_face_gate import FaceBlurGateReason, face_blur_gate_message
from anonymizer.controller.tseg.config import FACE_MASK_FILENAME
from anonymizer.controller.tseg.segment import (
    AnalysisProgress,
    FaceSegResult,
    analyze_tseg_face,
    dicom_series_to_nifti,
    face_mask_cache_path,
    run_face_segmentation,
    series_cache_dir,
)
from tests.controller.tseg.support.synthetic_ct import build_synthetic_scout_ct_series

pytestmark = pytest.mark.usefixtures("synthetic_ct_asset_dirs")


def _write_face_mask(mask_path: Path, *, voxel_count: int = 1500) -> None:
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros((24, 64, 64), dtype=np.uint8)
    flat = array.ravel()
    count = min(voxel_count, flat.size)
    flat[:count] = 1
    array = flat.reshape(array.shape)
    sitk.WriteImage(sitk.GetImageFromArray(array), str(mask_path))


def _write_empty_face_mask(mask_path: Path) -> None:
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros((4, 8, 8), dtype=np.uint8)
    sitk.WriteImage(sitk.GetImageFromArray(array), str(mask_path))


@patch("anonymizer.controller.tseg.segment.run_face_segmentation")
@patch("anonymizer.controller.tseg.segment.dicom_series_to_nifti")
def test_analyze_tseg_face_empty_geometry_skip(
    mock_nifti: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_scout_ct_series(tmp_path / "scout")

    result = analyze_tseg_face(series_dir)

    assert isinstance(result, FaceSegResult)
    assert result.error is not None
    assert result.face_mask_path is None
    assert "localizer" in result.error.lower() or "not suitable" in result.error.lower()
    mock_nifti.assert_not_called()
    mock_run.assert_not_called()


@patch("anonymizer.controller.tseg.segment.run_face_segmentation")
@patch("anonymizer.controller.tseg.segment.dicom_series_to_nifti")
def test_analyze_tseg_face_reuses_cached_nifti(
    mock_nifti: MagicMock,
    mock_run: MagicMock,
    synthetic_head_series: Path,
) -> None:
    cache = series_cache_dir(synthetic_head_series)
    dicom_series_to_nifti(synthetic_head_series, cache / "volume.nii.gz")
    _write_face_mask(cache / "seg" / FACE_MASK_FILENAME)

    result = analyze_tseg_face(synthetic_head_series)

    assert result.error is None
    assert result.face_mask_path == face_mask_cache_path(synthetic_head_series)
    mock_nifti.assert_not_called()
    mock_run.assert_not_called()
    assert result.slice_count > 0
    assert result.face_voxel_count > 0
    assert result.inference_seconds == 0.0


@patch("anonymizer.controller.tseg.segment.run_face_segmentation")
def test_analyze_tseg_face_reuses_cached_mask(
    mock_run: MagicMock,
    synthetic_head_series: Path,
) -> None:
    cache = series_cache_dir(synthetic_head_series)
    dicom_series_to_nifti(synthetic_head_series, cache / "volume.nii.gz")
    _write_face_mask(cache / "seg" / FACE_MASK_FILENAME)

    result = analyze_tseg_face(synthetic_head_series)

    assert result.error is None
    mock_run.assert_not_called()
    assert result.inference_seconds == 0.0


@patch("anonymizer.controller.tseg.segment.run_face_segmentation")
def test_analyze_tseg_face_runs_inference(
    mock_run: MagicMock,
    synthetic_head_series: Path,
) -> None:
    progress_events: list[AnalysisProgress] = []

    def _fake_run(nifti_path: Path, output_dir: Path, **kwargs) -> float:
        _write_face_mask(output_dir / FACE_MASK_FILENAME)
        return 3.5

    mock_run.side_effect = _fake_run

    result = analyze_tseg_face(
        synthetic_head_series,
        progress=lambda event: progress_events.append(event),
    )

    assert result.error is None
    assert result.face_mask_path == face_mask_cache_path(synthetic_head_series)
    assert result.inference_seconds == 3.5
    assert result.face_voxel_count > 0
    mock_run.assert_called_once()
    assert any(event.stage == "prepare" for event in progress_events)


@patch("anonymizer.controller.tseg.segment.run_face_segmentation")
def test_analyze_tseg_face_force_reruns_inference(
    mock_run: MagicMock,
    synthetic_head_series: Path,
) -> None:
    cache = series_cache_dir(synthetic_head_series)
    dicom_series_to_nifti(synthetic_head_series, cache / "volume.nii.gz")
    _write_face_mask(cache / "seg" / FACE_MASK_FILENAME)
    mock_run.return_value = 2.0

    result = analyze_tseg_face(synthetic_head_series, force=True)

    assert result.error is None
    mock_run.assert_called_once()
    assert result.inference_seconds == 2.0


@patch("anonymizer.controller.tseg.segment.run_face_segmentation")
def test_analyze_tseg_face_fails_on_empty_mask_after_inference(
    mock_run: MagicMock,
    synthetic_head_series: Path,
) -> None:
    def _fake_run(nifti_path: Path, output_dir: Path, **kwargs) -> float:
        _write_empty_face_mask(output_dir / FACE_MASK_FILENAME)
        return 1.0

    mock_run.side_effect = _fake_run

    result = analyze_tseg_face(synthetic_head_series)

    assert result.error == face_blur_gate_message(FaceBlurGateReason.INSUFFICIENT_FACE_MASK)
    assert result.face_mask_path is None
    mock_run.assert_called_once()


@patch("anonymizer.controller.tseg.segment.run_face_segmentation")
def test_analyze_tseg_face_fails_on_cached_empty_mask(
    mock_run: MagicMock,
    synthetic_head_series: Path,
) -> None:
    cache = series_cache_dir(synthetic_head_series)
    dicom_series_to_nifti(synthetic_head_series, cache / "volume.nii.gz")
    _write_empty_face_mask(cache / "seg" / FACE_MASK_FILENAME)

    result = analyze_tseg_face(synthetic_head_series)

    assert result.error == face_blur_gate_message(FaceBlurGateReason.INSUFFICIENT_FACE_MASK)
    assert result.face_mask_path is None
    mock_run.assert_not_called()


@patch("anonymizer.controller.tseg.segment.run_face_segmentation")
def test_analyze_tseg_face_invalidates_stale_volume_cache(
    mock_run: MagicMock,
    synthetic_head_series: Path,
) -> None:
    cache = series_cache_dir(synthetic_head_series)
    dicom_series_to_nifti(synthetic_head_series, cache / "volume.nii.gz")
    _write_empty_face_mask(cache / "seg" / FACE_MASK_FILENAME)

    stale_volume = sitk.GetImageFromArray(np.zeros((8, 8, 8), dtype=np.int16))
    sitk.WriteImage(stale_volume, str(cache / "volume.nii.gz"))

    def _fake_run(nifti_path: Path, output_dir: Path, **kwargs) -> float:
        _write_face_mask(output_dir / FACE_MASK_FILENAME)
        return 2.0

    mock_run.side_effect = _fake_run

    result = analyze_tseg_face(synthetic_head_series)

    assert result.error is None
    assert result.face_voxel_count >= 1500
    mock_run.assert_called_once()
    assert _nifti_slice_count(cache / "volume.nii.gz") == result.slice_count


def _nifti_slice_count(nifti_path: Path) -> int:
    image = sitk.ReadImage(str(nifti_path))
    return int(image.GetSize()[2])


@patch("anonymizer.controller.tseg.segment.release_working_memory")
@patch("anonymizer.controller.tseg.segment.sequential_ml_context")
@patch("anonymizer.controller.tseg.segment._require_totalsegmentator")
def test_run_face_segmentation_calls_totalsegmentator(
    mock_require: MagicMock,
    mock_context: MagicMock,
    mock_release: MagicMock,
    tmp_path: Path,
) -> None:
    mock_ts = MagicMock()

    def _write_face(input_path: str, output_dir: str, **kwargs) -> None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        _write_face_mask(out / FACE_MASK_FILENAME)

    mock_ts.side_effect = _write_face
    mock_require.return_value = mock_ts
    mock_context.return_value.__enter__ = MagicMock(return_value=None)
    mock_context.return_value.__exit__ = MagicMock(return_value=False)

    nifti_path = tmp_path / "volume.nii.gz"
    sitk.WriteImage(
        sitk.GetImageFromArray(np.zeros((4, 8, 8), dtype=np.int16)),
        str(nifti_path),
    )
    output_dir = tmp_path / "seg"

    seconds = run_face_segmentation(nifti_path, output_dir, device="cpu")

    mock_ts.assert_called_once()
    _, call_kwargs = mock_ts.call_args
    assert call_kwargs["task"] == "face"
    assert call_kwargs["fast"] is False
    assert call_kwargs["fastest"] is False
    assert call_kwargs["quiet"] is True
    assert call_kwargs["device"] == "cpu"
    assert seconds >= 0.0
    assert (output_dir / FACE_MASK_FILENAME).is_file()


def test_face_mask_cache_path(synthetic_head_series: Path) -> None:
    expected = synthetic_head_series.resolve() / "A_TS_SEG" / "seg" / FACE_MASK_FILENAME
    assert face_mask_cache_path(synthetic_head_series) == expected
