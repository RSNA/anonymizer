"""Tests for harmonize_series Playbook merge logic and sequential pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
        radlex_series_description="",
        error=error,
    )


def _head_tseg_result(series_dir: Path) -> TS_result:
    return TS_result(
        series_directory=series_dir,
        dominant_region="Head",
        body_parts_present="Head",
        multi_region=False,
        region_fraction=1.0,
        iv_contrast=False,
        contrast_phase="native",
        phase_probability=1.0,
        radlex_series_description="",
        structures_present={"brain": 50000},
    )


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
def test_harmonize_builds_playbook_description_from_tseg_only(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    nifti = synthetic_chest_series / "volume.nii.gz"
    mock_regions.return_value = (_tseg_region_result(synthetic_chest_series), nifti)
    mock_contrast.return_value = _tseg_result(synthetic_chest_series)

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]

    assert merged.error is None
    assert merged.radlex_series_description == "Ch Ax PortVen"
    assert merged.playbook is not None
    assert merged.playbook.body_part_code == "Ch"
    assert merged.playbook.iv_contrast_code == "PortVen"
    assert merged.playbook.anatomic_plane_code == "Ax"
    mock_regions.assert_called_once()
    mock_contrast.assert_called_once()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
def test_harmonize_reports_geometry_progress(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    progress_events: list[tuple[str, str]] = []

    def on_progress(progress) -> None:
        progress_events.append((progress.stage, progress.message))

    mock_regions.return_value = (
        _tseg_region_result(synthetic_chest_series),
        synthetic_chest_series / "volume.nii.gz",
    )
    mock_contrast.return_value = _tseg_result(synthetic_chest_series)

    harmonize_series([synthetic_chest_series], progress=on_progress)

    geometry_messages = [message for stage, message in progress_events if stage == "geometry"]
    assert len(geometry_messages) == 1
    assert geometry_messages[0].startswith("Geometry analysis: Axial · Diagnostic 3D volume · TS ok")


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
def test_harmonize_skips_tseg_for_scout_localizer(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_scout_ct_series

    scout_dir = build_synthetic_scout_ct_series(tmp_path / "scout")
    progress_events: list[tuple[str, str]] = []

    def on_progress(progress) -> None:
        progress_events.append((progress.stage, progress.message))

    results = harmonize_series([scout_dir], progress=on_progress)

    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    merged = results[0]
    assert merged.geometry is not None
    assert merged.geometry.ts_suitable is False
    assert merged.error is None
    assert merged.radlex_series_description == "Ch WO Localizer"
    assert merged.playbook is not None
    assert merged.playbook.body_part_code == "Ch"
    assert merged.playbook.series_type_code == "Localizer"
    tseg_messages = [message for stage, message in progress_events if stage == "tseg"]
    assert any(
        "Localizer and scout series are not suitable for anatomy analysis" in message for message in tseg_messages
    )


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", False)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
def test_harmonize_requires_ts_contrast_for_playbook_merge(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_regions.return_value = (
        _tseg_region_result(synthetic_chest_series),
        synthetic_chest_series / "vol.nii.gz",
    )

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]

    assert merged.radlex_series_description == ""
    assert merged.error is not None
    assert "contrast phase is required" in merged.error
    mock_contrast.assert_not_called()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
def test_harmonize_execution_order_seg_then_contrast(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    call_log: list[str] = []

    def _regions(*_args, **_kwargs):
        call_log.append("regions")
        return (_tseg_region_result(synthetic_chest_series), synthetic_chest_series / "vol.nii.gz")

    def _contrast(*_args, **_kwargs):
        call_log.append("contrast")
        return _tseg_result(synthetic_chest_series)

    mock_regions.side_effect = _regions
    mock_contrast.side_effect = _contrast

    harmonize_series([synthetic_chest_series])
    assert call_log == ["regions", "contrast"]


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
def test_harmonize_fails_when_tseg_regions_unavailable(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
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
    assert merged.radlex_series_description == ""
    assert merged.error is not None
    mock_contrast.assert_not_called()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.harmonize.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.harmonize.analyze_tseg_contrast")
@patch("anonymizer.controller.harmonize.analyze_tseg_regions")
def test_harmonize_fails_when_tseg_contrast_unavailable(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_regions.return_value = (
        _tseg_region_result(synthetic_chest_series),
        synthetic_chest_series / "vol.nii.gz",
    )
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
    assert merged.radlex_series_description == ""
    assert merged.error is not None


def test_harmonize_analysis_section_renders_playbook_attributes() -> None:
    from anonymizer.controller.tseg.dicom_geometry import SeriesGeometryResult
    from anonymizer.controller.tseg.radlex_playbook import PlaybookHarmonizeAttributes, harmonize_analysis_rows

    tseg = _head_tseg_result(Path("/tmp/series"))
    attributes = PlaybookHarmonizeAttributes(
        body_part_code="Brain",
        anatomic_plane_code="Ax",
        iv_contrast_code="WO",
        series_type_code="",
        body_part_confidence=1.0,
        plane_confidence=0.99,
        contrast_confidence=1.0,
        contrast_phase="native",
    )
    geometry = SeriesGeometryResult(
        plane="axial",
        plane_confidence=0.99,
        slice_normal_lps=(0.0, 0.0, 1.0),
        plane_angles_deg={"axial": 5.0, "coronal": 85.0, "sagittal": 85.0},
        dimensionality="volume_3d",
        n_slices=32,
        through_plane_extent_mm=150.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=True,
        metadata_suspect=False,
        method="dicom_headers",
        notes="",
    )
    rows = harmonize_analysis_rows(attributes, geometry=geometry, tseg=tseg)
    text = "\n".join(" | ".join(row) for row in rows)
    assert rows[0][1] == "Brain"
    assert "[Brain]" not in text
    assert "Brain" in text
    assert "Ax" in text
    assert "WO" in text
    assert "Head (dominant: Head)" in text
    assert "Axial · Diagnostic 3D volume · TS ok" in text
    assert "native ·" in text and "confidence" in text
    assert "TotalSegmentator anatomy" in text
    assert "TotalSegmentator contrast" in text
    assert "DICOM ImageOrientationPatient" in text
    assert "FALCON" not in text


def test_harmonize_dicom_table_includes_all_relevant_fields() -> None:
    from pydicom import dcmread
    from pydicom.data import get_testdata_file

    from anonymizer.controller.tseg.radlex_playbook import harmonize_dicom_rows

    ds = dcmread(get_testdata_file("CT_small.dcm"))
    rows = harmonize_dicom_rows(ds)
    labels = [row[0] for row in rows]
    assert "(geometry)" not in "".join(row[1] for row in rows)
    assert "Acquisition plane" not in labels
    assert len(rows) == 16
    assert any(row[2] == "—" for row in rows)
    assert any(row[2] != "—" for row in rows)


def test_series_description_is_harmonized_when_cache_matches() -> None:
    from pydicom import Dataset

    from anonymizer.controller.harmonize import series_description_is_harmonized

    ds = Dataset()
    ds.SeriesDescription = "Ch Ax PortVen"

    with patch(
        "anonymizer.controller.harmonize.harmonized_description_from_cache",
        return_value="Ch Ax PortVen",
    ):
        assert series_description_is_harmonized(Path("/tmp/series"), ds) is True


def test_series_description_is_harmonized_unknown_without_cache() -> None:
    from pydicom import Dataset

    from anonymizer.controller.harmonize import series_description_is_harmonized

    ds = Dataset()
    ds.SeriesDescription = "Legacy Description"

    with patch(
        "anonymizer.controller.harmonize.harmonized_description_from_cache",
        return_value=None,
    ):
        assert series_description_is_harmonized(Path("/tmp/series"), ds) is None


def test_harmonize_context_hint_when_already_harmonized() -> None:
    from pydicom import Dataset

    from anonymizer.controller.harmonize import harmonize_context_hint

    ds = Dataset()
    ds.Modality = "CT"
    ds.SeriesDescription = "Ch Ax PortVen"

    with patch(
        "anonymizer.controller.harmonize.series_description_is_harmonized",
        return_value=True,
    ):
        hint = harmonize_context_hint(Path("/tmp/series"), ds)

    assert hint is not None
    assert "Clear TS Cache" in hint


def test_harmonize_context_hint_omits_non_ct_and_unknown() -> None:
    from pydicom import Dataset

    from anonymizer.controller.harmonize import harmonize_context_hint

    mr = Dataset()
    mr.Modality = "MR"
    assert harmonize_context_hint(Path("/tmp/series"), mr) is None

    ct = Dataset()
    ct.Modality = "CT"
    with patch(
        "anonymizer.controller.harmonize.series_description_is_harmonized",
        return_value=None,
    ):
        assert harmonize_context_hint(Path("/tmp/series"), ct) is None
