"""Unit tests for DICOM series geometry (synthetic DICOM, no mocking)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pydicom
import pytest

from anonymizer.controller.tseg.config import MIN_DICOM_SLICES
from anonymizer.controller.tseg.dicom_geometry import (
    analyze_series_geometry,
    classify_plane,
    compute_stack_metrics,
    geometry_cache_path,
    geometry_from_dict,
    geometry_to_dict,
    headers_in_stack_order,
    infer_dimensionality,
    infer_provenance,
    load_geometry_cache,
    project_ipp_onto_normal,
    read_series_headers,
    resolve_series_geometry,
    slice_normal_from_iop,
    sorted_dicom_paths,
    ts_regions_eligible,
    write_geometry_cache,
)
from anonymizer.controller.tseg.segment import dicom_series_to_nifti
from tests.controller.tseg.support.synthetic_ct import (
    build_synthetic_chest_ct_series,
    build_synthetic_coronal_ct_series,
    build_synthetic_derived_coronal_mpr_series,
    build_synthetic_derived_mip_series,
    build_synthetic_oblique_ct_series,
    build_synthetic_sagittal_ct_series,
    build_synthetic_scout_ct_series,
    build_synthetic_single_slice_ct_series,
)


def test_slice_normal_from_iop_axial() -> None:
    normal = slice_normal_from_iop([1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
    assert normal == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)


def test_slice_normal_from_iop_sagittal() -> None:
    normal = slice_normal_from_iop([0.0, 0.0, 1.0, 0.0, 1.0, 0.0])
    assert abs(normal[0]) == pytest.approx(1.0, abs=1e-6)
    assert normal[1:] == pytest.approx((0.0, 0.0), abs=1e-6)


def test_slice_normal_from_iop_coronal() -> None:
    normal = slice_normal_from_iop([1.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    assert normal == pytest.approx((0.0, -1.0, 0.0), abs=1e-6)


def test_slice_normal_from_iop_rejects_invalid_length() -> None:
    with pytest.raises(ValueError, match="6 values"):
        slice_normal_from_iop([1.0, 0.0, 0.0])


def test_project_ipp_onto_normal() -> None:
    normal = (0.0, 0.0, 1.0)
    assert project_ipp_onto_normal([0.0, 0.0, 10.0], normal) == pytest.approx(10.0)
    assert project_ipp_onto_normal([5.0, -3.0, 10.0], normal) == pytest.approx(10.0)


def test_classify_plane_axial() -> None:
    plane, confidence, angles = classify_plane((0.0, 0.0, 1.0))
    assert plane == "axial"
    assert confidence > 0.99
    assert angles["axial"] == pytest.approx(0.0, abs=1e-6)


def test_classify_plane_sagittal() -> None:
    plane, confidence, _ = classify_plane((1.0, 0.0, 0.0))
    assert plane == "sagittal"
    assert confidence > 0.99


def test_classify_plane_coronal() -> None:
    plane, confidence, _ = classify_plane((0.0, 1.0, 0.0))
    assert plane == "coronal"
    assert confidence > 0.99


def test_classify_plane_oblique() -> None:
    component = 1 / math.sqrt(2)
    plane, _, _ = classify_plane((0.0, component, component))
    assert plane == "oblique"


def test_infer_provenance_original(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "original")
    headers = read_series_headers(series_dir)
    provenance, confidence, image_type, source_uids = infer_provenance(headers)
    assert provenance == "original"
    assert confidence >= 0.9
    assert image_type == ("ORIGINAL", "PRIMARY", "AXIAL")
    assert source_uids == ()


def test_infer_provenance_derived_reformat(tmp_path: Path) -> None:
    series_dir = build_synthetic_derived_coronal_mpr_series(tmp_path / "mpr")
    headers = read_series_headers(series_dir)
    provenance, confidence, image_type, source_uids = infer_provenance(headers)
    assert provenance == "derived_reformat"
    assert confidence >= 0.8
    assert image_type[0] == "DERIVED"
    assert source_uids


def test_infer_provenance_derived_3d_render(tmp_path: Path) -> None:
    series_dir = build_synthetic_derived_mip_series(tmp_path / "mip")
    headers = read_series_headers(series_dir)
    provenance, _, image_type, _ = infer_provenance(headers)
    assert provenance == "derived_3d_render"
    assert image_type is not None
    assert image_type[0] == "DERIVED"


def test_compute_stack_metrics_axial(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    headers = headers_in_stack_order(read_series_headers(series_dir))
    normal = slice_normal_from_iop(headers[0].ImageOrientationPatient)
    stack = compute_stack_metrics(headers, normal)
    assert stack.n_slices >= MIN_DICOM_SLICES
    assert stack.slice_spacing_mm == pytest.approx(5.0, abs=0.1)
    assert stack.through_plane_extent_mm == pytest.approx(5.0 * (stack.n_slices - 1), abs=0.5)
    assert stack.spacing_regularity is not None
    assert stack.spacing_regularity > 0.99


def test_infer_dimensionality_volume(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "volume")
    headers = read_series_headers(series_dir)
    stack = compute_stack_metrics(headers, (0.0, 0.0, 1.0))
    assert infer_dimensionality(headers, stack) == "volume_3d"


def test_infer_dimensionality_localizer(tmp_path: Path) -> None:
    series_dir = build_synthetic_scout_ct_series(tmp_path / "scout")
    headers = read_series_headers(series_dir)
    stack = compute_stack_metrics(headers, (0.0, 0.0, 1.0))
    assert infer_dimensionality(headers, stack) == "localizer_2d"


def test_infer_dimensionality_single_slice(tmp_path: Path) -> None:
    series_dir = build_synthetic_single_slice_ct_series(tmp_path / "single")
    headers = read_series_headers(series_dir)
    stack = compute_stack_metrics(headers, (0.0, 0.0, 1.0))
    assert infer_dimensionality(headers, stack) == "single_slice_2d"


def test_sorted_dicom_paths_sagittal_orders_along_stack(tmp_path: Path) -> None:
    series_dir = build_synthetic_sagittal_ct_series(tmp_path / "sagittal")
    paths = sorted_dicom_paths(series_dir)
    first_header = pydicom.dcmread(paths[0], stop_before_pixels=True)
    normal = slice_normal_from_iop(first_header.ImageOrientationPatient)
    projections = [
        project_ipp_onto_normal(
            pydicom.dcmread(path, stop_before_pixels=True).ImagePositionPatient,
            normal,
        )
        for path in paths
    ]
    assert projections == sorted(projections)


def test_analyze_series_geometry_axial_chest(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.plane == "axial"
    assert geometry.dimensionality == "volume_3d"
    assert geometry.provenance == "original"
    assert geometry.ts_suitable is True
    assert geometry.method == "dicom_iop"


def test_analyze_series_geometry_sagittal(tmp_path: Path) -> None:
    series_dir = build_synthetic_sagittal_ct_series(tmp_path / "sagittal")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.plane == "sagittal"
    assert geometry.dimensionality == "volume_3d"
    assert geometry.ts_suitable is True


def test_analyze_series_geometry_coronal(tmp_path: Path) -> None:
    series_dir = build_synthetic_coronal_ct_series(tmp_path / "coronal")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.plane == "coronal"
    assert geometry.dimensionality == "volume_3d"
    assert geometry.ts_suitable is True


def test_analyze_series_geometry_oblique(tmp_path: Path) -> None:
    series_dir = build_synthetic_oblique_ct_series(tmp_path / "oblique")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.plane == "oblique"
    assert geometry.ts_suitable is True


def test_analyze_series_geometry_scout_not_ts_suitable(tmp_path: Path) -> None:
    series_dir = build_synthetic_scout_ct_series(tmp_path / "scout")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.dimensionality == "localizer_2d"
    assert geometry.ts_suitable is False
    assert ts_regions_eligible(geometry) is False


def test_analyze_series_geometry_mip_not_ts_suitable(tmp_path: Path) -> None:
    series_dir = build_synthetic_derived_mip_series(tmp_path / "mip")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.provenance == "derived_3d_render"
    assert geometry.ts_suitable is False


def test_analyze_series_geometry_derived_mpr_is_ts_suitable(tmp_path: Path) -> None:
    series_dir = build_synthetic_derived_coronal_mpr_series(tmp_path / "mpr")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.provenance == "derived_reformat"
    assert geometry.plane == "coronal"
    assert geometry.ts_suitable is True


def test_geometry_cache_roundtrip(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    geometry = analyze_series_geometry(series_dir)
    cache_path = write_geometry_cache(series_dir, geometry)
    assert cache_path == geometry_cache_path(series_dir)
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    restored = geometry_from_dict(payload)
    assert restored == geometry
    assert geometry_to_dict(restored)["plane"] == "axial"


def test_resolve_series_geometry_uses_cache(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    first = resolve_series_geometry(series_dir)
    cache_path = geometry_cache_path(series_dir)
    assert cache_path.is_file()

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["plane"] = "sagittal"
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    cached = resolve_series_geometry(series_dir, use_cache=True)
    assert cached.plane == "sagittal"
    assert cached == load_geometry_cache(series_dir)

    refreshed = resolve_series_geometry(series_dir, use_cache=False, write_cache=True)
    assert refreshed.plane == "axial"


def test_sagittal_series_converts_to_nifti_with_correct_slice_count(tmp_path: Path) -> None:
    series_dir = build_synthetic_sagittal_ct_series(tmp_path / "sagittal")
    nifti_path = tmp_path / "sagittal.nii.gz"
    n_slices = dicom_series_to_nifti(series_dir, nifti_path)
    assert n_slices >= MIN_DICOM_SLICES
    assert nifti_path.is_file()
