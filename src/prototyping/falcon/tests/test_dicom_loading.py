"""Tests for FALCON DICOM loading aligned with TotalSegmentator stack ordering."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from prototyping.falcon.preprocessing.dicom_loading import MIN_DICOM_SLICES, get_sitk_from_dicom
from prototyping.falcon.preprocessing.preprocess_series import preprocess_series
from tests.controller.tseg.support.synthetic_ct import build_synthetic_oriented_ct_series

# Slightly oblique axial IOP (similar to real head CT with ~7° tilt).
_OBLIQUE_AXIAL_IOP = [1.0, 0.0, 0.0, 0.0, 0.992546152, 0.121869343]


def _stack_delta_along_normal(spacing_mm: float, image_orientation: list[float]) -> list[float]:
    row = image_orientation[:3]
    column = image_orientation[3:]
    normal = (
        row[1] * column[2] - row[2] * column[1],
        row[2] * column[0] - row[0] * column[2],
        row[0] * column[1] - row[1] * column[0],
    )
    magnitude = math.sqrt(sum(component * component for component in normal))
    return [spacing_mm * component / magnitude for component in normal]


def test_get_sitk_from_dicom_oblique_axial_stack(tmp_path: Path) -> None:
    series_dir = build_synthetic_oriented_ct_series(
        tmp_path / "oblique_head",
        num_slices=MIN_DICOM_SLICES + 5,
        image_orientation=_OBLIQUE_AXIAL_IOP,
        stack_delta=_stack_delta_along_normal(5.0, _OBLIQUE_AXIAL_IOP),
        body_part_examined="HEAD",
        series_description="Synthetic oblique axial head CT",
    )

    image = get_sitk_from_dicom(series_dir)
    try:
        assert image.GetSize()[2] == MIN_DICOM_SLICES + 5
        assert all(spacing > 0 for spacing in image.GetSpacing())
    finally:
        del image


def test_preprocess_series_oblique_axial_stack(tmp_path: Path) -> None:
    series_dir = build_synthetic_oriented_ct_series(
        tmp_path / "oblique_head_preprocess",
        num_slices=MIN_DICOM_SLICES + 5,
        image_orientation=_OBLIQUE_AXIAL_IOP,
        stack_delta=_stack_delta_along_normal(5.0, _OBLIQUE_AXIAL_IOP),
        body_part_examined="HEAD",
        series_description="Synthetic oblique axial head CT",
    )

    volume = preprocess_series(series_dir)
    assert volume.shape == (100, 150, 150)


def test_get_sitk_from_dicom_rejects_too_few_slices(tmp_path: Path) -> None:
    series_dir = build_synthetic_oriented_ct_series(
        tmp_path / "too_few",
        num_slices=MIN_DICOM_SLICES - 1,
        image_orientation=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        stack_delta=[0.0, 0.0, 5.0],
        require_min_volume_slices=False,
    )

    with pytest.raises(ValueError, match=f"Found only {MIN_DICOM_SLICES - 1} slices"):
        get_sitk_from_dicom(series_dir)
