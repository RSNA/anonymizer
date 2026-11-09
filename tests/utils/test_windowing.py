"""Tests for utils.windowing.apply_windowing and auto-window helpers."""

import numpy as np
from pydicom.dataset import Dataset

from anonymizer.utils.windowing import (
    apply_windowing,
    auto_window_from_pixels,
    resolve_default_window,
    safe_window_width,
    wl_ww_drag_units_per_pixel,
)


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


def test_auto_window_from_pixels_uses_percentiles() -> None:
    # Mostly low values with a sparse high tail — mimics PET-style skew.
    frame = np.full((64, 64), 10.0, dtype=np.float32)
    frame[0, 0] = 10000.0
    wl, ww = auto_window_from_pixels(frame, low_percentile=1.0, high_percentile=99.0)
    assert ww < 5000.0
    assert 0.0 <= wl <= 100.0
    assert ww > 0.0


def test_auto_window_from_pixels_constant_image() -> None:
    frame = np.full((8, 8), 42.0, dtype=np.float32)
    wl, ww = auto_window_from_pixels(frame)
    assert wl == 42.0
    assert ww == safe_window_width(42.0 * 1e-3)


def test_auto_window_and_apply_preserve_pet_modality_contrast() -> None:
    """Rescaled PET floats need WW << 1; flooring to 1.0 blanks the image."""
    # Mimic Discovery PET after RescaleSlope ~3e-8.
    frame = np.linspace(0.0, 9.7e-4, 64 * 64, dtype=np.float32).reshape(64, 64)
    wl, ww = auto_window_from_pixels(frame)
    assert ww < 1.0
    assert ww > 1e-6
    out = apply_windowing(wl, ww, frame)
    assert out.max() > 200
    assert out.min() < 50
    assert len(np.unique(out[..., 0])) > 50


def test_resolve_default_window_prefers_dicom_voi_tags() -> None:
    ds = Dataset()
    ds.BitsAllocated = 16
    ds.WindowCenter = 40
    ds.WindowWidth = 400
    pixels = np.full((16, 16), 10.0, dtype=np.float32)
    wl, ww = resolve_default_window(ds, pixels)
    assert wl == 40.0
    assert ww == 400.0


def test_resolve_default_window_uses_pixels_when_voi_missing() -> None:
    ds = Dataset()
    ds.BitsAllocated = 16
    pixels = np.linspace(0.0, 100.0, 256, dtype=np.float32).reshape(16, 16)
    wl, ww = resolve_default_window(ds, pixels)
    # Must not fall back to full 16-bit range.
    assert ww < 1000.0
    assert 0.0 <= wl <= 100.0


def test_resolve_default_window_bits_fallback_without_pixels() -> None:
    ds = Dataset()
    ds.BitsAllocated = 16
    wl, ww = resolve_default_window(ds, None)
    assert wl == 32768.0
    assert ww == 65535.0


def test_wl_ww_drag_units_scale_with_window_width() -> None:
    narrow = wl_ww_drag_units_per_pixel(256.0)
    wide = wl_ww_drag_units_per_pixel(65535.0)
    assert abs(narrow - 1.0) < 1e-9
    assert wide > narrow * 100
    assert wide > 200.0


def test_wl_ww_drag_units_scale_with_pet_sub_unit_window() -> None:
    """PET WW ~1e-4 must not use a 1/256 floor (that blanks on first mouse move)."""
    pet_ww = 0.00077
    units = wl_ww_drag_units_per_pixel(pet_ww)
    assert units == pet_ww / 256.0
    # One pixel of drag stays well inside the PET data span (~1e-3).
    assert units < 1e-5


def test_safe_window_width_allows_sub_unit() -> None:
    assert safe_window_width(0.0008) == 0.0008
    assert safe_window_width(0.0) == 1e-12
