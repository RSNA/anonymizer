"""Asset-DICOM series_io roundtrips using checked-in fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

from pydicom import dcmread

from anonymizer.controller import series_io
from tests.controller.ocr.conftest import assert_dcm, assert_dcm_dir
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR
from tests.controller.support.us_rgb_fixtures import US_RGB_DCM

DAVIDSON_CXR_SERIES_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "davidson_cxr"


def test_save_series_frames_rgb_preserves_rows_columns_bug_report_dims(tmp_path: Path) -> None:
    """Regression for US RGB metadata swap (Rows=width, Columns=3)."""
    import numpy as np

    assert_dcm(US_RGB_DCM)
    shutil.copy(US_RGB_DCM, tmp_path / "slice.dcm")
    loaded = series_io.load_series_frames(tmp_path)
    rows, cols = 852, 1136
    resized = np.zeros((1, rows, cols, 3), dtype=np.uint8)
    resized[0] = np.array(
        [np.linspace(0, 255, cols, dtype=np.uint8)] * rows,
        dtype=np.uint8,
    ).reshape(rows, cols, 1)
    resized[0, :, :, 1] = 128
    resized[0, :, :, 2] = 64

    assert series_io.save_series_frames(tmp_path, resized, loaded.metadata)

    ds = dcmread(str(tmp_path / "slice.dcm"))
    assert (int(ds.Rows), int(ds.Columns)) == (rows, cols)
    assert ds.pixel_array.shape == (rows, cols, 3)


def test_save_series_frames_rgb_preserves_rows_columns(tmp_path: Path) -> None:
    assert_dcm(US_RGB_DCM)
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


def test_save_series_frames_monochrome1_roundtrip_preserves_viewer(tmp_path: Path) -> None:
    import numpy as np

    assert_dcm_dir(DAVIDSON_CXR_SERIES_DIR)
    series_dir = tmp_path / "davidson"
    shutil.copytree(DAVIDSON_CXR_SERIES_DIR, series_dir)
    dcm_path = next(iter(series_dir.glob("*.dcm")))
    stored_before = dcmread(dcm_path).pixel_array.copy()

    loaded = series_io.load_series_frames(series_dir)
    assert str(loaded.metadata.PhotometricInterpretation).upper() == "MONOCHROME1"

    assert series_io.save_series_frames(series_dir, loaded.frames.copy(), loaded.metadata)

    reloaded = series_io.load_series_frames(series_dir)
    np.testing.assert_allclose(reloaded.frames, loaded.frames, rtol=1e-4, atol=1.0)
    stored_after = dcmread(dcm_path).pixel_array
    np.testing.assert_array_equal(stored_before, stored_after)
