"""Tests for harmonize_series merge logic and sequential pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.falcon.predict import FalconPrediction
from anonymizer.controller.harmonize import harmonize_series
from anonymizer.controller.tseg.segment import TS_result


def _tseg_region_result(series_dir: Path, *, error: str | None = None) -> TS_result:
    return TS_result(
        series_directory=series_dir,
        dominant_region="Chest",
        body_parts_present="Chest",
        multi_region=False,
        region_fraction=0.9,
        iv_contrast=False,
        contrast_phase="",
        phase_probability=0.0,
        radlex_series_description="",
        error=error,
    )


def _tseg_result(series_dir: Path, *, error: str | None = None) -> TS_result:
    return TS_result(
        series_directory=series_dir,
        dominant_region="Chest",
        body_parts_present="Chest",
        multi_region=False,
        region_fraction=0.9,
        iv_contrast=True,
        contrast_phase="portal_venous",
        phase_probability=0.88,
        radlex_series_description="CT Chest With Contrast",
        error=error,
    )


def _falcon_result(series_dir: Path, *, error: str | None = None) -> FalconPrediction:
    return FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.95,
        iv_contrast=False,
        iv_contrast_confidence=0.2,
        radlex_series_description="CT Chest Without Contrast",
        error=error,
    )


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", False)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_with_synthetic_chest_series(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    nifti = synthetic_chest_series / "volume.nii.gz"
    mock_falcon.return_value = [_falcon_result(synthetic_chest_series)]
    mock_regions.return_value = (_tseg_region_result(synthetic_chest_series), nifti)

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.series_directory == synthetic_chest_series
    assert merged.radlex_series_description == "CT Chest Without Contrast"
    assert merged.regions_source == "tseg"
    assert merged.contrast_source == "falcon"
    mock_falcon.assert_called_once()
    mock_regions.assert_called_once()
    mock_contrast.assert_not_called()


@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", False)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_skips_ts_contrast_when_disabled(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    mock_falcon.return_value = [_falcon_result(series_dir)]
    mock_regions.return_value = (_tseg_region_result(series_dir), tmp_path / "vol.nii.gz")

    results = harmonize_series([series_dir])
    merged = results[0]
    assert merged.regions_source == "tseg"
    assert merged.contrast_source == "falcon"
    mock_contrast.assert_not_called()


@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_execution_order_falcon_then_seg_then_contrast(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    call_log: list[str] = []

    def _falcon(*_args, **_kwargs):
        call_log.append("falcon")
        return [_falcon_result(series_dir)]

    def _regions(*_args, **_kwargs):
        call_log.append("regions")
        return (_tseg_region_result(series_dir), tmp_path / "vol.nii.gz")

    def _contrast(*_args, **_kwargs):
        call_log.append("contrast")
        return _tseg_result(series_dir)

    mock_falcon.side_effect = _falcon
    mock_regions.side_effect = _regions
    mock_contrast.side_effect = _contrast

    harmonize_series([series_dir])
    assert call_log == ["falcon", "regions", "contrast"]


@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", False)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_uses_falcon_contrast_when_ts_contrast_disabled(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    mock_falcon.return_value = [_falcon_result(series_dir)]
    mock_regions.return_value = (_tseg_region_result(series_dir), tmp_path / "vol.nii.gz")

    results = harmonize_series([series_dir])
    merged = results[0]
    assert merged.radlex_series_description == "CT Chest Without Contrast"
    assert merged.regions_source == "tseg"
    assert merged.contrast_source == "falcon"
    mock_contrast.assert_not_called()


@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_uses_tseg_contrast_when_enabled(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    mock_falcon.return_value = [_falcon_result(series_dir)]
    mock_regions.return_value = (_tseg_region_result(series_dir), tmp_path / "vol.nii.gz")
    mock_contrast.return_value = _tseg_result(series_dir)

    results = harmonize_series([series_dir])
    merged = results[0]
    assert merged.radlex_series_description == "CT Chest With Contrast"
    assert merged.regions_source == "tseg"
    assert merged.contrast_source == "tseg"


@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_falcon_fallback_regions(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    mock_falcon.return_value = [_falcon_result(series_dir)]
    mock_regions.return_value = (
        TS_result(
            series_directory=series_dir,
            dominant_region="",
            body_parts_present="",
            multi_region=False,
            region_fraction=0.0,
            iv_contrast=False,
            contrast_phase="",
            phase_probability=0.0,
            radlex_series_description="",
            error="segmentation failed",
        ),
        None,
    )

    results = harmonize_series([series_dir])
    merged = results[0]
    assert merged.radlex_series_description == "CT Chest Without Contrast"
    assert merged.regions_source == "falcon"
    assert merged.contrast_source == "falcon"
    mock_contrast.assert_not_called()


@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_tseg_regions_with_contrast_error_uses_falcon_contrast(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    mock_falcon.return_value = [_falcon_result(series_dir)]
    mock_regions.return_value = (_tseg_region_result(series_dir), tmp_path / "vol.nii.gz")
    mock_contrast.return_value = TS_result(
        series_directory=series_dir,
        dominant_region="Chest",
        body_parts_present="Chest",
        multi_region=False,
        region_fraction=0.9,
        iv_contrast=False,
        contrast_phase="",
        phase_probability=0.0,
        radlex_series_description="",
        error="RuntimeError: XGBoost is required",
    )

    results = harmonize_series([series_dir])
    merged = results[0]
    assert merged.regions_source == "tseg"
    assert merged.contrast_source == "falcon"
    assert merged.radlex_series_description == "CT Chest Without Contrast"


@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_both_fail(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    mock_falcon.return_value = [_falcon_result(series_dir, error="failed")]
    mock_regions.return_value = (
        TS_result(
            series_directory=series_dir,
            dominant_region="",
            body_parts_present="",
            multi_region=False,
            region_fraction=0.0,
            iv_contrast=False,
            contrast_phase="",
            phase_probability=0.0,
            radlex_series_description="",
            error="failed",
        ),
        None,
    )

    results = harmonize_series([series_dir])
    merged = results[0]
    assert merged.error is not None
    assert merged.radlex_series_description == ""
