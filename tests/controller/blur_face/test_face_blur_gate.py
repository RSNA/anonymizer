"""Unit tests for CT head eligibility gate (blur_face)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
import pytest
import SimpleITK as sitk
from pydicom.data import get_testdata_file

from anonymizer.controller.blur_face import (
    MIN_FACE_MASK_VOXELS,
    CachedRegionSignal,
    FaceBlurEligibility,
    FaceBlurGateDecision,
    FaceBlurGateReason,
    MetadataSignal,
    cached_region_signal,
    evaluate_face_blur_eligibility,
    face_blur_context_hint,
    face_blur_gate_message,
    face_blur_status_applicable,
    face_mask_is_substantial,
    metadata_signal,
)
from anonymizer.controller.tseg.config import MIN_STRUCTURE_VOXELS
from anonymizer.controller.tseg.dicom_geometry import SeriesGeometryResult, resolve_series_geometry
from anonymizer.controller.tseg.segment import series_cache_dir
from tests.controller.tseg.support.synthetic_ct import (
    build_synthetic_chest_ct_series,
    build_synthetic_head_ct_series,
)


def _geometry(*, ts_suitable: bool = True) -> SeriesGeometryResult:
    return SeriesGeometryResult(
        plane="axial",
        plane_confidence=0.95,
        slice_normal_lps=(0.0, 0.0, 1.0),
        plane_angles_deg={"axial": 5.0, "coronal": 85.0, "sagittal": 85.0},
        dimensionality="volume_3d",
        n_slices=24,
        through_plane_extent_mm=120.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=ts_suitable,
        metadata_suspect=False,
        method="dicom_headers",
        notes="" if ts_suitable else "Not a diagnostic 3D volume (localizer_2d)",
    )


def _dataset(**tags: str) -> pydicom.Dataset:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    for key, value in tags.items():
        setattr(ds, key, value)
    return ds


def _write_structure_mask(seg_dir: Path, name: str, voxel_count: int) -> None:
    seg_dir.mkdir(parents=True, exist_ok=True)
    array = np.zeros((24, 64, 64), dtype=np.uint8)
    flat = array.ravel()
    count = min(voxel_count, flat.size)
    flat[:count] = 1
    array = flat.reshape(array.shape)
    sitk.WriteImage(sitk.GetImageFromArray(array), str(seg_dir / f"{name}.nii.gz"))


def _write_head_region_cache(series_dir: Path) -> None:
    seg_dir = series_cache_dir(series_dir) / "seg"
    _write_structure_mask(seg_dir, "brain", 8000)


def _write_chest_region_cache(series_dir: Path) -> None:
    seg_dir = series_cache_dir(series_dir) / "seg"
    _write_structure_mask(seg_dir, "heart", 6000)
    _write_structure_mask(seg_dir, "lung_upper_lobe_left", 5000)
    _write_structure_mask(seg_dir, "lung_upper_lobe_right", 5000)


def _write_multi_region_cache(series_dir: Path) -> None:
    seg_dir = series_cache_dir(series_dir) / "seg"
    _write_structure_mask(seg_dir, "brain", 4000)
    _write_structure_mask(seg_dir, "heart", 4000)
    _write_structure_mask(seg_dir, "lung_upper_lobe_left", 4000)


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"BodyPartExamined": "HEAD", "SeriesDescription": "Routine head CT"}, MetadataSignal.HEAD),
        ({"BodyPartExamined": "CHEST", "SeriesDescription": "CT thorax"}, MetadataSignal.NON_HEAD),
        (
            {"BodyPartExamined": "HEAD", "SeriesDescription": "CT chest abdomen pelvis"},
            MetadataSignal.AMBIGUOUS,
        ),
        ({}, MetadataSignal.AMBIGUOUS),
    ],
)
def test_metadata_signal(tags: dict[str, str], expected: MetadataSignal) -> None:
    assert metadata_signal(_dataset(**tags)) == expected


def test_cached_region_signal_unavailable_without_cache(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "head")
    assert cached_region_signal(series_dir) == CachedRegionSignal.UNAVAILABLE


def test_cached_region_signal_head(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "head")
    _write_head_region_cache(series_dir)
    assert cached_region_signal(series_dir) == CachedRegionSignal.HEAD


def test_cached_region_signal_non_head(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    _write_chest_region_cache(series_dir)
    assert cached_region_signal(series_dir) == CachedRegionSignal.NON_HEAD


def test_cached_region_signal_multi_region(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "multi")
    _write_multi_region_cache(series_dir)
    assert cached_region_signal(series_dir) == CachedRegionSignal.MULTI_REGION


def test_evaluate_blocks_non_ct(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "head")
    ds = pydicom.dcmread(next(series_dir.glob("*.dcm")))
    ds.Modality = "MR"
    result = evaluate_face_blur_eligibility(series_dir, ds=ds, geometry=_geometry())
    assert result.decision == FaceBlurGateDecision.BLOCK
    assert result.reason == FaceBlurGateReason.MODALITY


def test_evaluate_blocks_when_feature_disabled(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "head")
    ds = pydicom.dcmread(next(series_dir.glob("*.dcm")))
    result = evaluate_face_blur_eligibility(
        series_dir,
        ds=ds,
        geometry=_geometry(),
        enable_tseg_face=False,
    )
    assert result.decision == FaceBlurGateDecision.BLOCK
    assert result.reason == FaceBlurGateReason.FEATURE_DISABLED


def test_evaluate_blocks_when_not_ts_suitable(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "head")
    ds = pydicom.dcmread(next(series_dir.glob("*.dcm")))
    result = evaluate_face_blur_eligibility(series_dir, ds=ds, geometry=_geometry(ts_suitable=False))
    assert result.decision == FaceBlurGateDecision.BLOCK
    assert result.reason == FaceBlurGateReason.GEOMETRY


def test_evaluate_allows_cached_head_over_chest_metadata(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    _write_head_region_cache(series_dir)
    ds = pydicom.dcmread(next(series_dir.glob("*.dcm")))
    result = evaluate_face_blur_eligibility(series_dir, ds=ds, geometry=_geometry())
    assert result.decision == FaceBlurGateDecision.ALLOW
    assert result.reason == FaceBlurGateReason.CACHED_REGIONS_HEAD


def test_evaluate_blocks_cached_non_head(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "head")
    _write_chest_region_cache(series_dir)
    ds = pydicom.dcmread(next(series_dir.glob("*.dcm")))
    result = evaluate_face_blur_eligibility(series_dir, ds=ds, geometry=_geometry())
    assert result.decision == FaceBlurGateDecision.BLOCK
    assert result.reason == FaceBlurGateReason.CACHED_REGIONS_NON_HEAD


def test_evaluate_confirms_cached_multi_region(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "multi")
    _write_multi_region_cache(series_dir)
    ds = pydicom.dcmread(next(series_dir.glob("*.dcm")))
    result = evaluate_face_blur_eligibility(series_dir, ds=ds, geometry=_geometry())
    assert result.decision == FaceBlurGateDecision.CONFIRM
    assert result.reason == FaceBlurGateReason.CACHED_REGIONS_MULTI


def test_evaluate_allows_head_metadata_without_cache(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "head")
    ds = pydicom.dcmread(next(series_dir.glob("*.dcm")))
    result = evaluate_face_blur_eligibility(series_dir, ds=ds, geometry=_geometry())
    assert result.decision == FaceBlurGateDecision.ALLOW
    assert result.reason == FaceBlurGateReason.METADATA_HEAD


def test_evaluate_blocks_non_head_metadata_without_cache(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    ds = pydicom.dcmread(next(series_dir.glob("*.dcm")))
    result = evaluate_face_blur_eligibility(series_dir, ds=ds, geometry=_geometry())
    assert result.decision == FaceBlurGateDecision.BLOCK
    assert result.reason == FaceBlurGateReason.METADATA_NON_HEAD


def test_evaluate_confirms_ambiguous_metadata(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "head")
    ds = _dataset(BodyPartExamined="", SeriesDescription="CT survey")
    result = evaluate_face_blur_eligibility(series_dir, ds=ds, geometry=_geometry())
    assert result.decision == FaceBlurGateDecision.CONFIRM
    assert result.reason == FaceBlurGateReason.AMBIGUOUS


def test_evaluate_uses_resolved_geometry_from_series(tmp_path: Path) -> None:
    series_dir = build_synthetic_head_ct_series(tmp_path / "head")
    geometry = resolve_series_geometry(series_dir, use_cache=False, write_cache=True)
    ds = pydicom.dcmread(next(series_dir.glob("*.dcm")))
    result = evaluate_face_blur_eligibility(series_dir, ds=ds, geometry=geometry)
    assert result.decision == FaceBlurGateDecision.ALLOW


def test_face_mask_is_substantial_threshold() -> None:
    assert face_mask_is_substantial(MIN_FACE_MASK_VOXELS)
    assert not face_mask_is_substantial(MIN_FACE_MASK_VOXELS - 1)
    assert MIN_FACE_MASK_VOXELS == MIN_STRUCTURE_VOXELS


def test_evaluate_face_blur_eligibility_already_applied() -> None:
    result = evaluate_face_blur_eligibility(
        Path("/tmp/series"),
        face_blur_already_applied=True,
    )
    assert result.decision == FaceBlurGateDecision.BLOCK
    assert result.reason == FaceBlurGateReason.ALREADY_APPLIED
    assert "already been applied" in face_blur_gate_message(result.reason).lower()


@pytest.mark.parametrize("reason", list(FaceBlurGateReason))
def test_face_blur_gate_message_covers_all_reasons(reason: FaceBlurGateReason) -> None:
    message = face_blur_gate_message(reason)
    assert message
    assert isinstance(message, str)


def test_face_blur_context_hint_skips_geometry_block() -> None:
    geometry = _geometry(ts_suitable=False)
    eligibility = FaceBlurEligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.GEOMETRY)
    assert face_blur_context_hint(eligibility, geometry) is None


def test_face_blur_context_hint_for_non_head_blocks() -> None:
    geometry = _geometry()
    for reason in (
        FaceBlurGateReason.CACHED_REGIONS_NON_HEAD,
        FaceBlurGateReason.METADATA_NON_HEAD,
    ):
        eligibility = FaceBlurEligibility(FaceBlurGateDecision.BLOCK, reason)
        assert face_blur_context_hint(eligibility, geometry) == face_blur_gate_message(reason)


def test_face_blur_context_hint_omits_modality_without_geometry() -> None:
    eligibility = FaceBlurEligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.MODALITY)
    assert face_blur_context_hint(eligibility, None) is None


@pytest.mark.parametrize(
    ("decision", "reason", "already_applied", "expected"),
    [
        (FaceBlurGateDecision.ALLOW, FaceBlurGateReason.CACHED_REGIONS_HEAD, False, True),
        (FaceBlurGateDecision.CONFIRM, FaceBlurGateReason.AMBIGUOUS, False, True),
        (FaceBlurGateDecision.CONFIRM, FaceBlurGateReason.CACHED_REGIONS_MULTI, False, True),
        (FaceBlurGateDecision.BLOCK, FaceBlurGateReason.CACHED_REGIONS_NON_HEAD, False, False),
        (FaceBlurGateDecision.BLOCK, FaceBlurGateReason.METADATA_NON_HEAD, False, False),
        (FaceBlurGateDecision.BLOCK, FaceBlurGateReason.MODALITY, False, False),
        (FaceBlurGateDecision.BLOCK, FaceBlurGateReason.GEOMETRY, False, False),
        (FaceBlurGateDecision.BLOCK, FaceBlurGateReason.CACHED_REGIONS_NON_HEAD, True, True),
    ],
)
def test_face_blur_status_applicable(
    decision: FaceBlurGateDecision,
    reason: FaceBlurGateReason,
    already_applied: bool,
    expected: bool,
) -> None:
    eligibility = FaceBlurEligibility(decision, reason)
    assert face_blur_status_applicable(eligibility, already_applied=already_applied) is expected
