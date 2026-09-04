from __future__ import annotations

import numpy as np


def window_hu_to_uint8(hu: np.ndarray, window_center: float, window_width: float) -> np.ndarray:
    low = window_center - window_width / 2.0
    high = window_center + window_width / 2.0
    if high <= low:
        high = low + 1.0
    scaled = (hu.astype(np.float64) - low) / (high - low) * 255.0
    return np.clip(scaled, 0, 255).astype(np.uint8)


def auto_window_from_mask(
    hu: np.ndarray,
    mask2d: np.ndarray,
    *,
    low_percentile: float = 2.0,
    high_percentile: float = 98.0,
    min_width: float = 80.0,
) -> tuple[float, float]:
    """Window center/width from masked HU percentiles (shared before/after display)."""
    values = hu[mask2d.astype(bool)]
    if values.size == 0:
        return 40.0, 400.0
    low = float(np.percentile(values, low_percentile))
    high = float(np.percentile(values, high_percentile))
    if high <= low:
        high = low + min_width
    width = max(high - low, min_width)
    center = (high + low) / 2.0
    return center, width


# Standard CT soft-tissue preset (skin / muscle / fat; bone may clip).
SOFT_TISSUE_WINDOW_CENTER = 40.0
SOFT_TISSUE_WINDOW_WIDTH = 400.0


def soft_tissue_window() -> tuple[float, float]:
    return SOFT_TISSUE_WINDOW_CENTER, SOFT_TISSUE_WINDOW_WIDTH
