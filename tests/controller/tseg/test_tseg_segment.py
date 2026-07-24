"""Tests for TotalSegmentator structure → region aggregation and device resolution."""

from __future__ import annotations

from unittest.mock import patch

from anonymizer.controller.tseg.segment import (
    _segmentation_cache_valid,
    body_parts_present,
    dominant_region_from_voxels,
    is_multi_region,
    resolve_device,
    series_cache_dir,
)


def test_chest_from_lungs() -> None:
    result = dominant_region_from_voxels(
        {
            "lung_upper_lobe_left": 50_000,
            "lung_upper_lobe_right": 48_000,
            "heart": 10_000,
        },
        min_voxels=1000,
    )
    assert result.dominant_region == "Chest"
    assert result.region_fraction > 0.5


def test_head_from_brain() -> None:
    result = dominant_region_from_voxels({"brain": 80_000, "skull": 20_000}, min_voxels=1000)
    assert result.dominant_region == "Head"


def test_abdomen_from_liver() -> None:
    result = dominant_region_from_voxels({"liver": 60_000, "spleen": 15_000}, min_voxels=1000)
    assert result.dominant_region == "Abdomen"


def test_empty_masks() -> None:
    result = dominant_region_from_voxels({"brain": 0, "liver": 10}, min_voxels=1000)
    assert result.dominant_region == ""
    assert result.region_fraction == 0.0


def test_body_parts_present_single() -> None:
    label = body_parts_present({"Head": 80_000, "Chest": 5_000, "Abdomen": 1_000})
    assert label == "Head"
    assert not is_multi_region(label)


def test_body_parts_present_multi() -> None:
    label = body_parts_present({"Head": 5_000, "Chest": 50_000, "Abdomen": 45_000})
    assert label == "Chest+Abdomen"
    assert is_multi_region(label)


def test_resolve_device_explicit() -> None:
    assert resolve_device("cpu") == "cpu"
    assert resolve_device("mps") == "mps"
    assert resolve_device("gpu") == "gpu"
    assert resolve_device("gpu:1") == "gpu:1"


@patch("torch.backends.mps.is_available", return_value=True)
@patch("torch.cuda.is_available", return_value=False)
def test_resolve_device_auto_mps(_cuda: object, _mps: object) -> None:
    assert resolve_device(None) == "mps"


@patch("torch.backends.mps.is_available", return_value=False)
@patch("torch.cuda.is_available", return_value=True)
def test_resolve_device_auto_gpu(_cuda: object, _mps: object) -> None:
    assert resolve_device(None) == "gpu"


@patch("torch.backends.mps.is_available", return_value=False)
@patch("torch.cuda.is_available", return_value=False)
def test_resolve_device_auto_cpu(_cuda: object, _mps: object) -> None:
    assert resolve_device(None) == "cpu"


def test_series_cache_dir_under_series(tmp_path) -> None:
    series = tmp_path / "1.2.3"
    series.mkdir()
    assert series_cache_dir(series) == series / "A_TS_SEG"


def test_segmentation_cache_valid_requires_mask(tmp_path) -> None:
    seg_dir = tmp_path / "seg"
    seg_dir.mkdir()
    assert not _segmentation_cache_valid(seg_dir, ["brain", "liver"])
    (seg_dir / "brain.nii.gz").write_bytes(b"x")
    assert _segmentation_cache_valid(seg_dir, ["brain", "liver"])
