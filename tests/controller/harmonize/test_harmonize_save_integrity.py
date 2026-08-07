"""Verify harmonize description save paths do not alter DICOM pixel data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pydicom import dcmread

from anonymizer.controller.harmonize import apply_harmonized_description
from anonymizer.controller.series_io import (
    apply_series_description,
    load_series,
    save_series_slices,
)
from tests.controller.tseg.support.synthetic_ct import build_synthetic_chest_ct_series


def _snapshot_series_pixel_arrays(series_dir: Path) -> dict[str, np.ndarray]:
    return {dcm_path.name: dcmread(dcm_path).pixel_array.copy() for dcm_path in sorted(series_dir.glob("*.dcm"))}


def _assert_series_pixels_unchanged(
    before: dict[str, np.ndarray],
    series_dir: Path,
) -> None:
    assert before, "expected at least one DICOM slice"
    for dcm_path in sorted(series_dir.glob("*.dcm")):
        after_pixels = dcmread(dcm_path).pixel_array
        before_pixels = before[dcm_path.name]
        assert after_pixels.shape == before_pixels.shape, dcm_path.name
        assert np.array_equal(after_pixels, before_pixels), dcm_path.name


def test_apply_harmonized_description_preserves_all_slice_pixels(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    before = _snapshot_series_pixel_arrays(series_dir)

    assert apply_harmonized_description(series_dir, "Brain Ax EarlyArt", None) is True

    for dcm_path in sorted(series_dir.glob("*.dcm")):
        assert dcmread(dcm_path).SeriesDescription == "Brain Ax EarlyArt"

    _assert_series_pixels_unchanged(before, series_dir)


def test_harmonize_save_then_save_pixel_changes_without_edits_preserves_pixels(
    tmp_path: Path,
) -> None:
    """Mirrors opening a harmonized series and clicking Save Pixel Changes with no edits."""
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    before = _snapshot_series_pixel_arrays(series_dir)

    assert apply_series_description(series_dir, "Chest Ax Portal Venous") is True

    loaded = load_series(series_dir)

    reference_ds, frames, _loaded_paths = loaded.metadata, loaded.slices, loaded.slice_paths
    assert save_series_slices(series_dir, frames, reference_ds) is True

    _assert_series_pixels_unchanged(before, series_dir)
