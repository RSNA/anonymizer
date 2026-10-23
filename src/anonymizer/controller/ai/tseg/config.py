"""Configuration for TotalSegmentator anatomy analysis.

Public API
----------
MIN_DICOM_SLICES
    Min dicom slices (4).

MIN_STRUCTURE_VOXELS
    Min structure voxels (1000).

MIN_REGION_FRACTION
    Min region fraction (0.15).

TSEG_CACHE_DIRNAME
    Tseg cache dirname (default '0_TS_SEG').

ANNOTATIONS_DIRNAME
    Annotations dirname (default 'annotations').

GEOMETRY_CACHE_FILENAME
    Geometry cache filename (default 'geometry.json').

GEOMETRY_CACHE_VERSION
    Geometry cache version (3).

ROI_SUBSET_MANIFEST_FILENAME
    Roi subset manifest filename (default 'roi_subset.json').

CONTRAST_STATS_FILENAME
    Contrast stats filename.

CONTRAST_STATS_HN_FILENAME
    Contrast stats hn filename.

CONTRAST_PHASE_CACHE_FILENAME
    Contrast phase cache filename.

STRUCTURE_VOXELS_FILENAME
    Structure voxels filename.

PRIMARY_SEGMENT_VOXELS_FILENAME
    Primary segment voxels filename.

MASK_GEOMETRY_FILENAME
    Mask geometry filename (default 'mask_geometry.json').

LOCALIZER_MAX_SLICES
    Localizer max slices (10).

MIN_THROUGH_PLANE_EXTENT_MM
    Min through plane extent mm (30.0).

SURVEY_MIN_SLICE_SPACING_MM
    Survey min slice spacing mm (6.0).

OBLIQUE_DOT_THRESHOLD
    Oblique dot threshold (0.866).

PLANE_AMBIGUITY_DOT_DELTA
    Plane ambiguity dot delta (0.05).

ENABLE_TS_CONTRAST
    Enable ts contrast (True).

ENABLE_CT_HARMONIZE_SINGLE_PASS
    Enable ct harmonize single pass (True).

FACE_TASK
    Face task (default 'face').

FACE_MASK_FILENAME
    Face mask filename (default 'face.nii.gz').

ENABLE_TSEG_FACE
    Enable tseg face (True).

BRAIN_STRUCTURES_TASK
    Brain structures task (default 'brain_structures').

ENABLE_TSEG_BRAIN_STRUCTURES
    Enable tseg brain structures (True).

RELEASE_ANATOMY_PREDICTORS_BEFORE_CONTRAST
    Release anatomy predictors before contrast (False).

BATCH_MEMORY_POLL_INTERVAL_SEC
    Batch memory poll interval sec (2.0).

BODY_PARTS
    Body parts.

STRUCTURE_TO_REGION
    Structure to region.

BRAIN_STRUCTURE_FILES
    Brain structure files.

ROI_SUBSET_HEAD
    Roi subset head.

ROI_SUBSET_CHEST
    Roi subset chest.

ROI_SUBSET
    Roi subset.

ROI_SUBSET_FULL
    Roi subset full.

ROI_TIER_HEAD
    Roi tier head (default 'HEAD').

ROI_TIER_CHEST
    Roi tier chest (default 'CHEST').

ROI_TIER_FULL
    Roi tier full (default 'FULL').

PRIMARY_SEGMENT_GROUPS
    Primary segment groups.

PRIMARY_SEGMENT_ORDER
    Primary segment order.

PRIMARY_SEGMENT_PREFERRED_FILES
    Primary segment preferred files.

DEFAULT_SEGMENTATION_MODE
    Default segmentation mode (default '3mm').

SegmentationMode
    Segmentationmode.

SEGMENTATION_MODES
    Segmentation modes.

normalize_segmentation_mode(value: object | None) -> SegmentationMode
    Normalize segmentation mode.

segmentation_mode_display(mode: object | None) -> str
    Human-readable spacing for status lines (not used for menu state).

segmentation_mode_menu_values() -> tuple[SegmentationMode, ...]
    Internal mode codes for resolution pickers (language-agnostic).

installed_segmentation_mode_menu_values(modes: tuple[str, ...] | list[str]) -> tuple[SegmentationMode, ...]
    Installed subset of segmentation_mode_menu_values() in canonical order.

default_installed_segmentation_mode(modes: tuple[str, ...] | list[str]) -> SegmentationMode
    Prefer 3 mm when installed; otherwise the first installed mode.

get_ct_segmentation_mode() -> SegmentationMode
    Get ct segmentation mode.

get_mr_segmentation_mode() -> SegmentationMode
    Get mr segmentation mode.

set_ct_segmentation_mode(mode: object | None) -> SegmentationMode
    Set ct segmentation mode.

set_mr_segmentation_mode(mode: object | None) -> SegmentationMode
    Set mr segmentation mode.

clear_segmentation_mode_cache() -> None
    Reset CT/MR modes to the default (tests / process cleanup).

segmentation_mode_for_modality(modality: str | Modality | None) -> SegmentationMode
    Return the active segmentation mode for a DICOM modality code.

is_multi_model_segmentation_mode(mode: object | None) -> bool
    1.5 mm uses multiple nnUNet tasks; predictor preload is skipped.

current_ai_features_preferences() -> dict[str, str]
    Current ai features preferences.

apply_ai_features_preferences(prefs: dict[str, Any] | None=None) -> None
    Load CT/MR Harmonize resolution preferences into the runtime config module.

persist_ai_features_preferences() -> None
    Merge current CT/MR segmentation modes into .anonymizer_state.json.

merge_ai_features_into_state(state: dict[str, Any]) -> dict[str, Any]
    Merge ai features into state.
"""
import logging
from typing import Any, Literal

from anonymizer.utils.app_state import (
    AI_FEATURES_SECTION,
    CT_SEGMENTATION_MODE_KEY,
    MR_SEGMENTATION_MODE_KEY,
    ai_features_from_state,
    read_app_state,
    write_app_state,
)
from anonymizer.utils.modalities import Modality

logger = logging.getLogger(__name__)

MIN_DICOM_SLICES = 4
MIN_STRUCTURE_VOXELS = 1000
MIN_REGION_FRACTION = 0.15

# Per-series cache directory (NIfTI volume, ROI seg masks, contrast statistics JSON).
TSEG_CACHE_DIRNAME = "0_TS_SEG"
# User annotation label volumes under the per-series cache (preserved when pruning TS masks).
ANNOTATIONS_DIRNAME = "annotations"
GEOMETRY_CACHE_FILENAME = "geometry.json"
GEOMETRY_CACHE_VERSION = 3
ROI_SUBSET_MANIFEST_FILENAME = "roi_subset.json"
CONTRAST_STATS_FILENAME = "contrast_stats.json"
CONTRAST_STATS_HN_FILENAME = "contrast_stats_hn.json"
CONTRAST_PHASE_CACHE_FILENAME = "contrast_phase.json"
STRUCTURE_VOXELS_FILENAME = "structure_voxels.json"
PRIMARY_SEGMENT_VOXELS_FILENAME = "primary_segment_voxels.json"
MASK_GEOMETRY_FILENAME = "mask_geometry.json"

# DICOM geometry heuristics (plane, localizer vs volume).
LOCALIZER_MAX_SLICES = 10
MIN_THROUGH_PLANE_EXTENT_MM = 30.0
SURVEY_MIN_SLICE_SPACING_MM = 6.0
OBLIQUE_DOT_THRESHOLD = 0.866  # ~30° from nearest cardinal plane
PLANE_AMBIGUITY_DOT_DELTA = 0.05

# Head/neck vessel stats (when brain present) + XGBoost after organ HU statistics.
# Set False on low-memory hosts to skip TS contrast analysis.
ENABLE_TS_CONTRAST = True

# CT Harmonize: one total+statistics pass supplies anatomy regions and contrast organ HU.
# Set False to force the legacy ROI anatomy pass then a separate contrast statistics pass.
ENABLE_CT_HARMONIZE_SINGLE_PASS = True

# Licensed TotalSegmentator face task (Dataset303; academic aca_* license).
FACE_TASK = "face"
FACE_MASK_FILENAME = "face.nii.gz"
ENABLE_TSEG_FACE = True

# Licensed TotalSegmentator brain_structures task (Dataset409; same academic license).
BRAIN_STRUCTURES_TASK = "brain_structures"
ENABLE_TSEG_BRAIN_STRUCTURES = True

# Release anatomy nnUNet predictors before contrast statistics (low-memory batch mode).
RELEASE_ANATOMY_PREDICTORS_BEFORE_CONTRAST = False

# AI batch process memory guard poll interval (MB thresholds live in utils.memory).
BATCH_MEMORY_POLL_INTERVAL_SEC = 2.0


BODY_PARTS: tuple[str, ...] = ("Head", "Chest", "Abdomen")

STRUCTURE_TO_REGION: dict[str, str] = {
    "brain": "Head",
    "skull": "Head",
    "spinal_cord": "Head",
    "lung_upper_lobe_left": "Chest",
    "lung_lower_lobe_left": "Chest",
    "lung_upper_lobe_right": "Chest",
    "lung_middle_lobe_right": "Chest",
    "lung_lower_lobe_right": "Chest",
    "heart": "Chest",
    "trachea": "Chest",
    "esophagus": "Chest",
    "clavicula_left": "Chest",
    "clavicula_right": "Chest",
    **{f"rib_left_{i}": "Chest" for i in range(1, 13)},
    **{f"rib_right_{i}": "Chest" for i in range(1, 13)},
    **{f"vertebrae_C{i}": "Head" for i in range(1, 8)},
    **{f"vertebrae_T{i}": "Chest" for i in range(1, 13)},
    **{f"vertebrae_L{i}": "Abdomen" for i in range(1, 6)},
    "vertebrae_S1": "Abdomen",
    **{name: "Head" for name in (
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
    )},
    "liver": "Abdomen",
    "spleen": "Abdomen",
    "kidney_left": "Abdomen",
    "kidney_right": "Abdomen",
    "stomach": "Abdomen",
    "pancreas": "Abdomen",
    "gallbladder": "Abdomen",
    "colon": "Abdomen",
    "small_bowel": "Abdomen",
    "urinary_bladder": "Abdomen",
    "hip_left": "Abdomen",
    "hip_right": "Abdomen",
    "sacrum": "Abdomen",
}

# TotalSegmentator total filenames used for region analysis + overlay groups.
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
# Licensed vertebrae_body task super-segment (not part of total / ROI_SUBSET).
_SPINE_SUPER_SEGMENT_FILES: tuple[str, ...] = ("vertebrae_body",)
_RIB_FILES: tuple[str, ...] = tuple(
    [f"rib_left_{i}" for i in range(1, 13)] + [f"rib_right_{i}" for i in range(1, 13)]
)
_CLAVICLE_FILES: tuple[str, ...] = ("clavicula_left", "clavicula_right")
_KIDNEY_FILES: tuple[str, ...] = ("kidney_left", "kidney_right")
_HEAD_BRAIN_FILES: tuple[str, ...] = ("brain",)
_HEAD_SKULL_FILES: tuple[str, ...] = ("skull",)
_HEAD_SPINAL_CORD_FILES: tuple[str, ...] = ("spinal_cord",)

# Licensed TotalSegmentator brain_structures task (Dataset409; same aca_* license as face).
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

# Files requested from TotalSegmentator total task (must be real class names).
ROI_SUBSET_HEAD: tuple[str, ...] = (
    *_HEAD_BRAIN_FILES,
    *_HEAD_SKULL_FILES,
    *_HEAD_SPINAL_CORD_FILES,
    *tuple(f"vertebrae_C{i}" for i in range(1, 8)),
    *_CLAVICLE_FILES,
    "trachea",
)

ROI_SUBSET_CHEST: tuple[str, ...] = (
    *ROI_SUBSET_HEAD,
    "heart",
    *_LUNG_LOBE_FILES,
    *_RIB_FILES,
    *tuple(f"vertebrae_T{i}" for i in range(1, 13)),
)

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

ROI_SUBSET_FULL: tuple[str, ...] = ROI_SUBSET

ROI_TIER_HEAD = "HEAD"
ROI_TIER_CHEST = "CHEST"
ROI_TIER_FULL = "FULL"

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

DEFAULT_SEGMENTATION_MODE = "3mm"

SegmentationMode = Literal["1.5mm", "3mm", "6mm"]
_VALID_SEGMENTATION_MODES: frozenset[str] = frozenset({"1.5mm", "3mm", "6mm"})
SEGMENTATION_MODES: tuple[SegmentationMode, ...] = ("1.5mm", "3mm", "6mm")

# Fixed ASCII labels for status text only (never menu state; not passed through gettext).
_SEGMENTATION_MODE_DISPLAY: dict[SegmentationMode, str] = {
    "1.5mm": "1.5 mm",
    "3mm": "3 mm",
    "6mm": "6 mm",
}

# Workstation defaults; restored from .anonymizer_state.json at startup (see utils.app_state).
_ct_segmentation_mode: SegmentationMode = DEFAULT_SEGMENTATION_MODE  # type: ignore[assignment]
_mr_segmentation_mode: SegmentationMode = DEFAULT_SEGMENTATION_MODE  # type: ignore[assignment]


def normalize_segmentation_mode(value: object | None) -> SegmentationMode:
    text = str(value or "").strip().lower().replace(" ", "").replace(",", ".")
    if text in _VALID_SEGMENTATION_MODES:
        return text  # type: ignore[return-value]
    return DEFAULT_SEGMENTATION_MODE  # type: ignore[return-value]


def segmentation_mode_display(mode: object | None) -> str:
    """Human-readable spacing for status lines (not used for menu state)."""
    return _SEGMENTATION_MODE_DISPLAY[normalize_segmentation_mode(mode)]


def segmentation_mode_menu_values() -> tuple[SegmentationMode, ...]:
    """Internal mode codes for resolution pickers (language-agnostic)."""
    return SEGMENTATION_MODES


def installed_segmentation_mode_menu_values(modes: tuple[str, ...] | list[str]) -> tuple[SegmentationMode, ...]:
    """Installed subset of segmentation_mode_menu_values() in canonical order."""
    installed = {normalize_segmentation_mode(mode) for mode in modes}
    return tuple(mode for mode in SEGMENTATION_MODES if mode in installed)


def default_installed_segmentation_mode(modes: tuple[str, ...] | list[str]) -> SegmentationMode:
    """Prefer 3 mm when installed; otherwise the first installed mode."""
    normalized = tuple(normalize_segmentation_mode(mode) for mode in modes)
    if "3mm" in normalized:
        return "3mm"  # type: ignore[return-value]
    if normalized:
        return normalized[0]
    return DEFAULT_SEGMENTATION_MODE  # type: ignore[return-value]


def get_ct_segmentation_mode() -> SegmentationMode:
    return _ct_segmentation_mode


def get_mr_segmentation_mode() -> SegmentationMode:
    return _mr_segmentation_mode


def set_ct_segmentation_mode(mode: object | None) -> SegmentationMode:
    global _ct_segmentation_mode
    _ct_segmentation_mode = normalize_segmentation_mode(mode)
    return _ct_segmentation_mode


def set_mr_segmentation_mode(mode: object | None) -> SegmentationMode:
    global _mr_segmentation_mode
    _mr_segmentation_mode = normalize_segmentation_mode(mode)
    return _mr_segmentation_mode


def clear_segmentation_mode_cache() -> None:
    """Reset CT/MR modes to the default (tests / process cleanup)."""
    global _ct_segmentation_mode, _mr_segmentation_mode
    _ct_segmentation_mode = DEFAULT_SEGMENTATION_MODE  # type: ignore[assignment]
    _mr_segmentation_mode = DEFAULT_SEGMENTATION_MODE  # type: ignore[assignment]


def segmentation_mode_for_modality(modality: str | Modality | None) -> SegmentationMode:
    """Return the active segmentation mode for a DICOM modality code."""
    parsed = modality if isinstance(modality, Modality) else Modality.from_code(modality)
    if parsed is Modality.MR:
        return get_mr_segmentation_mode()
    return get_ct_segmentation_mode()


def is_multi_model_segmentation_mode(mode: object | None) -> bool:
    """1.5 mm uses multiple nnUNet tasks; predictor preload is skipped."""
    return normalize_segmentation_mode(mode) == "1.5mm"


def current_ai_features_preferences() -> dict[str, str]:
    return {
        CT_SEGMENTATION_MODE_KEY: get_ct_segmentation_mode(),
        MR_SEGMENTATION_MODE_KEY: get_mr_segmentation_mode(),
    }


def apply_ai_features_preferences(prefs: dict[str, Any] | None = None) -> None:
    """Load CT/MR Harmonize resolution preferences into the runtime config module."""
    if prefs is None:
        prefs = ai_features_from_state(read_app_state())
    if CT_SEGMENTATION_MODE_KEY in prefs:
        set_ct_segmentation_mode(prefs[CT_SEGMENTATION_MODE_KEY])
    if MR_SEGMENTATION_MODE_KEY in prefs:
        set_mr_segmentation_mode(prefs[MR_SEGMENTATION_MODE_KEY])


def persist_ai_features_preferences() -> None:
    """Merge current CT/MR segmentation modes into .anonymizer_state.json."""
    state = read_app_state()
    state[AI_FEATURES_SECTION] = current_ai_features_preferences()
    write_app_state(state)


def merge_ai_features_into_state(state: dict[str, Any]) -> dict[str, Any]:
    merged = dict(state)
    merged[AI_FEATURES_SECTION] = current_ai_features_preferences()
    return merged

