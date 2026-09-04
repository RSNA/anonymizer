"""Tests that batch OCR uses the same preprocessing as Series View Detect Text."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pydicom
from pydicom.data import get_testdata_file

from anonymizer.controller.ai.remove_pixel_phi import _ocr_bgr_from_stored_monochrome, remove_pixel_phi
from anonymizer.controller.series_io import stored_monochrome_to_series_buffer
from anonymizer.utils.dicom import get_wl_ww
from anonymizer.utils.windowing import apply_windowing


def test_ocr_bgr_from_stored_monochrome_matches_detect_text_pipeline() -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    stored = ds.pixel_array.copy()

    viewer_pixels, _ = stored_monochrome_to_series_buffer(stored, ds)
    wl, ww = get_wl_ww(ds)
    expected = apply_windowing(wl, ww, viewer_pixels)

    actual = _ocr_bgr_from_stored_monochrome(stored, ds)

    assert actual.shape == expected.shape
    assert actual.dtype == expected.dtype
    assert np.array_equal(actual, expected)


@patch("anonymizer.controller.ai.remove_pixel_phi._ocr_bgr_from_stored_monochrome")
@patch("anonymizer.controller.ai.remove_pixel_phi.dcmread")
@patch("anonymizer.controller.ai.remove_pixel_phi._easyocr_readtext")
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
