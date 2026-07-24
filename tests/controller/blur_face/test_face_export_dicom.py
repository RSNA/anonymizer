"""Tests for blurred face DICOM export."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from pydicom.data import get_testdata_file

from anonymizer.controller.blur_face import blur_face_hu_volume, load_hu_stack, write_blurred_dicom_series


def _write_template_slice(path: Path, *, hu_value: float, instance_number: int) -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    stored = np.full(ds.pixel_array.shape, hu_value, dtype=np.float64)
    stored = (stored - float(ds.RescaleIntercept)) / float(ds.RescaleSlope)
    ds.PixelData = stored.astype(ds.pixel_array.dtype).tobytes()
    ds.InstanceNumber = instance_number
    ds.SOPInstanceUID = pydicom.uid.generate_uid()
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

    reloaded = load_hu_stack(written_paths)
    assert reloaded.shape == hu_after.shape
    assert np.allclose(reloaded, hu_after, atol=1.0)
    assert np.allclose(reloaded[~mask], hu_before[~mask], atol=1.0)
