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
    build_geometry_routing_summary,
    empty_geometry_fields,
    evaluate_record,
    geometry_fields,
    geometry_group_stats,
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


def test_geometry_group_stats_fail_rate_by_plane() -> None:
    rows = [
        {
            "status": "ok",
            "geometry_plane": "axial",
            "geometry_ts_suitable": True,
            "body_part_correct": True,
            "body_part_dominant_match": True,
            "iv_contrast_correct": True,
        },
        {
            "status": "fail",
            "geometry_plane": "oblique",
            "geometry_ts_suitable": False,
            "body_part_correct": False,
            "body_part_dominant_match": False,
            "iv_contrast_correct": "",
        },
        {
            "status": "fail",
            "geometry_plane": "oblique",
            "geometry_ts_suitable": False,
            "body_part_correct": False,
            "body_part_dominant_match": False,
            "iv_contrast_correct": "",
        },
        {
            "status": "fail",
            "geometry_plane": "axial",
            "geometry_dimensionality": "localizer_2d",
            "geometry_ts_suitable": False,
            "body_part_correct": False,
            "body_part_dominant_match": False,
            "iv_contrast_correct": "",
        },
    ]
    by_plane = geometry_group_stats(rows, "geometry_plane")
    assert by_plane["axial"]["n"] == 2
    assert by_plane["axial"]["n_ok"] == 1
    assert by_plane["axial"]["fail_rate"] == 0.5
    assert by_plane["oblique"]["fail_rate"] == 1.0
    assert by_plane["oblique"]["n_ts_not_suitable"] == 2

    by_dim = geometry_group_stats(rows, "geometry_dimensionality")
    assert by_dim["localizer_2d"]["fail_rate"] == 1.0


def test_build_geometry_routing_summary() -> None:
    rows = [
        {
            "status": "ok",
            "geometry_ts_suitable": True,
            "body_part_correct": True,
            "body_part_dominant_match": True,
            "iv_contrast_correct": True,
        },
        {
            "status": "fail",
            "geometry_ts_suitable": False,
            "body_part_correct": False,
            "body_part_dominant_match": False,
            "iv_contrast_correct": "",
        },
    ]
    routing = build_geometry_routing_summary(rows)
    assert routing["ts_suitable"]["n"] == 1
    assert routing["ts_suitable"]["n_ok"] == 1
    assert routing["ts_suitable"]["fail_rate"] == 0.0
    assert routing["ts_not_suitable"]["n"] == 1
    assert routing["ts_not_suitable"]["fail_rate"] == 1.0
