"""CXR-specific preprocess helpers; reuse xp_bodypart pad/normalize.

Public API
----------
upright_array(pixels: np.ndarray, rotation_label: str) -> np.ndarray
    Return a copy of pixels rotated so the radiograph is upright.
"""
import numpy as np

from anonymizer.controller.ai.harmonize.xp_bodypart.preprocess import (
    uint8_grayscale_from_array,
)
from anonymizer.controller.ai.harmonize.xr_chest_view.labels import normalize_rotation_label


def upright_array(pixels: np.ndarray, rotation_label: str) -> np.ndarray:
    """Return a copy of pixels rotated so the radiograph is upright.

    Applies the inverse of the predicted presentation rotation:
    Inverted → 180°, Left-rotation → +90° CW (np.rot90 k=-1),
    Right-rotation → -90° CW (np.rot90 k=1).
    """
    gray = uint8_grayscale_from_array(pixels)
    label = normalize_rotation_label(rotation_label)
    if label == "Upright":
        return gray
    if label == "Inverted":
        return np.rot90(gray, k=2)
    if label == "Left-rotation":
        # Image appears rotated 90° CCW from upright → rotate 90° CW to correct.
        return np.rot90(gray, k=-1)
    if label == "Right-rotation":
        return np.rot90(gray, k=1)
    return gray
