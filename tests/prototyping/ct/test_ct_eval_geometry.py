"""Unit tests for ct_eval geometry columns."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.tseg.dicom_geometry import SeriesGeometryResult
from anonymizer.controller.tseg.segment import TS_result
from prototyping.ct.ct_eval import (
    GEOMETRY_COLUMNS,
    RESULT_COLUMNS,
    SeriesRecord,
    empty_geometry_fields,
    evaluate_record,
    geometry_fields,
)


def _sample_geometry() -> SeriesGeometryResult:
    return SeriesGeometryResult(
        plane="axial",
        plane_confidence=0.9512,
        slice_normal_lps=(0.0, 0.0, 1.0),
        plane_angles_deg={"axial": 4.0, "coronal": 86.0, "sagittal": 86.0},
        dimensionality="volume_3d",
        n_slices=24,
        through_plane_extent_mm=115.0,
        slice_spacing_mm=5.0,
        spacing_regularity=0.99,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=True,
        metadata_suspect=False,
        method="dicom_headers",
        notes="",
    )


pytestmark = pytest.mark.prototyping


def test_geometry_columns_are_in_result_columns() -> None:
    assert all(column in RESULT_COLUMNS for column in GEOMETRY_COLUMNS)


def test_geometry_fields_flattens_series_geometry_result() -> None:
    row = geometry_fields(_sample_geometry())
    assert row == {
        "geometry_plane": "axial",
        "geometry_plane_confidence": 0.9512,
        "geometry_dimensionality": "volume_3d",
        "geometry_provenance": "original",
        "geometry_n_slices": 24,
        "geometry_ts_suitable": True,
        "geometry_metadata_suspect": False,
        "geometry_method": "dicom_headers",
    }


def test_empty_geometry_fields() -> None:
    assert set(empty_geometry_fields()) == set(GEOMETRY_COLUMNS)
    assert all(value == "" for value in empty_geometry_fields().values())


def test_evaluate_record_includes_geometry_columns() -> None:
    record = SeriesRecord(
        series_path=Path("/tmp/study/series"),
        label_dir="CHEST_WITH",
        body_part_gt="Chest",
        iv_contrast_gt=True,
    )
    tseg = TS_result(
        series_directory=record.series_path,
        dominant_region="Chest",
        body_parts_present="Chest",
        multi_region=False,
        region_fraction=0.82,
        iv_contrast=True,
        contrast_phase="portal_venous",
        phase_probability=0.99,
        radlex_series_description="CT Chest With Contrast",
    )
    row = evaluate_record(
        record,
        tseg,
        series_index=1,
        elapsed_sec=1.5,
        geometry=_sample_geometry(),
    )
    assert row["geometry_plane"] == "axial"
    assert row["geometry_dimensionality"] == "volume_3d"
    assert row["geometry_ts_suitable"] is True
    assert row["body_part_correct"] is True
