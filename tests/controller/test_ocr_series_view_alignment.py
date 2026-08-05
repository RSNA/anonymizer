"""Tests that batch OCR uses the same preprocessing as Series View Detect Text."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pydicom
from pydicom.data import get_testdata_file

from anonymizer.controller.create_projections import (
    apply_windowing,
    get_wl_ww,
    prepare_series_view_ocr_frame,
    stored_grayscale_frame_to_viewer_pixels,
)
from anonymizer.controller.remove_pixel_phi import remove_pixel_phi


def test_prepare_series_view_ocr_frame_matches_detect_text_pipeline() -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    stored = ds.pixel_array.copy()

    viewer_pixels, _ = stored_grayscale_frame_to_viewer_pixels(stored, ds)
    wl, ww = get_wl_ww(ds)
    expected = apply_windowing(wl, ww, viewer_pixels)

    actual = prepare_series_view_ocr_frame(stored, ds)

    assert actual.shape == expected.shape
    assert actual.dtype == expected.dtype
    assert np.array_equal(actual, expected)


@patch("anonymizer.controller.create_projections.prepare_series_view_ocr_frame")
@patch("anonymizer.controller.remove_pixel_phi.dcmread")
@patch("anonymizer.controller.remove_pixel_phi._easyocr_readtext")
def test_remove_pixel_phi_grayscale_uses_series_view_ocr_frame(
    mock_readtext: MagicMock,
    mock_dcmread: MagicMock,
    mock_prepare: MagicMock,
) -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    mock_dcmread.return_value = ds
    mock_prepare.return_value = np.zeros((ds.Rows, ds.Columns, 3), dtype=np.uint8)
    mock_readtext.return_value = []

    remove_pixel_phi(
        __import__("pathlib").Path("/tmp/test.dcm"),
        MagicMock(),
        whitelist=[],
    )

    mock_prepare.assert_called_once()
    call_frame = mock_prepare.call_args[0][0]
    assert call_frame.shape == ds.pixel_array.shape
