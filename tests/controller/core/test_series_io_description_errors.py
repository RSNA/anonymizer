"""Error / skip paths for apply_series_description and apply_study_description."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.series.series_io import (
    apply_series_description,
    apply_study_description,
)


def _write_minimal_series(series_dir: Path, *, with_pixel_data: bool = True) -> Path:
    series_dir.mkdir(parents=True, exist_ok=True)
    path = series_dir / "1.dcm"
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = file_meta
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.Modality = "CT"
    ds.SeriesDescription = "SCOUT"
    ds.StudyDescription = "STUDY"
    ds.Rows = 8
    ds.Columns = 8
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    if with_pixel_data:
        ds.PixelData = np.zeros((8, 8), dtype=np.uint16).tobytes()
    ds.save_as(path, enforce_file_format=True)
    return path


def test_apply_series_empty_dir(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    series.mkdir()
    assert apply_series_description(series, "CT Chest") is False


def test_apply_series_no_pixeldata_skips_without_failing(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _write_minimal_series(series, with_pixel_data=False)
    # No PixelData → skip; success stays True when nothing else fails.
    assert apply_series_description(series, "CT Chest") is True


def test_apply_series_save_as_fail(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _write_minimal_series(series)
    with patch.object(Dataset, "save_as", side_effect=OSError("boom")):
        assert apply_series_description(series, "CT Chest") is False


def test_apply_study_only_empty_series_dirs(tmp_path: Path) -> None:
    study = tmp_path / "study"
    (study / "ser1").mkdir(parents=True)
    (study / "ser2").mkdir()
    assert apply_study_description(study, "CT Chest") is False
