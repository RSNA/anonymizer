"""Tests for ROI annotation store, brush, and exports."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.cache import clear_tseg_series_cache, resolve_series_cache_dir
from anonymizer.controller.annotations import (
    add_user_label,
    annotations_exist,
    begin_stroke_capture,
    commit_stroke_undo,
    ensure_ts_edit,
    export_dicom_seg,
    export_ml_bundle,
    labels_path,
    load_annotate_session,
    save_annotate_session,
    stamp_brush,
    undo_last_stroke,
)
from anonymizer.controller.annotations.store import annotations_dir, edits_dir


def _write_geometry_volume(cache_dir: Path, shape_zyx: tuple[int, int, int] = (4, 32, 32)) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    z, y, x = shape_zyx
    arr = np.zeros((z, y, x), dtype=np.int16)
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((1.0, 1.0, 1.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    sitk.WriteImage(img, str(cache_dir / "volume.nii.gz"), True)
    from anonymizer.controller.ai.tseg.seg_retention import (
        MASK_GEOMETRY_FILENAME,
        mask_geometry_from_image,
    )

    payload = mask_geometry_from_image(img)
    import json

    (cache_dir / MASK_GEOMETRY_FILENAME).write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_annotate_session_roundtrip(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)

    session = load_annotate_session(cache)
    assert session is not None
    entry = add_user_label(session, "lesion")
    stamp_brush(session.labels, slice_index=1, cy=16, cx=16, radius=3, value=entry.label_id)
    assert int(session.labels[1, 16, 16]) == entry.label_id
    save_annotate_session(session)

    assert labels_path(cache).is_file()
    reloaded = load_annotate_session(cache)
    assert reloaded is not None
    assert entry.label_id in reloaded.label_map
    assert reloaded.label_map[entry.label_id].name == "lesion"
    assert int(reloaded.labels[1, 16, 16]) == entry.label_id


def test_brush_undo(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    entry = add_user_label(session, "roi")
    before = begin_stroke_capture(session.labels, slice_index=0)
    stamp_brush(session.labels, slice_index=0, cy=10, cx=10, radius=2, value=entry.label_id)
    commit_stroke_undo(session, kind="user", structure_name=None, slice_index=0, before_slice=before)
    assert int(session.labels[0, 10, 10]) == entry.label_id
    assert undo_last_stroke(session)
    assert int(session.labels[0, 10, 10]) == 0


def test_ts_edit_does_not_clobber_seg(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    seg_dir = cache / "seg"
    seg_dir.mkdir()
    brain = np.zeros((4, 32, 32), dtype=np.uint8)
    brain[1, 8:24, 8:24] = 1
    sitk.WriteImage(sitk.GetImageFromArray(brain), str(seg_dir / "brain.nii.gz"), True)

    session = load_annotate_session(cache)
    assert session is not None
    edited = ensure_ts_edit(session, "brain", source_mask=brain)
    stamp_brush(edited, slice_index=1, cy=16, cx=16, radius=5, value=0)
    save_annotate_session(session)

    # Original pristine
    original = sitk.GetArrayFromImage(sitk.ReadImage(str(seg_dir / "brain.nii.gz")))
    assert int(original[1, 16, 16]) == 1
    assert (edits_dir(cache) / "brain.nii.gz").is_file()
    edited_disk = sitk.GetArrayFromImage(sitk.ReadImage(str(edits_dir(cache) / "brain.nii.gz")))
    assert int(edited_disk[1, 16, 16]) == 0


def test_clear_cache_preserves_annotations(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    (cache / "seg").mkdir()
    (cache / "seg" / "dummy.txt").write_text("x", encoding="utf-8")
    session = load_annotate_session(cache)
    assert session is not None
    add_user_label(session, "keep_me")
    save_annotate_session(session)
    assert annotations_exist(cache)

    clear_tseg_series_cache(series, also_clear_annotations=False)
    assert annotations_dir(cache).is_dir()
    assert labels_path(cache).is_file()
    assert not (cache / "seg").exists()

    clear_tseg_series_cache(series, also_clear_annotations=True)
    assert not cache.exists() or not annotations_exist(cache)


def test_export_ml_bundle(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    add_user_label(session, "lesion")
    stamp_brush(session.labels, slice_index=0, cy=5, cx=5, radius=2, value=1)
    save_annotate_session(session)
    dest = tmp_path / "export"
    export_ml_bundle(cache, dest, session=session)
    assert (dest / "volume.nii.gz").is_file()
    assert (dest / "labels.nii.gz").is_file()
    assert (dest / "label_map.json").is_file()
    assert (dest / "export_meta.json").is_file()


def test_export_dicom_seg(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    add_user_label(session, "lesion")
    stamp_brush(session.labels, slice_index=1, cy=16, cx=16, radius=4, value=1)
    save_annotate_session(session)
    out = tmp_path / "roi.seg.dcm"
    export_dicom_seg(cache, out, series_dir=None, session=session)
    assert out.is_file()
    from pydicom import dcmread

    ds = dcmread(str(out), force=True)
    assert str(ds.SOPClassUID) == "1.2.840.10008.5.1.4.1.1.66.4"
    assert int(ds.NumberOfFrames) >= 1


def _unpack_binary_seg_frames(pixel_data: bytes, *, n_frames: int, rows: int, cols: int) -> np.ndarray:
    """Unpack DICOM-SEG bit-packed PixelData (little-endian) into ``(N, H, W)`` uint8."""
    bits_needed = n_frames * rows * cols
    packed = np.frombuffer(pixel_data, dtype=np.uint8)
    bits = np.unpackbits(packed, bitorder="little")[:bits_needed]
    return bits.reshape(n_frames, rows, cols)


def test_ct_head_annotate_five_slices_exports_both_formats(tmp_path: Path) -> None:
    """Paint a new ROI on 5 CT head slices; export NIfTI + DICOM-SEG; validate both."""
    import json

    from pydicom import dcmread

    from anonymizer.controller.ai.tseg.dicom_geometry import build_sitk_volume_from_series_frames
    from anonymizer.controller.ai.tseg.seg_retention import (
        MASK_GEOMETRY_FILENAME,
        mask_geometry_from_image,
    )
    from anonymizer.controller.series_io import load_series_frames
    from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

    series = CONTROLLER_TEST_DCM_FILES_DIR / "CT_Head_With_Contrast"
    if not series.is_dir():
        pytest.skip("CT_Head_With_Contrast fixture missing")

    loaded = load_series_frames(series)
    volume = build_sitk_volume_from_series_frames(loaded.metadata, loaded.frames, loaded.slice_paths)
    assert volume.GetSize()[2] >= 5

    cache = tmp_path / "0_TS_SEG"
    cache.mkdir(parents=True)
    sitk.WriteImage(volume, str(cache / "volume.nii.gz"), True)
    (cache / MASK_GEOMETRY_FILENAME).write_text(
        json.dumps(mask_geometry_from_image(volume)) + "\n", encoding="utf-8"
    )

    session = load_annotate_session(cache)
    assert session is not None
    z, h, w = session.labels.shape
    assert (z, h, w) == (
        int(volume.GetSize()[2]),
        int(volume.GetSize()[1]),
        int(volume.GetSize()[0]),
    )

    entry = add_user_label(session, "ct_head_roi")
    mid = z // 2
    slice_indices = [mid - 2, mid - 1, mid, mid + 1, mid + 2]
    assert all(0 <= zi < z for zi in slice_indices)
    cy, cx, radius = h // 2, w // 2, 8
    for zi in slice_indices:
        stamped = stamp_brush(
            session.labels,
            slice_index=zi,
            cy=cy,
            cx=cx,
            radius=radius,
            value=entry.label_id,
        )
        assert stamped is not None
        assert int(session.labels[zi, cy, cx]) == entry.label_id
    save_annotate_session(session)

    expected_voxels_per_slice = int(
        ((np.arange(-radius, radius + 1)[:, None] ** 2 + np.arange(-radius, radius + 1)[None, :] ** 2) <= radius**2).sum()
    )
    assert expected_voxels_per_slice > 0

    # --- NIfTI ML bundle ---
    nii_dest = tmp_path / "nii_export"
    export_ml_bundle(cache, nii_dest, session=session)
    assert (nii_dest / "volume.nii.gz").is_file()
    assert (nii_dest / "labels.nii.gz").is_file()
    assert (nii_dest / "label_map.json").is_file()
    assert (nii_dest / "export_meta.json").is_file()

    labels_img = sitk.ReadImage(str(nii_dest / "labels.nii.gz"))
    labels_arr = sitk.GetArrayFromImage(labels_img).astype(np.uint16, copy=False)
    vol_arr = sitk.GetArrayFromImage(sitk.ReadImage(str(nii_dest / "volume.nii.gz")))
    assert labels_arr.shape == vol_arr.shape == (z, h, w)
    assert labels_img.GetSpacing() == volume.GetSpacing()
    assert labels_img.GetOrigin() == volume.GetOrigin()

    label_map = json.loads((nii_dest / "label_map.json").read_text(encoding="utf-8"))
    assert str(entry.label_id) in label_map
    assert label_map[str(entry.label_id)]["name"] == "ct_head_roi"

    positive_slices = [int(i) for i in np.flatnonzero(np.any(labels_arr == entry.label_id, axis=(1, 2)))]
    assert positive_slices == slice_indices
    for zi in slice_indices:
        assert int(np.count_nonzero(labels_arr[zi] == entry.label_id)) == expected_voxels_per_slice
    assert int(np.count_nonzero(labels_arr == entry.label_id)) == expected_voxels_per_slice * 5

    # --- DICOM-SEG ---
    seg_path = tmp_path / "roi_annotations.seg.dcm"
    export_dicom_seg(cache, seg_path, series_dir=series, session=session)
    assert seg_path.is_file()

    ds = dcmread(str(seg_path), force=True)
    assert str(ds.SOPClassUID) == "1.2.840.10008.5.1.4.1.1.66.4"
    assert str(ds.Modality) == "SEG"
    assert str(ds.SegmentationType) == "BINARY"
    assert int(ds.Rows) == h
    assert int(ds.Columns) == w
    assert int(ds.NumberOfFrames) == 5
    assert len(ds.SegmentSequence) == 1
    assert str(ds.SegmentSequence[0].SegmentLabel) == "ct_head_roi"
    assert str(ds.SegmentSequence[0].SegmentAlgorithmType) == "MANUAL"
    assert len(ds.PerFrameFunctionalGroupsSequence) == 5

    # Source SOP refs match the annotated slice stack order.
    from anonymizer.controller.ai.tseg.dicom_geometry import stackable_dicom_paths

    source_paths = stackable_dicom_paths(series)
    assert len(source_paths) == z
    for frame_i, zi in enumerate(slice_indices):
        fg = ds.PerFrameFunctionalGroupsSequence[frame_i]
        assert int(fg.SegmentIdentificationSequence[0].SegmentNumber) == 1
        src = fg.DerivationImageSequence[0].SourceImageSequence[0]
        ref_ds = dcmread(str(source_paths[zi]), stop_before_pixels=True, force=True)
        assert str(src.ReferencedSOPInstanceUID) == str(ref_ds.SOPInstanceUID)

    frames = _unpack_binary_seg_frames(
        bytes(ds.PixelData),
        n_frames=int(ds.NumberOfFrames),
        rows=int(ds.Rows),
        cols=int(ds.Columns),
    )
    assert frames.shape == (5, h, w)
    for frame in frames:
        assert int(frame[cy, cx]) == 1
        assert int(frame.sum()) == expected_voxels_per_slice
