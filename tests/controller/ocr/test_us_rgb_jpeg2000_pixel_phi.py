"""Compressed RGB US pixel PHI: JPEG2000 re-encode and color preservation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from cv2 import dilate
from pydicom import dcmread
from pydicom.uid import JPEG2000Lossless
from openjpeg.utils import decode

from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    _draw_text_contours_on_mask,
    _encode_decompressed_frame_for_save,
    ocr_image_for_frame,
    remove_pixel_phi,
)
from anonymizer.controller.series_overlay import OCRText
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.support.us_rgb_fixtures import US_RGB_DCM, make_jpeg2000_rgb_dicom

_FAKE_OCR = [
    OCRText(text="TEST", top_left=(100, 100), bottom_right=(200, 140), prob=0.99),
]


def _blackout_exclusion_mask(shape: tuple[int, int]) -> np.ndarray:
    mask = np.ones(shape, dtype=bool)
    for ocr_text in _FAKE_OCR:
        x1, y1 = ocr_text.top_left
        x2, y2 = ocr_text.bottom_right
        mask[y1:y2, x1:x2] = False
    return mask


def _dilated_inpaint_mask(ds, frame_pixels: np.ndarray) -> np.ndarray:
    ocr_frame = ocr_image_for_frame(ds, frame_pixels)
    mask = np.zeros(frame_pixels.shape[:2], dtype=np.uint8)
    for ocr_text in _FAKE_OCR:
        _draw_text_contours_on_mask(
            ocr_frame,
            ocr_text.top_left,
            ocr_text.bottom_right,
            mask,
            is_bgr=True,
        )
    kernel = np.ones((3, 3), np.uint8)
    return dilate(src=mask, kernel=kernel, iterations=1)


def test_encode_decompressed_frame_preserves_rgb_channels(tmp_path: Path) -> None:
    assert_dcm(US_RGB_DCM)
    dcm_path = make_jpeg2000_rgb_dicom(tmp_path / "compressed.dcm")
    ds = dcmread(dcm_path)
    frame = ds.pixel_array.copy()

    encoded = _encode_decompressed_frame_for_save(
        frame,
        ds=ds,
        grayscale=False,
        pi="RGB",
    )
    decoded = decode(encoded, j2k_format=0, reshape=True)
    np.testing.assert_array_equal(decoded, frame)


def test_remove_pixel_phi_blackout_compressed_preserves_color_outside_mask(
    tmp_path: Path,
) -> None:
    assert_dcm(US_RGB_DCM)
    dcm_path = make_jpeg2000_rgb_dicom(tmp_path / "compressed.dcm")
    before = dcmread(dcm_path).pixel_array.copy()
    rows, cols = int(dcmread(dcm_path).Rows), int(dcmread(dcm_path).Columns)

    reader = MagicMock()
    with patch("anonymizer.controller.ai.remove_pixel_phi.detect_text", return_value=_FAKE_OCR):
        modified, texts, changed = remove_pixel_phi(
            dcm_path,
            reader,
            removal_mode=PixelPhiRemovalMode.BLACKOUT,
        )

    assert modified is True
    assert texts == ["TEST"]
    assert changed > 0

    ds = dcmread(dcm_path)
    assert ds.file_meta.TransferSyntaxUID == JPEG2000Lossless
    assert (int(ds.Rows), int(ds.Columns)) == (rows, cols)
    after = ds.pixel_array
    assert after.shape == before.shape

    outside = _blackout_exclusion_mask(before.shape[:2])
    np.testing.assert_array_equal(after[outside], before[outside])


def test_remove_pixel_phi_inpaint_compressed_preserves_color_outside_mask(
    tmp_path: Path,
) -> None:
    assert_dcm(US_RGB_DCM)
    dcm_path = make_jpeg2000_rgb_dicom(tmp_path / "compressed.dcm")
    ds_before = dcmread(dcm_path)
    before = ds_before.pixel_array.copy()

    reader = MagicMock()
    with patch("anonymizer.controller.ai.remove_pixel_phi.detect_text", return_value=_FAKE_OCR):
        modified, _, _ = remove_pixel_phi(
            dcm_path,
            reader,
            removal_mode=PixelPhiRemovalMode.INPAINT,
        )

    assert modified is True
    ds = dcmread(dcm_path)
    after = ds.pixel_array
    dilated_mask = _dilated_inpaint_mask(ds_before, before)
    outside = dilated_mask == 0
    assert after[outside].size > 0
    assert np.abs(before[outside].astype(int) - after[outside].astype(int)).max() == 0
