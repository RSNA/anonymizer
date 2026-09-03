"""Tests for CT Harmonize single-pass helpers and stage timings."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from anonymizer.controller.ai.harmonize.timings import HarmonizeStageTimings
from anonymizer.controller.ai.tseg.contrast import structure_voxels_from_organ_stats
from anonymizer.controller.ai.tseg.segment import (
    NO_ANATOMY_REGIONS_ERROR,
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
