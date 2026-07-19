"""Configurable parameters for in-mask Gaussian face blur."""

from __future__ import annotations

# Primary user-facing control: approximate Gaussian standard deviation in millimetres
# (full width at half maximum ≈ 2.355 × sigma_mm for each in-plane axis).
DEFAULT_FACE_BLUR_SIGMA_MM = 8.0

# Minimum pixel sigma passed to OpenCV when spacing is very fine or sigma_mm is small.
# Prevents a near-no-op blur that would not obscure facial structure.
MIN_FACE_BLUR_SIGMA_PX = 0.5
