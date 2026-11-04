"""OCR frame prep: DICOM / series buffers → EasyOCR input pixels.

Detection, annotate, and match mode live in ocr_pipeline / whitelist_io.

Public API
----------
ocr_image_for_frame(ds: Dataset, frame: np.ndarray) -> NDArray[np.uint8]
    Apply DICOM WL/WW to a processed frame for EasyOCR (Series View and batch).

build_series_view_ocr_pixels(images: np.ndarray, ds: Dataset) -> NDArray[np.uint8]
    Snapshot per-frame EasyOCR inputs for Series View (DICOM WL only; no viewer WL).
"""
import logging

import numpy as np
from cv2 import COLOR_RGB2BGR, cvtColor
from numpy.typing import NDArray
from pydicom import Dataset

from anonymizer.utils.dicom import get_wl_ww
from anonymizer.utils.windowing import apply_windowing

logger = logging.getLogger(__name__)


def ocr_image_for_frame(ds: Dataset, frame: np.ndarray) -> NDArray[np.uint8]:
    """
    Apply DICOM WL/WW to a processed frame for EasyOCR (Series View and batch).

    Args:
        ds: Source DICOM dataset (WL/WW / photometric).
        frame: Processed frame pixels.

    Returns:
        uint8 image suitable for EasyOCR.
    """
    pi = str(ds.get("PhotometricInterpretation", "") or "").upper()
    if frame.ndim == 3 and frame.shape[-1] == 3 and frame.dtype == np.uint8 and pi == "RGB":
        logger.debug(f"ocr_image_for_frame RGB uint8 -> BGR for EasyOCR frame_shape={frame.shape}")
        return cvtColor(np.ascontiguousarray(frame), COLOR_RGB2BGR)

    wl, ww = get_wl_ww(ds)
    logger.debug(f"ocr_image_for_frame wl={wl:.1f} ww={ww:.1f} frame_shape={frame.shape}")
    return apply_windowing(wl, ww, frame)


def build_series_view_ocr_pixels(images: np.ndarray, ds: Dataset) -> NDArray[np.uint8]:
    """
    Snapshot per-frame EasyOCR inputs for Series View (DICOM WL only; no viewer WL).

    Args:
        images: Stack of processed frames.
        ds: Source DICOM dataset.

    Returns:
        Stack of EasyOCR input frames.
    """
    return np.stack([ocr_image_for_frame(ds, frame) for frame in images])
