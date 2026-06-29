"""Configuration for TotalSegmentator anatomy analysis."""

from __future__ import annotations

MIN_DICOM_SLICES = 4
MIN_STRUCTURE_VOXELS = 1000
MIN_REGION_FRACTION = 0.15

BODY_PARTS: tuple[str, ...] = ("Head", "Chest", "Abdomen")

ROI_SUBSET: tuple[str, ...] = (
    "brain",
    "skull",
    "heart",
    "trachea",
    "lung_upper_lobe_left",
    "lung_upper_lobe_right",
    "liver",
    "spleen",
    "kidney_left",
    "kidney_right",
    "stomach",
    "pancreas",
)

SEGMENTATION_MODE = "3mm"

# Per-series cache directory (NIfTI volume, ROI seg masks, contrast statistics JSON).
TSEG_CACHE_DIRNAME = ".tseg_cache"

# Head/neck vessel stats (when brain present) + XGBoost after organ HU statistics.
# Set False on low-memory hosts to fall back to FALCON for contrast.
ENABLE_TS_CONTRAST = True
