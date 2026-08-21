"""Configuration for TotalSegmentator anatomy analysis."""

from __future__ import annotations

MIN_DICOM_SLICES = 4
MIN_STRUCTURE_VOXELS = 1000
MIN_REGION_FRACTION = 0.15

BODY_PARTS: tuple[str, ...] = ("Head", "Chest", "Abdomen")

# TotalSegmentator ``total`` filenames used for region analysis + overlay groups.
_LUNG_LOBE_FILES: tuple[str, ...] = (
    "lung_upper_lobe_left",
    "lung_lower_lobe_left",
    "lung_upper_lobe_right",
    "lung_middle_lobe_right",
    "lung_lower_lobe_right",
)
_VERTEBRAE_FILES: tuple[str, ...] = tuple(
    [f"vertebrae_C{i}" for i in range(1, 8)]
    + [f"vertebrae_T{i}" for i in range(1, 13)]
    + [f"vertebrae_L{i}" for i in range(1, 6)]
    + ["vertebrae_S1", "sacrum"]
)
# Licensed ``vertebrae_body`` task super-segment (not part of ``total`` / ROI_SUBSET).
_SPINE_SUPER_SEGMENT_FILES: tuple[str, ...] = ("vertebrae_body",)
_RIB_FILES: tuple[str, ...] = tuple(
    [f"rib_left_{i}" for i in range(1, 13)] + [f"rib_right_{i}" for i in range(1, 13)]
)
_CLAVICLE_FILES: tuple[str, ...] = ("clavicula_left", "clavicula_right")
_KIDNEY_FILES: tuple[str, ...] = ("kidney_left", "kidney_right")
_HEAD_BRAIN_FILES: tuple[str, ...] = ("brain",)
_HEAD_SKULL_FILES: tuple[str, ...] = ("skull",)
_HEAD_SPINAL_CORD_FILES: tuple[str, ...] = ("spinal_cord",)

# Licensed TotalSegmentator ``brain_structures`` task (Dataset409; same ``aca_*`` license as face).
# Order matches TotalSegmentator's class map presentation.
BRAIN_STRUCTURE_FILES: tuple[str, ...] = (
    "brainstem",
    "subarachnoid_space",
    "venous_sinuses",
    "septum_pellucidum",
    "cerebellum",
    "caudate_nucleus",
    "lentiform_nucleus",
    "insular_cortex",
    "internal_capsule",
    "ventricle",
    "central_sulcus",
    "frontal_lobe",
    "parietal_lobe",
    "occipital_lobe",
    "temporal_lobe",
    "thalamus",
)

# Files requested from TotalSegmentator ``total`` task (must be real class names).
ROI_SUBSET: tuple[str, ...] = (
    *_HEAD_BRAIN_FILES,
    *_HEAD_SKULL_FILES,
    *_HEAD_SPINAL_CORD_FILES,
    "heart",
    "trachea",
    *_LUNG_LOBE_FILES,
    "liver",
    "spleen",
    *_KIDNEY_FILES,
    "stomach",
    "pancreas",
    *_VERTEBRAE_FILES,
    *_RIB_FILES,
    *_CLAVICLE_FILES,
)

# Series View latch groups: one UI label → one or more TS mask files (no L/R split in the UI).
# Head: whole brain + brain_structures subs (when licensed task has run) + skull/cord.
PRIMARY_SEGMENT_GROUPS: dict[str, tuple[str, ...]] = {
    "brain": _HEAD_BRAIN_FILES,
    **{name: (name,) for name in BRAIN_STRUCTURE_FILES},
    "skull": _HEAD_SKULL_FILES,
    "spinal_cord": _HEAD_SPINAL_CORD_FILES,
    "spine": _VERTEBRAE_FILES,
    "clavicles": _CLAVICLE_FILES,
    "ribs": _RIB_FILES,
    "heart": ("heart",),
    "trachea": ("trachea",),
    "lungs": _LUNG_LOBE_FILES,
    "liver": ("liver",),
    "spleen": ("spleen",),
    "kidneys": _KIDNEY_FILES,
    "stomach": ("stomach",),
    "pancreas": ("pancreas",),
}

PRIMARY_SEGMENT_ORDER: tuple[str, ...] = tuple(PRIMARY_SEGMENT_GROUPS.keys())

# Prefer these masks when present on disk (e.g. licensed vertebrae_body task) over multi-file unions.
PRIMARY_SEGMENT_PREFERRED_FILES: dict[str, tuple[str, ...]] = {
    "spine": _SPINE_SUPER_SEGMENT_FILES,
}

SEGMENTATION_MODE = "3mm"

# Per-series cache directory (NIfTI volume, ROI seg masks, contrast statistics JSON).
TSEG_CACHE_DIRNAME = "A_TS_SEG"
GEOMETRY_CACHE_FILENAME = "geometry.json"
ROI_SUBSET_MANIFEST_FILENAME = "roi_subset.json"
CONTRAST_STATS_FILENAME = "contrast_stats.json"
CONTRAST_STATS_HN_FILENAME = "contrast_stats_hn.json"
CONTRAST_PHASE_CACHE_FILENAME = "contrast_phase.json"

# DICOM geometry heuristics (plane, localizer vs volume).
LOCALIZER_MAX_SLICES = 10
MIN_THROUGH_PLANE_EXTENT_MM = 30.0
OBLIQUE_DOT_THRESHOLD = 0.866  # ~30° from nearest cardinal plane
PLANE_AMBIGUITY_DOT_DELTA = 0.05

# Head/neck vessel stats (when brain present) + XGBoost after organ HU statistics.
# Set False on low-memory hosts to fall back to FALCON for contrast.
ENABLE_TS_CONTRAST = True

# Licensed TotalSegmentator ``face`` task (Dataset303; academic ``aca_*`` license).
FACE_TASK = "face"
FACE_MASK_FILENAME = "face.nii.gz"
ENABLE_TSEG_FACE = True

# Licensed TotalSegmentator ``brain_structures`` task (Dataset409; same academic license).
BRAIN_STRUCTURES_TASK = "brain_structures"
ENABLE_TSEG_BRAIN_STRUCTURES = True

# Release anatomy nnUNet predictors before contrast statistics (low-memory batch mode).
RELEASE_ANATOMY_PREDICTORS_BEFORE_CONTRAST = False

# AI batch process memory guard thresholds (MB).
BATCH_MEMORY_WARN_AVAILABLE_MB = 3_000
BATCH_MEMORY_ABORT_AVAILABLE_MB = 1_024
BATCH_MEMORY_POLL_INTERVAL_SEC = 2.0
