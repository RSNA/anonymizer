"""Apply window level / width to in-memory frames for display and OCR."""

from __future__ import annotations

import logging

import numpy as np
from cv2 import COLOR_GRAY2BGR, COLOR_RGBA2BGR, convertScaleAbs, cvtColor
from numpy import ndarray
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

__all__ = ["apply_windowing"]


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
            min_val = float(wl) - float(ww) / 2.0
            image_float = img_to_process.astype(np.float32)
            ww_safe = max(1.0, float(ww))
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

            ww_safe = max(1.0, ww)
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
