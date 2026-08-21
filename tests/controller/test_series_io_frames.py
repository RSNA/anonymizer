"""Tests for load_series_frames naming and LoadedSeries.frames."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from pydicom.data import get_testdata_file

from anonymizer.controller import series_io


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
