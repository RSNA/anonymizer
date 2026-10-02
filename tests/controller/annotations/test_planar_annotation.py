"""Planar CR/DX/US/MG annotation geometry (pixel-space fallback)."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.ai.tseg.dicom_geometry import is_stackable_image_header
from anonymizer.controller.ai.tseg.seg_retention import read_mask_geometry
from anonymizer.controller.annotations import (
    add_user_label,
    ensure_series_annotation_geometry,
    export_dicom_seg,
    load_annotate_session,
    save_annotate_session,
    stamp_brush,
    user_annotation_volumes_ml,
)
from anonymizer.controller.annotations.planar_geometry import (
    PLANAR_PIXEL_SPACE,
    annotation_source_dicom_paths,
    is_planar_pixel_space_geometry,
)
from anonymizer.controller.series_io import load_series_frames
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR
from tests.controller.tseg.support.synthetic_ct import build_synthetic_ct_small_series

DAVIDSON_CXR = CONTROLLER_TEST_DCM_FILES_DIR / "davidson_cxr"
US_MULTI = CONTROLLER_TEST_DCM_FILES_DIR / "us_multi_frame_grayscale"
US_RGB = CONTROLLER_TEST_DCM_FILES_DIR / "us_rgb_single_frame"


def _require_fixture(path: Path) -> Path:
    if not path.is_dir() or not any(path.glob("*.dcm")):
        pytest.skip(f"Missing fixture: {path}")
    return path


def _copy_series(src: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def _write_synthetic_mg_series(output_dir: Path) -> Path:
    """Single-frame MG without IOP/IPP (planar pixel-space annotate path)."""
    series_dir = Path(output_dir)
    series_dir.mkdir(parents=True, exist_ok=True)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(series_dir / "mg.dcm"), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "MG"
    ds.PatientName = "Anon^MG"
    ds.PatientID = "MG001"
    ds.Rows = 64
    ds.Columns = 64
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelSpacing = [0.1, 0.1]
    ds.InstanceNumber = 1
    ds.PixelData = np.zeros((64, 64), dtype=np.uint16).tobytes()
    # Explicitly no IOP/IPP
    assert not hasattr(ds, "ImageOrientationPatient")
    assert not hasattr(ds, "ImagePositionPatient")
    ds.save_as(str(series_dir / "mg.dcm"), enforce_file_format=True)
    return series_dir


def test_planar_cxr_annotation_roundtrip(tmp_path: Path) -> None:
    src = _require_fixture(DAVIDSON_CXR)
    series = _copy_series(src, tmp_path / "cxr")
    cache = resolve_series_cache_dir(series)

    session = ensure_series_annotation_geometry(series, cache)
    assert session is not None
    assert is_planar_pixel_space_geometry(cache)
    geometry = read_mask_geometry(cache)
    assert geometry is not None
    assert geometry.get("grid") == PLANAR_PIXEL_SPACE

    loaded = load_series_frames(series)
    assert session.labels.shape[0] == loaded.frames.shape[0]
    assert session.labels.shape[1:] == loaded.frames.shape[1:3]

    entry = add_user_label(session, "opacity")
    stamp_brush(session.labels, slice_index=0, cy=32, cx=32, radius=5, value=entry.label_id)
    save_annotate_session(session)

    reloaded = load_annotate_session(cache)
    assert reloaded is not None
    assert int(reloaded.labels[0, 32, 32]) == entry.label_id
    assert user_annotation_volumes_ml(cache) == {}


def test_planar_cxr_dicom_seg_export(tmp_path: Path) -> None:
    src = _require_fixture(DAVIDSON_CXR)
    series = _copy_series(src, tmp_path / "cxr")
    cache = resolve_series_cache_dir(series)
    session = ensure_series_annotation_geometry(series, cache)
    entry = add_user_label(session, "roi")
    stamp_brush(session.labels, slice_index=0, cy=40, cx=40, radius=6, value=entry.label_id)
    save_annotate_session(session)

    dest = tmp_path / "roi_annotations.seg.dcm"
    export_dicom_seg(cache, dest, series_dir=series, session=session)
    assert dest.is_file()
    seg = pydicom.dcmread(str(dest))
    assert str(seg.SOPClassUID).startswith("1.2.840.10008.5.1.4.1.1.66.4")
    assert hasattr(seg, "ReferencedSeriesSequence")
    assert len(seg.ReferencedSeriesSequence[0].ReferencedInstanceSequence) >= 1


def test_planar_us_multiframe_z_matches_frames(tmp_path: Path) -> None:
    src = _require_fixture(US_MULTI)
    series = _copy_series(src, tmp_path / "us_mf")
    cache = resolve_series_cache_dir(series)
    session = ensure_series_annotation_geometry(series, cache)
    loaded = load_series_frames(series)
    assert session.labels.shape[0] == loaded.frames.shape[0]
    assert session.labels.shape[0] > 1
    assert is_planar_pixel_space_geometry(cache)
    paths = annotation_source_dicom_paths(series)
    assert len(paths) == loaded.frames.shape[0]


def test_planar_us_rgb_annotation(tmp_path: Path) -> None:
    src = _require_fixture(US_RGB)
    series = _copy_series(src, tmp_path / "us_rgb")
    cache = resolve_series_cache_dir(series)
    session = ensure_series_annotation_geometry(series, cache)
    loaded = load_series_frames(series)
    assert loaded.frames.ndim == 4
    assert session.labels.ndim == 3
    assert session.labels.shape[0] == loaded.frames.shape[0]
    assert session.labels.shape[1:] == loaded.frames.shape[1:3]
    entry = add_user_label(session, "probe")
    stamp_brush(session.labels, slice_index=0, cy=10, cx=10, radius=3, value=entry.label_id)
    save_annotate_session(session)
    assert int(session.labels[0, 10, 10]) == entry.label_id


def test_planar_mg_annotation(tmp_path: Path) -> None:
    series = _write_synthetic_mg_series(tmp_path / "mg")
    assert not is_stackable_image_header(pydicom.dcmread(str(next(series.glob("*.dcm"))), stop_before_pixels=True))
    cache = resolve_series_cache_dir(series)
    session = ensure_series_annotation_geometry(series, cache)
    assert is_planar_pixel_space_geometry(cache)
    assert session.labels.shape == (1, 64, 64)
    entry = add_user_label(session, "calc")
    stamp_brush(session.labels, slice_index=0, cy=20, cx=20, radius=4, value=entry.label_id)
    save_annotate_session(session)
    assert int(load_annotate_session(cache).labels[0, 20, 20]) == entry.label_id  # type: ignore[union-attr]
    assert user_annotation_volumes_ml(cache) == {}


def test_stackable_ct_keeps_non_planar_geometry(tmp_path: Path) -> None:
    series = build_synthetic_ct_small_series(tmp_path / "ct")
    cache = resolve_series_cache_dir(series)
    session = ensure_series_annotation_geometry(series, cache)
    assert session is not None
    assert not is_planar_pixel_space_geometry(cache)
    geometry = read_mask_geometry(cache)
    assert geometry is not None
    assert geometry.get("grid") != PLANAR_PIXEL_SPACE
    # Stackable path should retain patient origin from DICOM, not forced zeros-only planar.
    origin = tuple(float(v) for v in session.reference_image.GetOrigin())
    assert origin != (0.0, 0.0, 0.0) or session.labels.shape[0] > 1


def test_reference_frames_rebuilds_mismatched_grid(tmp_path: Path) -> None:
    """Stale label grids (wrong HxW) must rebuild against Series View frames."""
    series = _write_synthetic_mg_series(tmp_path / "mg")
    cache = resolve_series_cache_dir(series)
    session = ensure_series_annotation_geometry(series, cache)
    assert session.labels.shape == (1, 64, 64)
    # Poison cache with a different-sized volume/geometry.
    wrong = np.zeros((1, 32, 40), dtype=np.float32)
    from pydicom.dataset import Dataset

    from anonymizer.controller.annotations.planar_geometry import (
        build_planar_sitk_volume,
        write_planar_annotation_geometry,
    )

    ds = Dataset()
    ds.PixelSpacing = [0.1, 0.1]
    ds.Modality = "MG"
    write_planar_annotation_geometry(cache, build_planar_sitk_volume(ds, wrong))
    poisoned = load_annotate_session(cache)
    assert poisoned is not None
    assert poisoned.labels.shape == (1, 32, 40)

    display = np.zeros((1, 64, 64), dtype=np.float32)
    fixed = ensure_series_annotation_geometry(series, cache, reference_frames=display)
    assert fixed.labels.shape == (1, 64, 64)
