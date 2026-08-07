"""Tests for MONOCHROME1/MONOCHROME2 blackout alignment with Series View pixels."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pydicom
from pydicom.data import get_testdata_file

from anonymizer.controller.remove_pixel_phi import (
    PixelPhiRemovalMode,
    UserRectangle,
    blackout_rectangular_areas,
    remove_pixel_phi,
)
from anonymizer.controller.series_io import (
    series_buffer_monochrome_to_stored,
    stored_monochrome_to_series_buffer,
)


def _monochrome1_dataset() -> pydicom.Dataset:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    ds.PhotometricInterpretation = "MONOCHROME1"
    stored = ds.pixel_array.copy()
    stored[:] = 50
    stored[30:50, 30:50] = 2000
    ds.PixelData = stored.tobytes()
    return ds


def test_monochrome1_blackout_uses_viewer_space_not_stored_zero() -> None:
    ds = _monochrome1_dataset()
    stored = ds.pixel_array.copy()

    viewer, mono1_invert_max = stored_monochrome_to_series_buffer(stored, ds)
    viewer = viewer.copy()
    blackout_rectangular_areas(
        viewer,
        [UserRectangle(top_left=(35, 35), bottom_right=(45, 45))],
    )
    out = series_buffer_monochrome_to_stored(viewer, ds, mono1_invert_max=mono1_invert_max)

    assert out[40, 40] > 1500
    assert out[0, 0] == 50


@patch("anonymizer.controller.remove_pixel_phi.dcmread")
@patch("anonymizer.controller.remove_pixel_phi._easyocr_readtext")
def test_remove_pixel_phi_blackout_monochrome1_writes_dark_pixels(
    mock_readtext: MagicMock,
    mock_dcmread: MagicMock,
    tmp_path: Path,
) -> None:
    ds = _monochrome1_dataset()
    dcm_path = tmp_path / "cxr.dcm"
    ds.save_as(dcm_path)
    mock_dcmread.return_value = pydicom.dcmread(dcm_path)

    mock_readtext.return_value = [
        ([(30, 30), (50, 30), (50, 50), (30, 50)], "PATIENT PHI", 0.95),
    ]

    modified, texts, pixels_changed = remove_pixel_phi(
        dcm_path,
        MagicMock(),
        whitelist=[],
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
        border_size=0,
        downscale_dimension_threshold=10_000,
    )

    assert modified is True
    assert texts == ["PATIENT PHI"]
    assert pixels_changed > 0

    after = pydicom.dcmread(dcm_path).pixel_array
    assert after[40, 40] > 1500
    assert after[0, 0] == 50
