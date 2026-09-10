"""Tests for harmonize_series Playbook merge logic and sequential pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.ai.harmonize import harmonize_series
from anonymizer.controller.ai.tseg.segment import NO_ANATOMY_REGIONS_ERROR, TS_result


@pytest.fixture(autouse=True)
def _disable_ct_harmonize_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep dual-pass region mocks on the ROI anatomy path (single-pass covered elsewhere)."""
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.config.ENABLE_CT_HARMONIZE_SINGLE_PASS",
        False,
    )


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
        structures_present={"brain": 50000},
    )


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
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
@patch("anonymizer.controller.ai.harmonize.pipeline.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_mpr_reformat_detects_modifier_not_in_description(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_derived_coronal_mpr_series

    mpr_dir = build_synthetic_derived_coronal_mpr_series(tmp_path / "mpr")
    nifti = mpr_dir / "volume.nii.gz"
    mock_regions.return_value = (_tseg_region_result(mpr_dir), nifti)
    mock_contrast.return_value = _tseg_result(mpr_dir)

    merged = harmonize_series([mpr_dir])[0]

    assert merged.error is None
    assert merged.playbook is not None
    assert merged.geometry is not None
    assert merged.geometry.provenance == "derived_reformat"
    assert merged.playbook.series_type_modifier_code == "MPR"
    assert merged.playbook.series_type_code == ""
    assert "MPR" not in merged.radlex_series_description
    assert merged.radlex_series_description == "Ch Cor PortVen"


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
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
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_skips_tseg_for_haste_sag_localizer(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_haste_sag_series

    haste_dir = build_synthetic_haste_sag_series(tmp_path / "haste_sag")
    progress_events: list[tuple[str, str]] = []

    def on_progress(progress) -> None:
        progress_events.append((progress.stage, progress.message))

    results = harmonize_series([haste_dir], progress=on_progress)

    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    merged = results[0]
    assert merged.geometry is not None
    assert merged.geometry.dimensionality == "localizer_2d"
    assert merged.geometry.ts_suitable is False
    assert merged.error is None
    assert merged.playbook is not None
    assert merged.playbook.series_type_code == "Localizer"
    tseg_messages = [message for stage, message in progress_events if stage == "tseg"]
    assert any(
        "Localizer and scout series are not suitable for anatomy analysis" in message for message in tseg_messages
    )


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_skips_tseg_for_breast_adc_postprocess(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_breast_adc_mr_series

    adc_dir = build_synthetic_breast_adc_mr_series(tmp_path / "adc")
    results = harmonize_series([adc_dir])

    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    merged = results[0]
    assert merged.geometry is not None
    assert merged.geometry.ts_suitable is False
    assert merged.error is None
    assert merged.playbook is not None
    assert merged.playbook.body_part_code == "Breast"
    assert merged.playbook.anatomic_plane_code == "Ax"
    assert merged.playbook.series_type_code == "Postprocess"
    assert "Postprocess" in merged.radlex_series_description


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_skips_tseg_for_breast_anatomical_mr(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_breast_mr_anatomical_series

    breast_dir = build_synthetic_breast_mr_anatomical_series(tmp_path / "breast_t2")
    results = harmonize_series([breast_dir])

    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    merged = results[0]
    assert merged.error is None
    assert merged.playbook is not None
    assert merged.playbook.body_part_code == "Breast"
    assert merged.playbook.anatomic_plane_code == "Ax"
    assert merged.playbook.series_type_code == ""
    assert merged.playbook.slice_thickness_code == ""
    assert merged.playbook.series_type_modifier_code == ""
    assert merged.radlex_series_description == "Breast Ax W"


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_metadata_merge_for_fused_series(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_fused_pet_ct_series

    fused_dir = build_synthetic_fused_pet_ct_series(tmp_path / "fused")
    results = harmonize_series([fused_dir])

    mock_regions.assert_not_called()
    merged = results[0]
    assert merged.error is None
    assert merged.playbook is not None
    assert merged.playbook.series_type_code == "Fused"
    assert "Fused" in merged.radlex_series_description


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_metadata_merge_for_bolus_monitoring(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_bolus_monitor_series

    monitor_dir = build_synthetic_bolus_monitor_series(tmp_path / "monitor")
    results = harmonize_series([monitor_dir])

    mock_regions.assert_not_called()
    merged = results[0]
    assert merged.error is None
    assert merged.playbook is not None
    assert merged.playbook.series_type_code == "Monitoring"
    assert merged.radlex_series_description == "Ch WO Monitoring"


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
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
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_single_slice_topogram_as_localizer(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_scout_ct_series

    topogram_dir = build_synthetic_scout_ct_series(tmp_path / "topogram", num_slices=1)
    results = harmonize_series([topogram_dir])

    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    merged = results[0]
    assert merged.error is None
    assert merged.geometry is not None
    assert merged.geometry.dimensionality == "localizer_2d"
    assert merged.playbook is not None
    assert merged.playbook.series_type_code == "Localizer"
    assert "Localizer" in merged.radlex_series_description


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_single_slice_ct_guesses_from_dicom(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_single_slice_ct_series

    series_dir = build_synthetic_single_slice_ct_series(tmp_path / "single")
    results = harmonize_series([series_dir])

    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    merged = results[0]
    assert merged.error is None
    assert merged.geometry is not None
    assert merged.geometry.dimensionality == "single_slice_2d"
    assert merged.geometry.ts_suitable is False
    assert merged.playbook is not None
    assert merged.playbook.body_part_code == "Ch"
    assert merged.playbook.anatomic_plane_code == "Ax"
    assert merged.radlex_series_description == "Ch Ax WO"


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_single_slice_mr_guesses_from_dicom(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_single_slice_mr_series

    series_dir = build_synthetic_single_slice_mr_series(tmp_path / "mr_single")
    results = harmonize_series([series_dir])

    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    merged = results[0]
    assert merged.error is None
    assert merged.geometry is not None
    assert merged.geometry.dimensionality == "single_slice_2d"
    assert merged.geometry.ts_suitable is False
    assert merged.geometry.ts_skip_category == "single_slice"
    assert merged.playbook is not None
    assert merged.playbook.body_part_code == "Brain"
    assert merged.playbook.anatomic_plane_code == "Ax"
    # MR uses DICOM IV-contrast text (WITHOUT CONTRAST → WO), not TS phase ML.
    assert merged.playbook.iv_contrast_code == "WO"
    assert merged.radlex_series_description == "Brain Ax WO"


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_single_slice_mr_with_contrast_from_dicom(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from tests.controller.tseg.support.synthetic_ct import build_synthetic_single_slice_mr_series

    series_dir = build_synthetic_single_slice_mr_series(
        tmp_path / "mr_single_w",
        series_description="T1 AXIAL POST GAD",
        study_description="MRI BRAIN WITH CONTRAST",
    )
    results = harmonize_series([series_dir])

    mock_regions.assert_not_called()
    merged = results[0]
    assert merged.error is None
    assert merged.playbook is not None
    assert merged.playbook.iv_contrast_code == "W"
    assert merged.radlex_series_description == "Brain Ax W"


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_smart_prep_single_slice_as_monitoring(
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    from pydicom import dcmread

    from tests.controller.tseg.support.synthetic_ct import build_synthetic_single_slice_ct_series

    series_dir = build_synthetic_single_slice_ct_series(tmp_path / "smart_prep")
    for path in series_dir.glob("*.dcm"):
        ds = dcmread(path)
        ds.StudyDescription = "CT CHEST PULMONARY EMBOLISM (CTPE)"
        ds.SeriesDescription = "PE Smart Prep Left Atrium"
        if hasattr(ds, "BodyPartExamined"):
            del ds.BodyPartExamined
        ds.save_as(path)

    results = harmonize_series([series_dir])
    mock_regions.assert_not_called()
    merged = results[0]
    assert merged.error is None
    assert merged.playbook is not None
    assert merged.playbook.body_part_code == "Ch"
    assert merged.playbook.series_type_code == "Monitoring"
    assert merged.radlex_series_description == "Ch WO Monitoring"


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.ENABLE_TS_CONTRAST", False)
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
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
@patch("anonymizer.controller.ai.harmonize.pipeline.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
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
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_falls_back_to_dicom_when_tseg_regions_empty(
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
            error=NO_ANATOMY_REGIONS_ERROR,
        ),
        None,
    )

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.error is None
    assert merged.radlex_series_description == "Ch Ax WO"
    assert merged.playbook is not None
    assert merged.playbook.body_part_code == "Ch"
    mock_contrast.assert_not_called()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_fails_when_segmentation_errors(
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
            error="EOFError: Compressed file ended before the end-of-stream marker was reached",
        ),
        None,
    )

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.radlex_series_description == ""
    assert merged.error is not None
    assert "EOFError" in merged.error
    mock_contrast.assert_not_called()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
def test_harmonize_fails_when_tseg_and_dicom_body_part_unavailable(
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
            error="segmentation failed",
        ),
        None,
    )

    with patch(
        "anonymizer.controller.ai.harmonize.playbook.map_body_part_from_dicom",
        side_effect=ValueError("Could not determine Playbook body part"),
    ):
        results = harmonize_series([synthetic_chest_series])

    merged = results[0]
    assert merged.radlex_series_description == ""
    assert merged.error == "segmentation failed"
    mock_contrast.assert_not_called()


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
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
        error="RuntimeError: XGBoost is required",
    )

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]
    assert merged.radlex_series_description == ""
    assert merged.error is not None


def test_harmonize_analysis_section_renders_playbook_attributes() -> None:
    from anonymizer.controller.ai.tseg.dicom_geometry import SeriesGeometryResult
    from anonymizer.controller.ai.harmonize.playbook import PlaybookHarmonizeAttributes, harmonize_analysis_rows

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
    assert len(rows) == 6
    assert [row[0] for row in rows] == [
        "Body Part",
        "Anatomic Plane",
        "IV Contrast Phase",
        "Slice Thickness",
        "Series Type",
        "Series Type Modifier",
    ]
    assert rows[0][1] == "Brain"
    assert "[Brain]" not in text
    assert "Brain" in text
    assert "Ax" in text
    assert "WO" in text
    assert "Head (dominant: Head)" in text
    assert "Axial · Diagnostic 3D volume · TS ok" in text
    assert "Native ·" in text and "confidence" in text
    assert "TotalSegmentator anatomy (3 mm)" in text
    assert "TotalSegmentator contrast" in text
    assert "DICOM ImageOrientationPatient" in text
    assert "FALCON" not in text


def test_harmonize_dicom_table_includes_all_relevant_fields() -> None:
    from pydicom import Dataset, dcmread
    from pydicom.data import get_testdata_file

    from anonymizer.controller.ai.harmonize.playbook import harmonize_dicom_rows

    ds = dcmread(get_testdata_file("CT_small.dcm"))
    rows = harmonize_dicom_rows(ds)
    labels = [row[0] for row in rows]
    assert "(geometry)" not in "".join(row[1] for row in rows)
    assert "Acquisition plane" not in labels
    assert "Slice Thickness" in labels
    assert "Spacing Between Slices" in labels
    assert "Image Orientation Patient" in labels
    assert "Contrast Bolus Agent" in labels
    assert "View Position" not in labels
    assert "Image Laterality" not in labels
    assert "Series Number" not in labels
    assert "Scanning Sequence" not in labels
    assert "Patient Orientation" not in labels
    assert any(row[2] == "—" for row in rows)
    assert any(row[2] != "—" for row in rows)


def test_harmonize_dicom_table_xr_omits_ct_fields() -> None:
    from pydicom.dataset import Dataset

    from anonymizer.controller.ai.harmonize.playbook import harmonize_dicom_rows

    ds = Dataset()
    ds.Modality = "CR"
    ds.BodyPartExamined = "CHEST"
    ds.ViewPosition = "AP"
    rows = harmonize_dicom_rows(ds)
    labels = [row[0] for row in rows]
    assert "Modality" in labels
    assert "Body Part Examined" in labels
    assert "View Position" in labels
    assert "Image Laterality" in labels
    assert "Slice Thickness" not in labels
    assert "Image Orientation Patient" not in labels
    assert "Contrast Bolus Agent" not in labels
    assert "SOP Class UID" not in labels


def test_harmonize_dicom_table_us_planar_fields() -> None:
    from pydicom.dataset import Dataset

    from anonymizer.controller.ai.harmonize.playbook import harmonize_dicom_rows

    ds = Dataset()
    ds.Modality = "US"
    ds.StudyDescription = "USS ABDOMEN"
    rows = harmonize_dicom_rows(ds)
    labels = [row[0] for row in rows]
    assert "Study Description" in labels
    assert "View Position" in labels
    assert "Slice Thickness" not in labels
    assert "View Code Sequence" not in labels


def test_series_description_is_harmonized_when_cache_matches() -> None:
    from pydicom import Dataset

    from anonymizer.controller.ai.harmonize import series_description_is_harmonized

    ds = Dataset()
    ds.SeriesDescription = "Ch Ax PortVen"

    with patch(
        "anonymizer.controller.ai.harmonize.pipeline.harmonized_description_from_cache",
        return_value="Ch Ax PortVen",
    ):
        assert series_description_is_harmonized(Path("/tmp/series"), ds) is True


def test_series_description_is_harmonized_unknown_without_cache() -> None:
    from pydicom import Dataset

    from anonymizer.controller.ai.harmonize import series_description_is_harmonized

    ds = Dataset()
    ds.SeriesDescription = "Legacy Description"

    with patch(
        "anonymizer.controller.ai.harmonize.pipeline.harmonized_description_from_cache",
        return_value=None,
    ):
        assert series_description_is_harmonized(Path("/tmp/series"), ds) is None


def test_harmonize_context_hint_when_already_harmonized() -> None:
    from pydicom import Dataset

    from anonymizer.controller.ai.harmonize import harmonize_context_hint

    ds = Dataset()
    ds.Modality = "CT"
    ds.SeriesDescription = "Ch Ax PortVen"

    with patch(
        "anonymizer.controller.ai.harmonize.pipeline.series_description_is_harmonized",
        return_value=True,
    ):
        hint = harmonize_context_hint(Path("/tmp/series"), ds)

    assert hint is not None
    assert "Clear" in hint
    assert "Clear Cache" not in hint


def test_harmonize_context_hint_omits_non_ct_and_unknown() -> None:
    from pydicom import Dataset

    from anonymizer.controller.ai.harmonize import harmonize_context_hint

    mr = Dataset()
    mr.Modality = "MR"
    assert harmonize_context_hint(Path("/tmp/series"), mr) is None

    ct = Dataset()
    ct.Modality = "CT"
    with patch(
        "anonymizer.controller.ai.harmonize.pipeline.series_description_is_harmonized",
        return_value=None,
    ):
        assert harmonize_context_hint(Path("/tmp/series"), ct) is None
