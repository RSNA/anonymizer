"""Tests for researcher NIfTI/NRRD segment import profiles."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.annotations import (
    ImportProfile,
    add_user_label,
    export_ml_bundle,
    import_binary_masks,
    import_folder_binary_masks,
    import_label_nifti,
    load_annotate_session,
    parse_itk_snap_label_file,
    parse_nnunet_dataset_json,
    save_annotate_session,
    stamp_brush,
)
from anonymizer.controller.annotations.import_nii import (
    align_label_image_to_reference,
    detect_and_import,
)
from anonymizer.controller.ai.tseg.seg_retention import MASK_GEOMETRY_FILENAME, mask_geometry_from_image


def _write_geometry_volume(cache_dir: Path, shape_zyx: tuple[int, int, int] = (4, 32, 32)) -> sitk.Image:
    cache_dir.mkdir(parents=True, exist_ok=True)
    z, y, x = shape_zyx
    arr = np.zeros((z, y, x), dtype=np.int16)
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((1.0, 1.0, 1.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    sitk.WriteImage(img, str(cache_dir / "volume.nii.gz"), True)
    (cache_dir / MASK_GEOMETRY_FILENAME).write_text(
        json.dumps(mask_geometry_from_image(img)) + "\n", encoding="utf-8"
    )
    return img


def _write_label_nii(path: Path, arr: np.ndarray, *, spacing=(1.0, 1.0, 1.0), origin=(0.0, 0.0, 0.0)) -> None:
    img = sitk.GetImageFromArray(arr.astype(np.uint16, copy=False))
    img.SetSpacing(spacing)
    img.SetOrigin(origin)
    path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(img, str(path), True)


def test_parse_itk_snap_label_file(tmp_path: Path) -> None:
    path = tmp_path / "seg.label"
    path.write_text(
        "# ITK-SnAP Label Description File\n"
        '0 0 0 0 0 0 0 "Clear Label"\n'
        '1 255 0 0 1 1 1 "Lesion"\n'
        '2 0 255 0 1 1 1 "Vessel"\n',
        encoding="utf-8",
    )
    parsed = parse_itk_snap_label_file(path)
    assert 0 not in parsed
    assert parsed[1].name == "Lesion"
    assert parsed[1].color_bgr == (0, 0, 255)  # RGB → BGR
    assert parsed[2].name == "Vessel"


def test_parse_nnunet_dataset_json(tmp_path: Path) -> None:
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps(
            {
                "labels": {"background": 0, "tumor": 1, "edema": 2},
                "file_ending": ".nii.gz",
            }
        ),
        encoding="utf-8",
    )
    parsed = parse_nnunet_dataset_json(path)
    assert parsed[1].name == "tumor"
    assert parsed[2].name == "edema"
    assert 0 not in parsed


def test_import_ml_bundle_roundtrip(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    entry = add_user_label(session, "lesion")
    stamp_brush(session.labels, slice_index=1, cy=16, cx=16, radius=3, value=entry.label_id)
    save_annotate_session(session)
    bundle = tmp_path / "bundle"
    export_ml_bundle(cache, bundle, session=session)

    session.labels[:] = 0
    session.label_map.clear()
    session.dirty = True
    save_annotate_session(session)

    result = import_label_nifti(session, bundle / "labels.nii.gz", profile=ImportProfile.AUTO)
    assert len(result.entries) == 1
    assert result.entries[0].name == "lesion"
    assert int(session.labels[1, 16, 16]) == result.entries[0].label_id


def test_import_itk_snap_with_label_sidecar(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None

    labels = np.zeros((4, 32, 32), dtype=np.uint16)
    labels[2, 10:14, 10:14] = 1
    labels[2, 20:22, 20:22] = 2
    vol_path = tmp_path / "itk" / "seg.nii.gz"
    _write_label_nii(vol_path, labels)
    (tmp_path / "itk" / "seg.label").write_text(
        '1 255 0 0 1 1 1 "Lesion"\n' '2 0 128 255 1 1 1 "Vessel"\n',
        encoding="utf-8",
    )

    result = import_label_nifti(session, vol_path, profile=ImportProfile.ITK_SNAP)
    assert result.profile == ImportProfile.ITK_SNAP
    names = {e.name for e in result.entries}
    assert names == {"Lesion", "Vessel"}
    lesion = next(e for e in result.entries if e.name == "Lesion")
    assert int(session.labels[2, 12, 12]) == lesion.label_id


def test_import_nnunet_with_dataset_json(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None

    labels = np.zeros((4, 32, 32), dtype=np.uint16)
    labels[1, 5:10, 5:10] = 1
    case = tmp_path / "Dataset001" / "labelsTr" / "case.nii.gz"
    _write_label_nii(case, labels)
    (tmp_path / "Dataset001" / "dataset.json").write_text(
        json.dumps({"labels": {"background": 0, "tumor": 1}}),
        encoding="utf-8",
    )

    result = import_label_nifti(session, case, profile=ImportProfile.NNUNET)
    assert result.entries[0].name == "tumor"
    assert int(np.count_nonzero(session.labels == result.entries[0].label_id)) == 25


def test_import_totalsegmentator_folder(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None

    folder = tmp_path / "ts_out"
    liver = np.zeros((4, 32, 32), dtype=np.uint8)
    liver[0, 8:12, 8:12] = 1
    spleen = np.zeros((4, 32, 32), dtype=np.uint8)
    spleen[1, 16:18, 16:18] = 1
    _write_label_nii(folder / "liver.nii.gz", liver)
    _write_label_nii(folder / "spleen.nii.gz", spleen)

    result = import_folder_binary_masks(session, folder)
    assert result.profile == ImportProfile.FOLDER_TS
    assert {e.name for e in result.entries} == {"liver", "spleen"}


def test_import_binary_masks_merge_preserves_existing(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    existing = add_user_label(session, "keep_me")
    stamp_brush(session.labels, slice_index=0, cy=4, cx=4, radius=2, value=existing.label_id)
    save_annotate_session(session)

    mask = np.zeros((4, 32, 32), dtype=np.uint8)
    mask[3, 20:24, 20:24] = 1
    path = tmp_path / "extra.nii.gz"
    _write_label_nii(path, mask)
    result = import_binary_masks(session, [path], names=["imported"])
    assert existing.label_id in session.label_map
    assert int(session.labels[0, 4, 4]) == existing.label_id
    assert result.entries[0].name == "imported"
    assert int(session.labels[3, 22, 22]) == result.entries[0].label_id


def test_align_nearest_neighbor_resample() -> None:
    ref = sitk.GetImageFromArray(np.zeros((4, 16, 16), dtype=np.uint16))
    ref.SetSpacing((1.0, 1.0, 1.0))
    src_arr = np.zeros((2, 8, 8), dtype=np.uint16)
    src_arr[1, 4, 4] = 7
    src = sitk.GetImageFromArray(src_arr)
    src.SetSpacing((2.0, 2.0, 2.0))
    aligned, resampled, warn = align_label_image_to_reference(src, ref)
    assert resampled
    assert warn is not None
    out = sitk.GetArrayFromImage(aligned)
    assert out.shape == (4, 16, 16)
    assert int(out.max()) == 7


def test_import_nrrd_multilabel(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None

    labels = np.zeros((4, 32, 32), dtype=np.uint16)
    labels[0, 1:3, 1:3] = 1
    path = tmp_path / "slicer_seg.nrrd"
    img = sitk.GetImageFromArray(labels)
    img.SetSpacing((1.0, 1.0, 1.0))
    sitk.WriteImage(img, str(path))

    result = detect_and_import(session, paths=[path], profile=ImportProfile.MULTILABEL)
    assert len(result.entries) == 1
    assert int(np.count_nonzero(session.labels)) == 4


def test_detect_and_import_auto_multifile_as_binary(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    a = np.zeros((4, 32, 32), dtype=np.uint8)
    a[0, 2, 2] = 1
    b = np.zeros((4, 32, 32), dtype=np.uint8)
    b[0, 5, 5] = 1
    pa = tmp_path / "a.nii.gz"
    pb = tmp_path / "b.nii.gz"
    _write_label_nii(pa, a)
    _write_label_nii(pb, b)
    result = detect_and_import(session, paths=[pa, pb], profile=ImportProfile.AUTO)
    assert result.profile == ImportProfile.BINARY_MASKS
    assert len(result.entries) == 2
