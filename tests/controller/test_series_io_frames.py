"""Tests for load_series_frames naming and LoadedSeries.frames."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom import dcmread
from pydicom.data import get_testdata_file

from anonymizer.controller import series_io
from tests.controller.support.us_rgb_fixtures import US_RGB_DCM


def test_loaded_series_exposes_frames_field() -> None:
    import dataclasses

    names = {f.name for f in dataclasses.fields(series_io.LoadedSeries)}
    assert "frames" in names
    assert "slices" not in names


def test_load_series_frames_and_save_roundtrip(tmp_path: Path) -> None:
    source = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    dcm_path = tmp_path / "slice.dcm"
    source.save_as(dcm_path)
    loaded = series_io.load_series_frames(tmp_path)
    assert loaded.frames.shape[0] >= 1
    assert loaded.frames.dtype == np.float32
    assert series_io.save_series_frames(tmp_path, loaded.frames, loaded.metadata)


@pytest.mark.skipif(not US_RGB_DCM.is_file(), reason="US RGB single-frame fixture missing")
def test_save_series_frames_rgb_preserves_rows_columns(tmp_path: Path) -> None:
    shutil.copy(US_RGB_DCM, tmp_path / "slice.dcm")
    loaded = series_io.load_series_frames(tmp_path)
    assert loaded.frames.shape == (1, 600, 800, 3)

    edited = loaded.frames.copy()
    edited[0, 10:20, 10:20, :] = 0
    assert series_io.save_series_frames(tmp_path, edited, loaded.metadata)

    ds = dcmread(str(tmp_path / "slice.dcm"))
    assert (int(ds.Rows), int(ds.Columns)) == (600, 800)
    assert ds.pixel_array.shape == (600, 800, 3)
    assert ds.pixel_array[10:20, 10:20, :].max() == 0
    assert ds.pixel_array.max() > 0
