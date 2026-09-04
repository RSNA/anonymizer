"""Tests for utils.windowing.apply_windowing."""

from __future__ import annotations

import numpy as np

from anonymizer.utils.windowing import apply_windowing


def test_apply_windowing_float_mono_produces_bgr_uint8() -> None:
    frame = np.full((64, 64), 1000.0, dtype=np.float32)
    result = apply_windowing(1000.0, 2000.0, frame)
    assert result.shape == (64, 64, 3)
    assert result.dtype == np.uint8


def test_apply_windowing_uint8_rgb_preserves_shape() -> None:
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    result = apply_windowing(127.5, 255.0, frame)
    assert result.shape == (32, 32, 3)
    assert result.dtype == np.uint8
