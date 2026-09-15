"""Tests for CT Harmonize single-pass helpers and stage timings."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.ai.harmonize import harmonize_series
from anonymizer.controller.ai.harmonize.timings import HarmonizeStageTimings
from anonymizer.controller.ai.tseg.config import TSEG_CACHE_DIRNAME
from anonymizer.controller.ai.tseg.contrast import structure_voxels_from_organ_stats
from anonymizer.controller.ai.tseg.segment import (
    NO_ANATOMY_REGIONS_ERROR,
    TS_result,
    _ts_result_from_structure_voxels,
    analyze_tseg_ct_single_pass,
)


def test_structure_voxels_from_organ_stats_maps_known_structures() -> None:
    stats = {
        "brain": {"volume": 120000.0, "intensity": 40.0},
        "heart": {"volume": 50000.0, "intensity": 120.0},
        "liver": {"volume": 80000.0, "intensity": 90.0},
        "unknown_organ": {"volume": 999.0, "intensity": 1.0},
    }
    counts = structure_voxels_from_organ_stats(stats)
    assert counts["brain"] == 120000
    assert counts["heart"] == 50000
    assert counts["liver"] == 80000
    assert "unknown_organ" not in counts


def test_ts_result_from_structure_voxels_head_dominant() -> None:
    result = _ts_result_from_structure_voxels(
        Path("/tmp/series"),
        {"brain": 200000, "skull": 50000, "heart": 0, "liver": 0},
    )
    assert result.error is None
    assert "Head" in result.body_parts_present
    assert result.dominant_region == "Head"


def test_ts_result_from_structure_voxels_empty() -> None:
    result = _ts_result_from_structure_voxels(Path("/tmp/series"), {})
    assert result.error == NO_ANATOMY_REGIONS_ERROR


def test_analyze_tseg_ct_single_pass_rejects_non_ct(tmp_path: Path) -> None:
    with patch(
        "anonymizer.controller.ai.tseg.modality_profile.resolve_profile_for_series",
        return_value=None,
    ):
        result, nifti, used = analyze_tseg_ct_single_pass(tmp_path)
    assert used is False
    assert nifti is None
    assert result.error == "CT single-pass not applicable"


def test_harmonize_stage_timings_as_log_dict() -> None:
    timing = HarmonizeStageTimings(
        series_directory="/tmp/s",
        anatomy_sec=10.0,
        contrast_sec=2.0,
        total_sec=13.0,
        single_pass=True,
        body_parts_present="Head",
    )
    payload = timing.as_log_dict()
    assert payload["single_pass"] is True
    assert payload["anatomy_sec"] == 10.0


@pytest.mark.usefixtures("synthetic_ct_asset_dirs")
@patch("anonymizer.controller.ai.harmonize.pipeline.ENABLE_TS_CONTRAST", True)
@patch("anonymizer.controller.ai.tseg.config.ENABLE_CT_HARMONIZE_SINGLE_PASS", True)
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_ct_single_pass")
def test_harmonize_prefers_ct_single_pass_when_enabled(
    mock_single_pass: MagicMock,
    mock_regions: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    region = TS_result(
        series_directory=synthetic_chest_series,
        dominant_region="Chest",
        body_parts_present="Chest",
        multi_region=False,
        region_fraction=0.9,
        iv_contrast=False,
        contrast_phase="",
        phase_probability=0.0,
    )
    nifti = synthetic_chest_series / "volume.nii.gz"
    mock_single_pass.return_value = (region, nifti, True)
    mock_contrast.return_value = TS_result(
        series_directory=synthetic_chest_series,
        dominant_region="Chest",
        body_parts_present="Chest",
        multi_region=False,
        region_fraction=0.9,
        iv_contrast=True,
        contrast_phase="portal_venous",
        phase_probability=0.88,
    )

    results = harmonize_series([synthetic_chest_series])
    merged = results[0]

    assert merged.error is None
    assert merged.radlex_series_description == "Ch Ax PortVen"
    mock_single_pass.assert_called_once()
    mock_regions.assert_not_called()
    mock_contrast.assert_called_once()


def _ct_head_geometry() -> SeriesGeometryResult:
    from anonymizer.controller.ai.tseg.dicom_geometry import SeriesGeometryResult

    return SeriesGeometryResult(
        plane="axial",
        plane_confidence=0.95,
        slice_normal_lps=(0.0, 0.0, 1.0),
        plane_angles_deg={"axial": 5.0, "coronal": 85.0, "sagittal": 85.0},
        dimensionality="volume_3d",
        n_slices=34,
        through_plane_extent_mm=170.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=True,
        metadata_suspect=False,
        method="test",
        notes="",
    )


def _anatomy_only_series(tmp_path: Path) -> Path:
    series = tmp_path / "series"
    cache = series / TSEG_CACHE_DIRNAME
    seg = cache / "seg"
    cache.mkdir(parents=True)
    seg.mkdir()
    (cache / "volume.nii.gz").write_bytes(b"vol")
    (cache / "contrast_stats.json").write_text("{}")
    (seg / "brain.nii.gz").write_bytes(b"m")
    return series


@patch("anonymizer.controller.ai.tseg.segment.finalize_seg_cache", side_effect=lambda cache, seg, voxels: voxels)
@patch("anonymizer.controller.ai.tseg.segment.collect_structure_voxels_from_masks", return_value={"cerebellum": 4000})
@patch("anonymizer.controller.ai.tseg.readiness.verify_face_license", return_value=(True, ""))
@patch("anonymizer.controller.ai.tseg.segment.run_brain_structures_segmentation", return_value=1.0)
@patch("anonymizer.controller.ai.tseg.segment._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.segment._nifti_slice_count", return_value=34)
@patch("anonymizer.controller.ai.tseg.segment.invalidate_stale_tseg_volume_cache")
@patch("anonymizer.controller.ai.tseg.segment.anatomy_overlay_cache_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.tseg.segment.read_structure_voxels",
    return_value={"brain": 200_000, "skull": 50_000},
)
@patch("anonymizer.controller.ai.tseg.segment.load_contrast_statistics", return_value={"brain": {"volume": 200000}})
@patch("anonymizer.controller.ai.tseg.segment.ts_regions_eligible", return_value=True)
@patch("anonymizer.controller.ai.tseg.segment.resolve_series_geometry")
@patch("anonymizer.controller.ai.tseg.modality_profile.resolve_profile_for_series")
def test_single_pass_reuses_anatomy_when_only_brain_missing(
    mock_profile: MagicMock,
    mock_geometry: MagicMock,
    _eligible: MagicMock,
    _stats: MagicMock,
    _voxels: MagicMock,
    _overlay: MagicMock,
    _invalidate: MagicMock,
    _slices: MagicMock,
    mock_totalseg: MagicMock,
    mock_brain: MagicMock,
    _license: MagicMock,
    _brain_counts: MagicMock,
    _finalize: MagicMock,
    tmp_path: Path,
) -> None:
    from anonymizer.controller.ai.tseg.modality_profile import ct_modality_profile

    mock_profile.return_value = ct_modality_profile()
    mock_geometry.return_value = _ct_head_geometry()
    series = _anatomy_only_series(tmp_path)

    result, nifti, used = analyze_tseg_ct_single_pass(series, include_brain_structures=True)

    assert used is True
    assert result.error is None
    assert nifti is not None
    mock_totalseg.assert_not_called()
    mock_brain.assert_called_once()


@patch("anonymizer.controller.ai.tseg.segment.run_brain_structures_segmentation")
@patch("anonymizer.controller.ai.tseg.segment._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.segment._nifti_slice_count", return_value=34)
@patch("anonymizer.controller.ai.tseg.segment.invalidate_stale_tseg_volume_cache")
@patch("anonymizer.controller.ai.tseg.segment._brain_structures_cache_valid", return_value=True)
@patch("anonymizer.controller.ai.tseg.segment.anatomy_overlay_cache_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.tseg.segment.read_structure_voxels",
    return_value={"brain": 200_000, "skull": 50_000, "cerebellum": 4000},
)
@patch("anonymizer.controller.ai.tseg.segment.load_contrast_statistics", return_value={"brain": {"volume": 200000}})
@patch("anonymizer.controller.ai.tseg.segment.ts_regions_eligible", return_value=True)
@patch("anonymizer.controller.ai.tseg.segment.resolve_series_geometry")
@patch("anonymizer.controller.ai.tseg.modality_profile.resolve_profile_for_series")
def test_single_pass_reuses_full_cache_including_brain(
    mock_profile: MagicMock,
    mock_geometry: MagicMock,
    _eligible: MagicMock,
    _stats: MagicMock,
    _voxels: MagicMock,
    _overlay: MagicMock,
    _brain_valid: MagicMock,
    _invalidate: MagicMock,
    _slices: MagicMock,
    mock_totalseg: MagicMock,
    mock_brain: MagicMock,
    tmp_path: Path,
) -> None:
    from anonymizer.controller.ai.tseg.modality_profile import ct_modality_profile

    mock_profile.return_value = ct_modality_profile()
    mock_geometry.return_value = _ct_head_geometry()
    series = _anatomy_only_series(tmp_path)

    result, _nifti, used = analyze_tseg_ct_single_pass(series, include_brain_structures=True)

    assert used is True
    assert result.error is None
    mock_totalseg.assert_not_called()
    mock_brain.assert_not_called()

