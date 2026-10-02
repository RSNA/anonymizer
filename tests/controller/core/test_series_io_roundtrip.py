"""Functional series_io load/save/description roundtrips (real DICOM)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydicom import dcmread
from pydicom.data import get_testdata_file

from anonymizer.controller.series_io import (
    apply_series_description,
    apply_study_description,
    load_series_frames,
    ordered_series_dcm_paths,
    save_series_frames,
)
from tests.controller.tseg.support.synthetic_ct import build_synthetic_ct_small_series


def test_load_save_synthetic_ct_roundtrip(tmp_path: Path) -> None:
    series_dir = build_synthetic_ct_small_series(tmp_path / "ct_series", num_slices=11)
    loaded = load_series_frames(series_dir)
    assert loaded.frames.ndim == 3
    assert loaded.frames.shape[0] == 11
    assert len(loaded.slice_paths) == 11

    frames = loaded.frames.copy()
    frames[0, 0, 0] = float(frames[0, 0, 0]) + 1.0
    assert save_series_frames(series_dir, frames, loaded.metadata) is True
    reloaded = load_series_frames(series_dir)
    assert reloaded.frames.shape == loaded.frames.shape


def test_ordered_series_dcm_paths_and_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="No DICOM files"):
        ordered_series_dcm_paths(empty)

    series_dir = build_synthetic_ct_small_series(tmp_path / "ct2", num_slices=11)
    paths = ordered_series_dcm_paths(series_dir)
    assert len(paths) == 11
    assert all(p.suffix.lower() == ".dcm" for p in paths)


def test_load_series_frames_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "no_such_series"
    with pytest.raises((FileNotFoundError, OSError, ValueError, RuntimeError)):
        load_series_frames(missing)


def test_apply_series_and_study_description_on_synthetic(tmp_path: Path) -> None:
    series_dir = build_synthetic_ct_small_series(tmp_path / "patient" / "study" / "series", num_slices=11)
    study_path = series_dir.parent

    assert apply_series_description(series_dir, "Harmonized Series Desc") is True
    ds = dcmread(next(series_dir.glob("*.dcm")), stop_before_pixels=True)
    assert str(ds.SeriesDescription) == "Harmonized Series Desc"

    assert apply_study_description(study_path, "Harmonized Study Desc") is True
    ds2 = dcmread(next(series_dir.glob("*.dcm")), stop_before_pixels=True)
    assert str(ds2.StudyDescription) == "Harmonized Study Desc"


def test_load_monochrome_testdata_fixture(tmp_path: Path) -> None:
    """Load a single-frame pydicom testdata file via series_io."""
    src = get_testdata_file("CT_small.dcm")
    assert src
    series_dir = tmp_path / "mono"
    series_dir.mkdir()
    import shutil

    shutil.copy(src, series_dir / "1.dcm")
    loaded = load_series_frames(series_dir)
    assert loaded.frames.ndim >= 2
    assert len(loaded.slice_paths) == 1
