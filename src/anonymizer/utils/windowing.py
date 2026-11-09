"""Apply window level / width to in-memory frames for display and OCR.

Public API
----------
apply_windowing(wl: float, ww: float, image_array_raw: ndarray) -> NDArray[np.uint8]
    Apply WL/WW to a series-buffer frame and return uint8 BGR for display or OCR.

auto_window_from_pixels(pixels: ndarray, *, low_percentile: float = 1.0, high_percentile: float = 99.0) -> tuple[float, float]
    WL/WW from intensity percentiles of a frame or volume (for missing DICOM VOI tags).

resolve_default_window(ds: Dataset, pixels: ndarray | None = None) -> tuple[float, float]
    Prefer DICOM Window Center/Width; else pixel percentiles; else BitsAllocated fallback.

safe_window_width(ww: float) -> float
    Positive WW floor (epsilon only) so PET modality-LUT windows may be << 1.

wl_ww_drag_units_per_pixel(ww: float, *, reference_pixels: float = 256.0) -> float
    Intensity units changed per mouse pixel when dragging WW/WL on the image.

MIN_WINDOW_WIDTH
    Epsilon floor for window width (not 1.0 — that blanks rescaled PET).
"""
import logging

import numpy as np
from cv2 import COLOR_GRAY2BGR, COLOR_RGBA2BGR, convertScaleAbs, cvtColor
from numpy import ndarray
from numpy.typing import NDArray
from pydicom.dataset import Dataset

from anonymizer.utils.dicom import get_wl_ww, has_voi_window

logger = logging.getLogger(__name__)

# Cap samples so full PET volumes stay interactive for Auto window / load defaults.
_AUTO_WINDOW_MAX_SAMPLES = 2_000_000
# Dragging this many pixels should change WW by about the current WW.
WLWW_DRAG_REFERENCE_PIXELS = 256.0
# Avoid divide-by-zero only. PET after RescaleSlope often needs WW << 1.
MIN_WINDOW_WIDTH = 1e-12


def safe_window_width(ww: float) -> float:
    """Clamp window width to a positive epsilon (allows PET WW << 1).

    Args:
        ww: Requested window width.

    Returns:
        Positive window width suitable for display math.
    """
    return max(MIN_WINDOW_WIDTH, abs(float(ww)))


def auto_window_from_pixels(
    pixels: ndarray,
    *,
    low_percentile: float = 1.0,
    high_percentile: float = 99.0,
) -> tuple[float, float]:
    """WL/WW from intensity percentiles of a frame or volume.

    Args:
        pixels: Frame (H,W) / (H,W,C) or stack (N,H,W) / (N,H,W,C).
        low_percentile: Lower intensity percentile for the window floor.
        high_percentile: Upper intensity percentile for the window ceiling.

    Returns:
        (window_level, window_width) with width at least MIN_WINDOW_WIDTH.
    """
    arr = np.asarray(pixels)
    if arr.size == 0:
        return 127.5, 255.0

    # Display buffer may be RGB/RGBA; use first channel (matches histogram gray path).
    sample = arr[..., 0] if arr.ndim >= 3 and arr.shape[-1] in (3, 4) else arr

    flat = sample.astype(np.float64, copy=False).ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        return 127.5, 255.0
    if finite.size > _AUTO_WINDOW_MAX_SAMPLES:
        step = max(1, finite.size // _AUTO_WINDOW_MAX_SAMPLES)
        finite = finite[::step]

    lo = float(np.percentile(finite, low_percentile))
    hi = float(np.percentile(finite, high_percentile))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        mid = lo if np.isfinite(lo) else 0.0
        return mid, safe_window_width(1.0 if mid == 0.0 else abs(mid) * 1e-3)
    return (lo + hi) / 2.0, safe_window_width(hi - lo)


def resolve_default_window(
    ds: Dataset,
    pixels: ndarray | None = None,
) -> tuple[float, float]:
    """Prefer DICOM VOI window tags; else pixel percentiles; else BitsAllocated.

    Args:
        ds: Dataset that may carry WindowCenter / WindowWidth.
        pixels: Optional loaded frames used when VOI tags are absent.

    Returns:
        (window_level, window_width).
    """
    if has_voi_window(ds):
        return get_wl_ww(ds)
    if pixels is not None and np.asarray(pixels).size > 0:
        return auto_window_from_pixels(pixels)
    return get_wl_ww(ds)


def wl_ww_drag_units_per_pixel(
    ww: float,
    *,
    reference_pixels: float = WLWW_DRAG_REFERENCE_PIXELS,
) -> float:
    """Intensity units changed per mouse pixel when dragging image WW/WL.

    Scales with current WW so ~reference_pixels of drag changes WW by about
    one window width. Must not use a 1/ref floor — that dominates PET
    modality-LUT windows (WW ~1e-4) and jumps WL/WW outside the data in one
    pixel, blanking the image.

    Args:
        ww: Current window width at drag start.
        reference_pixels: Mouse travel that should change WW by about ``ww``.

    Returns:
        Positive units-per-pixel scale.
    """
    ref = max(1.0, float(reference_pixels))
    return safe_window_width(ww) / ref


def apply_windowing(
    wl: float, ww: float, image_array_raw: ndarray
) -> NDArray[np.uint8]:
    """Apply WL/WW to a series-buffer frame and return uint8 BGR for display or OCR."""
    try:
        current_dtype = image_array_raw.dtype
        current_ndim = image_array_raw.ndim
        num_channels = image_array_raw.shape[-1] if current_ndim == 3 else 1
        image_height, image_width = image_array_raw.shape[:2]
        logger.debug(
            "apply_windowing: %s dtype=%s", image_array_raw.shape, current_dtype
        )

        is_high_bit_gray = (current_ndim == 2 and current_dtype != np.uint8) or (
            current_ndim == 3 and num_channels == 1 and current_dtype != np.uint8
        )

        if is_high_bit_gray:
            logger.debug("Applying true WW/WL: WL=%.1f, WW=%.1f", wl, ww)
            img_to_process = (
                image_array_raw.squeeze() if current_ndim == 3 else image_array_raw
            )
            ww_safe = safe_window_width(ww)
            min_val = float(wl) - ww_safe / 2.0
            image_float = img_to_process.astype(np.float32)
            output_float = ((image_float - min_val) / ww_safe) * 255.0
            output_clipped = np.clip(output_float, 0, 255)
            output_uint8_gray = output_clipped.astype(np.uint8)
            image_processed_bgr = cvtColor(output_uint8_gray, COLOR_GRAY2BGR)
        else:
            logger.debug("Applying simulated WW/WL (alpha/beta) for uint8 input")
            if current_ndim == 2 and current_dtype == np.uint8:
                image_color = cvtColor(image_array_raw, COLOR_GRAY2BGR)
            elif (
                current_ndim == 3
                and image_array_raw.shape[-1] == 4
                and current_dtype == np.uint8
            ):
                image_color = cvtColor(image_array_raw, COLOR_RGBA2BGR)
            elif (
                current_ndim == 3
                and image_array_raw.shape[-1] == 3
                and current_dtype == np.uint8
            ):
                image_color = image_array_raw
            else:
                logger.error(
                    "Cannot apply alpha/beta to unexpected uint8 format: Shape=%s, Dtype=%s",
                    image_array_raw.shape,
                    current_dtype,
                )
                return np.zeros((image_height, image_width, 3), dtype=np.uint8)

            ww_safe = safe_window_width(ww)
            derived_alpha = 255.0 / ww_safe
            derived_beta = int(127.5 - (derived_alpha * wl))
            if derived_alpha != 1.0 or derived_beta != 0:
                image_processed_bgr = convertScaleAbs(
                    image_color, alpha=derived_alpha, beta=derived_beta
                )
            else:
                image_processed_bgr = image_color

        return image_processed_bgr.astype(np.uint8)

    except Exception as exc:
        logger.exception(
            "Error applying windowing to frame with shape %s dtype %s: %s",
            image_array_raw.shape,
            current_dtype,
            exc,
        )
        return np.zeros((image_height, image_width, 3), dtype=np.uint8)
