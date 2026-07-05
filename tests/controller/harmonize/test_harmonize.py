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
    assert merged.geometry is not None
    assert merged.geometry.plane == "axial"
    assert merged.geometry.ts_suitable is True
    mock_falcon.assert_called_once()
    mock_regions.assert_called_once()
    mock_contrast.assert_not_called()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", False)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_reports_geometry_progress(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    progress_events: list[tuple[str, str]] = []

    def on_progress(progress) -> None:
        progress_events.append((progress.stage, progress.message))

    mock_falcon.return_value = [_falcon_result(synthetic_chest_series)]
    mock_regions.return_value = (
        _tseg_region_result(synthetic_chest_series),
        synthetic_chest_series / "volume.nii.gz",
    )

    harmonize_series([synthetic_chest_series], progress=on_progress)

    geometry_messages = [message for stage, message in progress_events if stage == "geometry"]
    assert len(geometry_messages) == 1
    assert geometry_messages[0].startswith("Geometry: axial · volume_3d · TS ok")


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", False)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_skips_tseg_for_scout_localizer(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_scout_ct_series

    scout_dir = build_synthetic_scout_ct_series(tmp_path / "scout")
    progress_events: list[tuple[str, str]] = []

    def on_progress(progress) -> None:
        progress_events.append((progress.stage, progress.message))

    mock_falcon.return_value = [_falcon_result(scout_dir)]

    results = harmonize_series([scout_dir], progress=on_progress)

    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    merged = results[0]
    assert merged.geometry is not None
    assert merged.geometry.ts_suitable is False
    assert merged.geometry.dimensionality == "localizer_2d"
    tseg_messages = [message for stage, message in progress_events if stage == "tseg"]
    assert any("TS skip" in message for message in tseg_messages)


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", False)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_skips_ts_contrast_when_disabled(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_falcon.return_value = [_falcon_result(synthetic_chest_series)]
    mock_regions.return_value = (_tseg_region_result(synthetic_chest_series), synthetic_chest_series / "vol.nii.gz")

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.regions_source == "tseg"
    assert merged.contrast_source == "falcon"
    mock_contrast.assert_not_called()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_execution_order_falcon_then_seg_then_contrast(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    call_log: list[str] = []

    def _falcon(*_args, **_kwargs):
        call_log.append("falcon")
        return [_falcon_result(synthetic_chest_series)]

    def _regions(*_args, **_kwargs):
        call_log.append("regions")
        return (_tseg_region_result(synthetic_chest_series), synthetic_chest_series / "vol.nii.gz")

    def _contrast(*_args, **_kwargs):
        call_log.append("contrast")
        return _tseg_result(synthetic_chest_series)

    mock_falcon.side_effect = _falcon
    mock_regions.side_effect = _regions
    mock_contrast.side_effect = _contrast

    harmonize_series([synthetic_chest_series])
    assert call_log == ["falcon", "regions", "contrast"]


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", False)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_uses_falcon_contrast_when_ts_contrast_disabled(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_falcon.return_value = [_falcon_result(synthetic_chest_series)]
    mock_regions.return_value = (_tseg_region_result(synthetic_chest_series), synthetic_chest_series / "vol.nii.gz")

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.radlex_series_description == "CT Chest Without Contrast"
    assert merged.regions_source == "tseg"
    assert merged.contrast_source == "falcon"
    mock_contrast.assert_not_called()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_uses_tseg_contrast_when_enabled(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_falcon.return_value = [_falcon_result(synthetic_chest_series)]
    mock_regions.return_value = (_tseg_region_result(synthetic_chest_series), synthetic_chest_series / "vol.nii.gz")
    mock_contrast.return_value = _tseg_result(synthetic_chest_series)

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.radlex_series_description == "CT Chest With Contrast"
    assert merged.regions_source == "tseg"
    assert merged.contrast_source == "tseg"


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_falcon_fallback_regions(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_falcon.return_value = [_falcon_result(synthetic_chest_series)]
    mock_regions.return_value = (
        TS_result(
            series_directory=synthetic_chest_series,
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

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.radlex_series_description == "CT Chest Without Contrast"
    assert merged.regions_source == "falcon"
    assert merged.contrast_source == "falcon"
    mock_contrast.assert_not_called()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_tseg_regions_with_contrast_error_uses_falcon_contrast(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_falcon.return_value = [_falcon_result(synthetic_chest_series)]
    mock_regions.return_value = (_tseg_region_result(synthetic_chest_series), synthetic_chest_series / "vol.nii.gz")
    mock_contrast.return_value = TS_result(
        series_directory=synthetic_chest_series,
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

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.regions_source == "tseg"
    assert merged.contrast_source == "falcon"
    assert merged.radlex_series_description == "CT Chest Without Contrast"


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
@patch("anonymizer.controller.harmonize.predict_falcon_series")
def test_harmonize_both_fail(
    mock_falcon: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_falcon.return_value = [_falcon_result(synthetic_chest_series, error="failed")]
    mock_regions.return_value = (
        TS_result(
            series_directory=synthetic_chest_series,
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

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.error is not None
    assert merged.radlex_series_description == ""


def test_harmonize_geometry_result_section_renders_plane() -> None:
    from anonymizer.controller.harmonize import HarmonizedResult
    from anonymizer.controller.tseg.dicom_geometry import SeriesGeometryResult
    from anonymizer.view.series import SeriesView

    geometry = SeriesGeometryResult(
        plane="axial",
        plane_confidence=0.92,
        slice_normal_lps=(0.0, 0.0, 1.0),
        plane_angles_deg={"axial": 8.0, "coronal": 82.0, "sagittal": 82.0},
        dimensionality="volume_3d",
        n_slices=12,
        through_plane_extent_mm=55.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.85,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=True,
        metadata_suspect=False,
        method="dicom_headers",
        notes="",
    )
    result = HarmonizedResult(
        series_directory=Path("/tmp/series"),
        radlex_series_description="CT Chest With Contrast",
        tseg=None,
        falcon=None,
        regions_source="none",
        contrast_source="none",
        geometry=geometry,
    )
    text = SeriesView._format_geometry_result_section(result)
    assert "axial" in text
    assert "volume_3d" in text
    assert "92" in text


def test_geometry_dicom_rows_include_ts_eligibility() -> None:
    from anonymizer.controller.tseg.dicom_geometry import SeriesGeometryResult
    from anonymizer.view.series import SeriesView

    geometry = SeriesGeometryResult(
        plane="coronal",
        plane_confidence=0.7,
        slice_normal_lps=(0.0, 1.0, 0.0),
        plane_angles_deg={"axial": 80.0, "coronal": 10.0, "sagittal": 80.0},
        dimensionality="volume_3d",
        n_slices=20,
        through_plane_extent_mm=100.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=False,
        metadata_suspect=False,
        method="dicom_headers",
        notes="",
    )
    rows = SeriesView._geometry_dicom_rows(geometry)
    assert rows[0][2] == "coronal"
    assert rows[3][2] == "No"


def test_series_geometry_caption_reads_cached_geometry(tmp_path: Path) -> None:
    from anonymizer.controller.tseg.dicom_geometry import resolve_series_geometry
    from anonymizer.view.projection import ProjectionView
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_chest_ct_series

    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    resolve_series_geometry(series_dir)

    caption = ProjectionView._series_geometry_caption(series_dir)
    assert caption == "axial · volume_3d · TS ok"
    assert ProjectionView._series_geometry_caption(tmp_path / "missing") == ""
