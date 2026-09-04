"""Tests for Series View OCR text removal helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    remove_ocr_text_from_frame,
)
from anonymizer.controller.series_overlay import OCRText


def _ocr_texts() -> list[OCRText]:
    return [OCRText(text="PHI", top_left=(2, 2), bottom_right=(5, 5), prob=0.9)]


def test_remove_ocr_text_from_frame_blackout_zeros_boxes() -> None:
    raw = np.full((8, 8), 100, dtype=np.uint8)
    windowed = raw.copy()
    texts = _ocr_texts()
    result = remove_ocr_text_from_frame(
        raw,
        windowed,
        texts,
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )
    assert result is not raw
    assert result[2:5, 2:5].max() == 0
    assert result[0, 0] == 100
    assert raw[2:5, 2:5].max() == 100


@patch("anonymizer.controller.ai.remove_pixel_phi.remove_text")
def test_remove_ocr_text_from_frame_inpaint_calls_remove_text(mock_remove_text: MagicMock) -> None:
    raw = np.full((8, 8), 100, dtype=np.uint8)
    windowed = raw.copy()
    texts = _ocr_texts()
    inpainted = np.full((8, 8), 50, dtype=np.uint8)
    mock_remove_text.return_value = inpainted

    result = remove_ocr_text_from_frame(
        raw,
        windowed,
        texts,
        removal_mode=PixelPhiRemovalMode.INPAINT,
    )

    mock_remove_text.assert_called_once_with(raw, windowed, texts)
    assert result is inpainted
