"""Tests for blurred face DICOM export."""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import numpy as np
import pydicom
from pydicom.data import get_testdata_file

from anonymizer.controller.ai.blur_face import (
    blur_face_hu_volume,
    load_hu_stack,
    write_blurred_dicom_series,
)
from anonymizer.controller.series_io import load_series_frames, save_series_frames


def _write_template_slice(path: Path, *, hu_value: float, instance_number: int) -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    stored = np.full(ds.pixel_array.shape, hu_value, dtype=np.float64)
    stored = (stored - float(ds.RescaleIntercept)) / float(ds.RescaleSlope)
    ds.PixelData = stored.astype(ds.pixel_array.dtype).tobytes()
    ds.InstanceNumber = instance_number
    ds.SOPInstanceUID = pydicom.uid.generate_uid()
    if getattr(ds, "ImagePositionPatient", None) is not None:
        ipp = [float(value) for value in ds.ImagePositionPatient]
        ipp[2] += float(instance_number - 1)
        ds.ImagePositionPatient = ipp
    ds.save_as(path)


def test_write_blurred_dicom_series_preserves_geometry(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    source_dir.mkdir()
    slice_paths = tuple(source_dir / f"slice_{index:03d}.dcm" for index in range(2))
    _write_template_slice(slice_paths[0], hu_value=-100.0, instance_number=1)
    _write_template_slice(slice_paths[1], hu_value=40.0, instance_number=2)

    hu_before = load_hu_stack(slice_paths)
    mask = np.zeros(hu_before.shape, dtype=bool)
    mask[:, 20:40, 20:40] = True
    hu_after = blur_face_hu_volume(
        hu_before,
        mask,
        sigma_mm=4.0,
        pixel_spacing_mm=(1.0, 1.0),
    )

    out_dir = tmp_path / "face_blurred"
    written_paths = write_blurred_dicom_series(hu_after, slice_paths, out_dir)

    assert len(written_paths) == 2

    source_ds = pydicom.dcmread(slice_paths[0])
    out_ds = pydicom.dcmread(written_paths[0])
    assert out_ds.ImagePositionPatient == source_ds.ImagePositionPatient
    assert out_ds.ImageOrientationPatient == source_ds.ImageOrientationPatient
    assert list(out_ds.PixelSpacing) == list(source_ds.PixelSpacing)
    assert out_ds.Rows == source_ds.Rows
    assert out_ds.Columns == source_ds.Columns
    assert out_ds.SeriesInstanceUID != source_ds.SeriesInstanceUID
    assert "face blurred" in out_ds.SeriesDescription.lower()
    assert out_ds.SpecificCharacterSet == "ISO_IR 192"

    reloaded = load_hu_stack(written_paths)
    assert reloaded.shape == hu_after.shape
    assert np.allclose(reloaded, hu_after, atol=1.0)
    assert np.allclose(reloaded[~mask], hu_before[~mask], atol=1.0)


def test_save_series_frames_preserves_ct_encoding(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()
    slice_paths = tuple(source_dir / f"slice_{index:03d}.dcm" for index in range(2))
    _write_template_slice(slice_paths[0], hu_value=-100.0, instance_number=1)
    _write_template_slice(slice_paths[1], hu_value=40.0, instance_number=2)

    loaded = load_series_frames(source_dir)

    reference_ds, frames, loaded_paths = loaded.metadata, loaded.frames, loaded.slice_paths
    assert loaded_paths == slice_paths

    for path in slice_paths:
        shutil.copy2(path, output_dir / path.name)

    assert save_series_frames(output_dir, frames, reference_ds)

    for source_path in slice_paths:
        source_ds = pydicom.dcmread(source_path)
        output_ds = pydicom.dcmread(output_dir / source_path.name)
        assert float(output_ds.RescaleSlope) == float(source_ds.RescaleSlope)
        assert float(output_ds.RescaleIntercept) == float(source_ds.RescaleIntercept)
        assert int(output_ds.BitsStored) == int(source_ds.BitsStored)
        if "WindowCenter" in source_ds:
            assert output_ds.WindowCenter == source_ds.WindowCenter
            assert output_ds.WindowWidth == source_ds.WindowWidth

    hu_source = load_hu_stack(slice_paths)
    hu_output = load_hu_stack(tuple(output_dir / path.name for path in slice_paths))
    assert np.allclose(hu_output, hu_source, atol=1.0)


def test_write_blurred_dicom_series_no_charset_warning(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    source_dir.mkdir()
    slice_path = source_dir / "slice_001.dcm"
    _write_template_slice(slice_path, hu_value=0.0, instance_number=1)

    hu = load_hu_stack((slice_path,))
    mask = np.zeros(hu.shape, dtype=bool)
    mask[:, 20:40, 20:40] = True
    hu = blur_face_hu_volume(hu, mask, sigma_mm=4.0, pixel_spacing_mm=(1.0, 1.0))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        write_blurred_dicom_series(hu, (slice_path,), tmp_path / "out")

    charset_warnings = [item for item in caught if "encode value with encodings" in str(item.message).lower()]
    assert not charset_warnings
