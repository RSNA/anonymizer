"""Tests for TS segmentation cache retention and adaptive ROI."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.config import ROI_SUBSET_HEAD, ROI_TIER_HEAD
from anonymizer.controller.ai.tseg.seg_retention import (
    aggregate_primary_segment_voxels,
    compute_latch_mask_keep_set,
    finalize_seg_cache,
    prune_seg_cache,
    read_mask_geometry,
    read_primary_segment_voxels,
    read_structure_voxels,
    resolve_harmonize_roi_subset,
    write_structure_voxels,
)
from anonymizer.controller.ai.tseg.segment import (
    _segmentation_cache_valid,
    collect_structure_voxels,
    write_roi_subset_manifest,
)
from anonymizer.view.series.anatomy_overlay import (
    collect_primary_segment_voxels,
    load_primary_segment_mask,
)


def _write_mask(path: Path, voxel_count: int, *, shape: tuple[int, int, int] = (4, 16, 16)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros(shape, dtype=np.uint8)
    flat = array.reshape(-1)
    flat[: min(voxel_count, flat.size)] = 1
    sitk.WriteImage(sitk.GetImageFromArray(array), str(path))


def test_latch_mask_stems_for_export_and_multilabel_write(tmp_path: Path) -> None:
    import nibabel as nib
    import numpy as np

    from anonymizer.controller.ai.tseg.seg_retention import (
        latch_mask_stems_for_export,
        write_binary_masks_from_multilabel,
    )
    from totalsegmentator.map_to_binary import class_map

    name_to_label = {name: int(label) for label, name in class_map["total"].items()}
    shape = (4, 8, 8)
    data = np.zeros(shape, dtype=np.uint8)
    data[0, 0:2, 0:2] = name_to_label["brain"]
    data[1, 0:2, 0:2] = name_to_label["skull"]
    data[2, 0:2, 0:2] = name_to_label["liver"]  # should not export (below latch set for head-only counts)
    img = nib.Nifti1Image(data, np.eye(4))

    structure_voxels = {"brain": 5000, "skull": 3000, "liver": 0, "heart": 0}
    stems = latch_mask_stems_for_export(structure_voxels)
    assert "brain" in stems
    assert "skull" in stems
    assert "liver" not in stems

    seg_dir = tmp_path / "seg"
    written = write_binary_masks_from_multilabel(img, seg_dir, stems, task="total")
    assert set(written) == {"brain", "skull"}
    assert (seg_dir / "brain.nii.gz").is_file()
    assert (seg_dir / "skull.nii.gz").is_file()
    assert not (seg_dir / "liver.nii.gz").is_file()
    brain = nib.load(str(seg_dir / "brain.nii.gz")).get_fdata()
    assert int((brain > 0).sum()) == 4

    cache_dir = tmp_path / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    _write_mask(seg_dir / "brain.nii.gz", 5000)
    _write_mask(seg_dir / "liver.nii.gz", 0)
    _write_mask(seg_dir / "heart.nii.gz", 0)

    structure_voxels = {"brain": 5000, "liver": 0, "heart": 0, "skull": 0}
    finalize_seg_cache(cache_dir, seg_dir, structure_voxels)

    assert read_structure_voxels(cache_dir) == structure_voxels
    assert read_primary_segment_voxels(cache_dir) == {"brain": 5000}
    assert read_mask_geometry(cache_dir) is not None
    assert (seg_dir / "brain.nii.gz").is_file()
    assert not (seg_dir / "liver.nii.gz").is_file()
    assert not (seg_dir / "heart.nii.gz").is_file()


def test_finalize_seg_cache_refuses_counts_without_masks(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    seg_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="no overlay masks"):
        finalize_seg_cache(cache_dir, seg_dir, {"brain": 5000, "skull": 0})


def test_anatomy_overlay_cache_ready_requires_masks(tmp_path: Path) -> None:
    from anonymizer.controller.ai.tseg.seg_retention import (
        anatomy_overlay_cache_ready,
        reconcile_primary_segment_sidecar,
        write_primary_segment_voxels,
        write_structure_voxels,
    )

    cache_dir = tmp_path / "0_TS_SEG"
    cache_dir.mkdir()
    write_structure_voxels(cache_dir, {"brain": 5000})
    write_primary_segment_voxels(cache_dir, {"brain": 5000})
    assert anatomy_overlay_cache_ready(cache_dir) is False

    reconciled = reconcile_primary_segment_sidecar(cache_dir)
    assert reconciled == {}
    assert read_primary_segment_voxels(cache_dir) in (None, {})


def test_collect_structure_voxels_reads_json_without_masks(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    seg_dir.mkdir(parents=True)
    write_structure_voxels(cache_dir, {"brain": 4000, "liver": 0})
    write_roi_subset_manifest(cache_dir, ["brain", "liver"])

    counts = collect_structure_voxels(seg_dir, ["brain", "liver"])
    assert counts == {"brain": 4000, "liver": 0}
    assert _segmentation_cache_valid(seg_dir, ["brain", "liver"])


def test_collect_primary_segment_voxels_reads_json(tmp_path: Path) -> None:
    from anonymizer.controller.ai.tseg.seg_retention import write_primary_segment_voxels

    cache_dir = tmp_path / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    _write_mask(seg_dir / "brain.nii.gz", 5000)
    _write_mask(seg_dir / "skull.nii.gz", 3000)
    write_primary_segment_voxels(cache_dir, {"brain": 5000, "skull": 3000, "spine": 9000})

    present = collect_primary_segment_voxels(seg_dir)
    assert present == {"brain": 5000, "skull": 3000}
    assert "spine" not in present


def test_aggregate_primary_require_masks_skips_stats_only_groups(tmp_path: Path) -> None:
    seg_dir = tmp_path / "seg"
    seg_dir.mkdir()
    _write_mask(seg_dir / "brainstem.nii.gz", 4000)
    structure_voxels = {"brain": 5000, "spinal_cord": 2000, "vertebrae_C1": 3000, "brainstem": 4000}
    present = aggregate_primary_segment_voxels(structure_voxels, seg_dir, require_masks=True)
    assert present == {"brainstem": 4000}
    assert "brain" not in present
    assert "spine" not in present
    assert "spinal_cord" not in present


def test_load_primary_segment_mask_uses_mask_geometry_without_volume(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    _write_mask(seg_dir / "brain.nii.gz", 5000, shape=(3, 12, 12))
    finalize_seg_cache(cache_dir, seg_dir, {"brain": 5000})

    mask = load_primary_segment_mask(seg_dir, "brain")
    assert mask.shape == (3, 12, 12)
    assert mask.sum() > 0


def test_prune_prefers_vertebrae_body_over_per_vertebra(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    _write_mask(seg_dir / "vertebrae_body.nii.gz", 2500)
    _write_mask(seg_dir / "vertebrae_C1.nii.gz", 1200)

    structure_voxels = {"vertebrae_body": 2500, "vertebrae_C1": 1200}
    primary = {"spine": 2500}
    keep = compute_latch_mask_keep_set(seg_dir, structure_voxels, primary)
    assert keep == {"vertebrae_body"}

    removed = prune_seg_cache(seg_dir, structure_voxels=structure_voxels, primary_segment_voxels=primary)
    assert "vertebrae_C1" in removed
    assert (seg_dir / "vertebrae_body.nii.gz").is_file()


def test_resolve_harmonize_roi_subset_head_from_body_part(tmp_path: Path) -> None:
    from pydicom import Dataset, FileDataset, Sequence
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    series_dir = tmp_path / "series"
    series_dir.mkdir()
    ds = FileDataset(
        str(series_dir / "slice.dcm"),
        {},
        file_meta=Dataset(),
        preamble=b"\0" * 128,
    )
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = generate_uid()
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "CT"
    ds.BodyPartExamined = "HEAD"
    ds.ImagePositionPatient = [0.0, 0.0, 0.0]
    ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    ds.PixelSpacing = [1.0, 1.0]
    ds.SliceThickness = 1.0
    ds.Rows = 16
    ds.Columns = 16
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.InstanceNumber = 1
    ds.save_as(str(series_dir / "slice.dcm"))

    subset, tier = resolve_harmonize_roi_subset(series_dir)
    assert tier == ROI_TIER_HEAD
    assert set(subset) == set(ROI_SUBSET_HEAD)


def test_aggregate_primary_segment_voxels_sums_bilateral_kidneys(tmp_path: Path) -> None:
    cache_dir = tmp_path / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    _write_mask(seg_dir / "kidney_left.nii.gz", 800)
    _write_mask(seg_dir / "kidney_right.nii.gz", 700)

    structure_voxels = {"kidney_left": 800, "kidney_right": 700}
    primary = aggregate_primary_segment_voxels(structure_voxels, seg_dir)
    assert primary["kidneys"] == 1500


@pytest.mark.parametrize(
    ("body_part", "expected_tier"),
    [
        ("CHEST", "CHEST"),
        ("ABDOMEN", "FULL"),
    ],
)
def test_resolve_harmonize_roi_subset_chest_and_full(
    tmp_path: Path,
    body_part: str,
    expected_tier: str,
) -> None:
    from pydicom import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    series_dir = tmp_path / f"series_{body_part.lower()}"
    series_dir.mkdir()
    ds = FileDataset(
        str(series_dir / "slice.dcm"),
        {},
        file_meta=Dataset(),
        preamble=b"\0" * 128,
    )
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = generate_uid()
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "CT"
    ds.BodyPartExamined = body_part
    ds.ImagePositionPatient = [0.0, 0.0, 0.0]
    ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    ds.PixelSpacing = [1.0, 1.0]
    ds.SliceThickness = 1.0
    ds.Rows = 16
    ds.Columns = 16
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.InstanceNumber = 1
    ds.save_as(str(series_dir / "slice.dcm"))

    _subset, tier = resolve_harmonize_roi_subset(series_dir)
    assert tier == expected_tier


def test_evict_tseg_volume_after_segmentation_sidecars(tmp_path: Path) -> None:
    from anonymizer.controller.ai.tseg.seg_retention import evict_tseg_volume

    series_dir = tmp_path / "series"
    cache_dir = series_dir / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    _write_mask(seg_dir / "brain.nii.gz", 5000)
    finalize_seg_cache(cache_dir, seg_dir, {"brain": 5000})
    volume = cache_dir / "volume.nii.gz"
    _write_mask(volume, 1, shape=(2, 8, 8))

    assert evict_tseg_volume(series_dir) is True
    assert not volume.is_file()


def test_evict_tseg_volume_keeps_volume_without_sidecars(tmp_path: Path) -> None:
    from anonymizer.controller.ai.tseg.seg_retention import evict_tseg_volume

    series_dir = tmp_path / "series"
    cache_dir = series_dir / "0_TS_SEG"
    cache_dir.mkdir(parents=True)
    volume = cache_dir / "volume.nii.gz"
    _write_mask(volume, 1, shape=(2, 8, 8))

    assert evict_tseg_volume(series_dir) is False
    assert volume.is_file()


def _write_ct_series_dicom(series_dir: Path, *, body_part: str = "HEAD") -> str:
    from pydicom import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    series_dir.mkdir(parents=True, exist_ok=True)
    series_uid = generate_uid()
    ds = FileDataset(
        str(series_dir / "slice.dcm"),
        {},
        file_meta=Dataset(),
        preamble=b"\0" * 128,
    )
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = generate_uid()
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "CT"
    ds.SeriesInstanceUID = series_uid
    ds.BodyPartExamined = body_part
    ds.ImagePositionPatient = [0.0, 0.0, 0.0]
    ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    ds.PixelSpacing = [1.0, 1.0]
    ds.SliceThickness = 1.0
    ds.Rows = 16
    ds.Columns = 16
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.InstanceNumber = 1
    ds.save_as(str(series_dir / "slice.dcm"))
    return series_uid


def _write_evictable_cache(series_dir: Path) -> Path:
    cache_dir = series_dir / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    _write_mask(seg_dir / "brain.nii.gz", 5000)
    finalize_seg_cache(cache_dir, seg_dir, {"brain": 5000})
    volume = cache_dir / "volume.nii.gz"
    _write_mask(volume, 1, shape=(2, 8, 8))
    return volume


class _FaceBlurModel:
    def __init__(self, *, applied: bool) -> None:
        self._applied = applied

    def series_has_face_blur(self, _anon_series_uid: str) -> bool:
        return self._applied


def test_evict_tseg_volume_keeps_ct_head_until_face_blur(tmp_path: Path) -> None:
    from anonymizer.controller.ai.tseg.seg_retention import evict_tseg_volume

    series_dir = tmp_path / "head_series"
    _write_ct_series_dicom(series_dir, body_part="HEAD")
    volume = _write_evictable_cache(series_dir)

    assert evict_tseg_volume(series_dir) is False
    assert volume.is_file()
    assert evict_tseg_volume(series_dir, anon_model=_FaceBlurModel(applied=False)) is False
    assert volume.is_file()


def test_evict_tseg_volume_removes_ct_head_after_face_blur(tmp_path: Path) -> None:
    from anonymizer.controller.ai.tseg.seg_retention import evict_tseg_volume

    series_dir = tmp_path / "head_series"
    _write_ct_series_dicom(series_dir, body_part="HEAD")
    volume = _write_evictable_cache(series_dir)

    assert evict_tseg_volume(series_dir, anon_model=_FaceBlurModel(applied=True)) is True
    assert not volume.is_file()


def test_evict_tseg_volume_removes_ct_chest_with_sidecars(tmp_path: Path) -> None:
    from anonymizer.controller.ai.tseg.seg_retention import evict_tseg_volume

    series_dir = tmp_path / "chest_series"
    _write_ct_series_dicom(series_dir, body_part="CHEST")
    cache_dir = series_dir / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    _write_mask(seg_dir / "lung_upper_lobe_left.nii.gz", 5000)
    finalize_seg_cache(cache_dir, seg_dir, {"lung_upper_lobe_left": 5000})
    volume = cache_dir / "volume.nii.gz"
    _write_mask(volume, 1, shape=(2, 8, 8))

    assert evict_tseg_volume(series_dir) is True
    assert not volume.is_file()
