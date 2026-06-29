"""Synthetic CT DICOM integration tests for the tseg module (no TotalSegmentator inference)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import shutil

import nibabel as nib
import pytest
import SimpleITK as sitk
from pydicom import dcmread

from anonymizer.controller.tseg.config import MIN_DICOM_SLICES
from anonymizer.controller.tseg.contrast import ContrastResult
from anonymizer.controller.tseg.segment import (
    TS_result,
    analyze_series,
    dicom_series_to_nifti,
    sorted_dicom_paths,
)
from tests.controller.create_synthetic_ct_series import list_dcm_files
from tests.controller.tseg_fixtures import SYNTHETIC_CT_ASSET_DIRS

pytestmark = pytest.mark.usefixtures("synthetic_ct_asset_dirs")


def test_sorted_dicom_paths_orders_by_image_position(synthetic_chest_series: Path) -> None:
    paths = sorted_dicom_paths(synthetic_chest_series)
    assert len(paths) >= MIN_DICOM_SLICES
    z_positions = [float(dcmread(path, stop_before_pixels=True).ImagePositionPatient[2]) for path in paths]
    assert z_positions == sorted(z_positions)


def test_dicom_series_to_nifti_from_synthetic_chest(synthetic_chest_series: Path, tmp_path: Path) -> None:
    nifti_path = tmp_path / "chest.nii.gz"
    n_slices = dicom_series_to_nifti(synthetic_chest_series, nifti_path)

    assert n_slices == len(list_dcm_files(synthetic_chest_series))
    assert nifti_path.is_file()
    image = sitk.ReadImage(str(nifti_path))
    assert image.GetDimension() == 3
    assert image.GetSize()[2] == n_slices


@pytest.mark.parametrize(
    ("fixture_name", "body_part"),
    [
        ("synthetic_head_series", "HEAD"),
        ("synthetic_chest_series", "CHEST"),
        ("synthetic_abdomen_series", "ABDOMEN"),
    ],
)
def test_synthetic_phantom_dicom_metadata(
    fixture_name: str,
    body_part: str,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    series_dir: Path = request.getfixturevalue(fixture_name)
    nifti_path = tmp_path / f"{body_part.lower()}.nii.gz"
    n_slices = dicom_series_to_nifti(series_dir, nifti_path)
    assert n_slices >= MIN_DICOM_SLICES

    first = dcmread(sorted_dicom_paths(series_dir)[0], stop_before_pixels=True)
    assert first.Modality == "CT"
    assert first.BodyPartExamined == body_part


def test_dicom_series_to_nifti_minimum_slice_count(
    synthetic_chest_series: Path,
    tmp_path: Path,
) -> None:
    min_dir = tmp_path / "min_slices"
    min_dir.mkdir()
    for path in sorted_dicom_paths(synthetic_chest_series)[:MIN_DICOM_SLICES]:
        shutil.copy(path, min_dir / path.name)
    nifti_path = tmp_path / "ok.nii.gz"
    assert dicom_series_to_nifti(min_dir, nifti_path) == MIN_DICOM_SLICES


def test_dicom_series_to_nifti_rejects_empty_directory(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="No DICOM files"):
        dicom_series_to_nifti(empty_dir, tmp_path / "bad.nii.gz")


def test_dicom_series_to_nifti_rejects_insufficient_slices(
    synthetic_chest_series: Path,
    tmp_path: Path,
) -> None:
    few_dir = tmp_path / "few_slices"
    few_dir.mkdir()
    for path in sorted_dicom_paths(synthetic_chest_series)[: MIN_DICOM_SLICES - 1]:
        shutil.copy(path, few_dir / path.name)
    with pytest.raises(ValueError, match=f"Need at least {MIN_DICOM_SLICES}"):
        dicom_series_to_nifti(few_dir, tmp_path / "too_few.nii.gz")


def test_dicom_series_to_nifti_committed_chest_assets(synthetic_ct_asset_dirs: dict[str, Path], tmp_path: Path) -> None:
    chest_dir = synthetic_ct_asset_dirs["chest"]
    nifti_path = tmp_path / "committed_chest.nii.gz"
    n_slices = dicom_series_to_nifti(chest_dir, nifti_path)
    assert n_slices >= MIN_DICOM_SLICES
    loaded = nib.load(nifti_path)
    assert loaded.ndim == 3


def _chest_structure_voxels() -> dict[str, int]:
    return {
        "lung_upper_lobe_left": 50_000,
        "lung_upper_lobe_right": 48_000,
        "heart": 10_000,
    }


def _head_structure_voxels() -> dict[str, int]:
    return {"brain": 80_000, "skull": 15_000}


def _abdomen_structure_voxels() -> dict[str, int]:
    return {"liver": 60_000, "spleen": 12_000, "kidney_left": 8_000}


@patch("anonymizer.controller.tseg.segment.analyze_contrast_phase")
@patch("anonymizer.controller.tseg.segment.run_segmentation")
@patch("anonymizer.controller.tseg.segment.collect_structure_voxels")
def test_analyze_series_synthetic_chest_pipeline(
    mock_collect: MagicMock,
    mock_seg: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_seg.return_value = 12.5
    mock_collect.return_value = _chest_structure_voxels()
    mock_contrast.return_value = ContrastResult("native", 4.0, 0.97, False)

    results = analyze_series([synthetic_chest_series])
    assert len(results) == 1
    result = results[0]
    assert result.error is None
    assert result.dominant_region == "Chest"
    assert result.body_parts_present == "Chest"
    assert result.contrast_phase == "native"
    assert result.radlex_series_description == "CT Chest Without Contrast"
    mock_seg.assert_called_once()
    mock_contrast.assert_called_once()


@patch("anonymizer.controller.tseg.segment.analyze_contrast_phase")
@patch("anonymizer.controller.tseg.segment.run_segmentation")
@patch("anonymizer.controller.tseg.segment.collect_structure_voxels")
def test_analyze_series_synthetic_head_pipeline(
    mock_collect: MagicMock,
    mock_seg: MagicMock,
    mock_contrast: MagicMock,
    synthetic_head_series: Path,
) -> None:
    mock_seg.return_value = 10.0
    mock_collect.return_value = _head_structure_voxels()
    mock_contrast.return_value = ContrastResult("portal_venous", 72.0, 0.91, True)

    results = analyze_series([synthetic_head_series])
    result = results[0]
    assert result.error is None
    assert result.dominant_region == "Head"
    assert result.radlex_series_description == "CT Head+Neck With Contrast"


@patch("anonymizer.controller.tseg.segment.analyze_contrast_phase")
@patch("anonymizer.controller.tseg.segment.run_segmentation")
@patch("anonymizer.controller.tseg.segment.collect_structure_voxels")
def test_analyze_series_synthetic_abdomen_pipeline(
    mock_collect: MagicMock,
    mock_seg: MagicMock,
    mock_contrast: MagicMock,
    synthetic_abdomen_series: Path,
) -> None:
    mock_seg.return_value = 11.0
    mock_collect.return_value = _abdomen_structure_voxels()
    mock_contrast.return_value = ContrastResult("native", 2.0, 0.99, False)

    results = analyze_series([synthetic_abdomen_series])
    result = results[0]
    assert result.error is None
    assert result.dominant_region == "Abdomen"
    assert result.radlex_series_description == "CT Abdomen Without Contrast"


@patch("anonymizer.controller.tseg.segment.analyze_contrast_phase")
@patch("anonymizer.controller.tseg.segment.run_segmentation")
@patch("anonymizer.controller.tseg.segment.collect_structure_voxels")
def test_analyze_series_contrast_failure_keeps_regions(
    mock_collect: MagicMock,
    mock_seg: MagicMock,
    mock_contrast: MagicMock,
    synthetic_chest_series: Path,
) -> None:
    mock_seg.return_value = 9.0
    mock_collect.return_value = _chest_structure_voxels()
    mock_contrast.side_effect = RuntimeError("XGBoost is required")

    results = analyze_series([synthetic_chest_series])
    result = results[0]
    assert result.body_parts_present == "Chest"
    assert result.contrast_phase == ""
    assert result.error is not None
    assert "XGBoost" in result.error


@patch("anonymizer.controller.tseg.segment.analyze_contrast_phase")
@patch("anonymizer.controller.tseg.segment.run_segmentation")
@patch("anonymizer.controller.tseg.segment.collect_structure_voxels")
def test_analyze_series_same_name_different_paths_do_not_collide(
    mock_collect: MagicMock,
    mock_seg: MagicMock,
    mock_contrast: MagicMock,
    tmp_path: Path,
) -> None:
    mock_seg.return_value = 1.0
    mock_collect.return_value = _chest_structure_voxels()
    mock_contrast.return_value = ContrastResult("native", 0.0, 0.9, False)

    series_a = tmp_path / "batch_a" / "series"
    series_b = tmp_path / "batch_b" / "series"
    for series in (series_a, series_b):
        series.mkdir(parents=True)
        for src in list_dcm_files(SYNTHETIC_CT_ASSET_DIRS["chest"])[:MIN_DICOM_SLICES]:
            (series / src.name).write_bytes(src.read_bytes())

    results = analyze_series([series_a, series_b])
    assert len(results) == 2
    assert all(isinstance(r, TS_result) and r.error is None for r in results)
