"""Tests for analyze_series entry point (mocked TotalSegmentator)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.ai.tseg.contrast import ContrastResult
from anonymizer.controller.ai.tseg.segment import TS_result, analyze_series
from tests.controller.tseg.support.stub_seg_masks import write_stub_overlay_masks

pytestmark = pytest.mark.usefixtures("synthetic_ct_asset_dirs")


@pytest.fixture
def mock_contrast_result() -> ContrastResult:
    return ContrastResult(
        phase="native",
        pi_time=5.0,
        probability=0.95,
        iv_contrast=False,
    )


def test_analyze_series_empty_input() -> None:
    assert analyze_series([]) == []


@patch("anonymizer.controller.ai.tseg.segment.analyze_contrast_phase")
@patch("anonymizer.controller.ai.tseg.segment.run_segmentation")
@patch("anonymizer.controller.ai.tseg.segment.dicom_series_to_nifti")
@patch("anonymizer.controller.ai.tseg.segment.collect_structure_voxels")
def test_analyze_series_chest_mocked(
    mock_collect: MagicMock,
    mock_nifti: MagicMock,
    mock_seg: MagicMock,
    mock_contrast: MagicMock,
    mock_contrast_result: ContrastResult,
    synthetic_chest_series: Path,
) -> None:
    voxels = {
        "lung_upper_lobe_left": 50_000,
        "lung_upper_lobe_right": 48_000,
        "heart": 10_000,
    }
    write_stub_overlay_masks(synthetic_chest_series, voxels)
    mock_nifti.return_value = 24
    mock_seg.return_value = 1.0
    mock_collect.return_value = voxels
    mock_contrast.return_value = mock_contrast_result

    results = analyze_series([synthetic_chest_series])
    assert len(results) == 1
    result = results[0]
    assert isinstance(result, TS_result)
    assert result.error is None
    assert result.dominant_region == "Chest"
    assert result.body_parts_present == "Chest"
    mock_nifti.assert_called_once()


@patch("anonymizer.controller.ai.tseg.segment.analyze_contrast_phase")
@patch("anonymizer.controller.ai.tseg.segment.run_segmentation")
@patch("anonymizer.controller.ai.tseg.segment.dicom_series_to_nifti")
@patch("anonymizer.controller.ai.tseg.segment.collect_structure_voxels")
def test_analyze_series_no_regions_returns_error(
    mock_collect: MagicMock,
    mock_nifti: MagicMock,
    mock_seg: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_nifti.return_value = 24
    mock_seg.return_value = 1.0
    mock_collect.return_value = {"brain": 0, "liver": 0}
    mock_contrast.return_value = ContrastResult("native", 0.0, 0.0, False)

    results = analyze_series([synthetic_chest_series])
    assert len(results) == 1
    assert results[0].error is not None
    assert "No anatomy regions" in results[0].error
