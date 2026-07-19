from __future__ import annotations

import cv2
import numpy as np

from prototyping.ffr.face.config import DEFAULT_FACE_BLUR_SIGMA_MM, MIN_FACE_BLUR_SIGMA_PX


def blur_face_hu_volume(
    hu: np.ndarray,
    mask: np.ndarray,
    *,
    sigma_mm: float = DEFAULT_FACE_BLUR_SIGMA_MM,
    pixel_spacing_mm: tuple[float, float] = (1.0, 1.0),
    min_sigma_px: float = MIN_FACE_BLUR_SIGMA_PX,
) -> np.ndarray:
    """
    In-plane Gaussian blur inside ``mask`` only; voxels outside ``mask`` unchanged.

    Parameters
    ----------
    sigma_mm:
        Target Gaussian standard deviation in millimetres, applied separately along
        row and column axes after converting to pixel units via ``pixel_spacing_mm``.
        Larger values remove more facial detail; typical CT head range is 6–15 mm.
    pixel_spacing_mm:
        ``(row_spacing, col_spacing)`` in mm — from DICOM ``PixelSpacing`` in the
        same order used for the HU stack (SimpleITK spacing Y, X).
    min_sigma_px:
        Floor for per-axis pixel sigma so very small ``sigma_mm`` or fine spacing
        still produces a visible blur.

    ``hu`` and ``mask`` shape: (Z, Y, X).
    """
    if hu.shape != mask.shape:
        raise ValueError(f"HU shape {hu.shape} != mask shape {mask.shape}")

    row_spacing, col_spacing = pixel_spacing_mm
    sigma_y = max(sigma_mm / row_spacing, min_sigma_px)
    sigma_x = max(sigma_mm / col_spacing, min_sigma_px)

    out = hu.copy()
    face = mask.astype(bool)
    for z in range(hu.shape[0]):
        slice_mask = face[z]
        if not slice_mask.any():
            continue
        blurred = cv2.GaussianBlur(
            hu[z].astype(np.float32),
            ksize=(0, 0),
            sigmaX=sigma_x,
            sigmaY=sigma_y,
        )
        out[z] = np.where(slice_mask, blurred, hu[z])
    return out
