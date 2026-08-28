"""Modality profiles for TotalSegmentator Harmonize / Face Blur (CT vs MR).

CT profile constants match today's production values exactly so existing CT
call sites that omit ``profile`` keep identical behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from anonymizer.controller.ai.tseg.config import (
    FACE_MASK_FILENAME,
    FACE_TASK,
    ROI_SUBSET,
)

FaceFillMode = Literal["hu_band", "intensity_percentile"]

# MR ``total_mr`` class names used for region analysis (open task Dataset852 @ 3mm).
ROI_SUBSET_MR: tuple[str, ...] = (
    "brain",
    "spinal_cord",
    "heart",
    "lung_left",
    "lung_right",
    "liver",
    "spleen",
    "kidney_left",
    "kidney_right",
    "stomach",
    "pancreas",
    "vertebrae",
    "sacrum",
    "clavicula_left",
    "clavicula_right",
)

# Overlay on CT STRUCTURE_TO_REGION for MR-only class names.
# Combined ``vertebrae`` is omitted: a whole-column mask must not force Chest/Abdomen
# body-part codes (organs + sacrum already drive region rollup).
STRUCTURE_TO_REGION_MR_EXTRA: dict[str, str] = {
    "lung_left": "Chest",
    "lung_right": "Chest",
    "intervertebral_discs": "Chest",
}

FACE_TASK_MR = "face_mr"
FACE_MASK_FILENAME_MR = "face_mr.nii.gz"

# Task IDs (3mm anatomy + crop companion for CT; MR 3mm total_mr).
_CT_ANATOMY_TASK_IDS_3MM: tuple[int, ...] = (297, 298)
_MR_ANATOMY_TASK_IDS_3MM: tuple[int, ...] = (852,)
_CT_FACE_TASK_ID = 303
_MR_FACE_TASK_ID = 856


@dataclass(frozen=True)
class TsegModalityProfile:
    """Frozen strategy for one TSEG-supported modality."""

    modality: str  # "CT" | "MR"
    anatomy_task: str
    anatomy_task_ids: tuple[int, ...]
    face_task: str
    face_task_id: int
    roi_subset: tuple[str, ...]
    structure_to_region: dict[str, str]
    enable_contrast_phase: bool
    face_fill: FaceFillMode
    loinc_prefix: str
    face_mask_filename: str


def normalize_modality(value: object | None) -> str:
    """Return uppercase modality code; map MRI → MR."""
    text = str(value or "").strip().upper()
    if text == "MRI":
        return "MR"
    return text


def is_ct_modality(value: object | None) -> bool:
    return normalize_modality(value) == "CT"


def is_mr_modality(value: object | None) -> bool:
    return normalize_modality(value) == "MR"


def is_tseg_modality(value: object | None) -> bool:
    return normalize_modality(value) in {"CT", "MR"}


def series_is_tseg_eligible(modality: object | None) -> bool:
    """ORM / study-complete helper: CT or MR series participate in TSEG Harmonize."""
    return is_tseg_modality(modality)


def _ct_structure_to_region() -> dict[str, str]:
    # Lazy import: avoid circular import with segment.py (which may take a profile).
    from anonymizer.controller.ai.tseg.segment import STRUCTURE_TO_REGION

    return dict(STRUCTURE_TO_REGION)


def _mr_structure_to_region() -> dict[str, str]:
    from anonymizer.controller.ai.tseg.segment import STRUCTURE_TO_REGION

    merged = dict(STRUCTURE_TO_REGION)
    merged.update(STRUCTURE_TO_REGION_MR_EXTRA)
    return merged


def ct_modality_profile() -> TsegModalityProfile:
    """Return the production CT profile (must stay bit-identical to pre-MR defaults)."""
    from anonymizer.controller.ai.tseg.model_cache import harmonize_anatomy_task_ids

    return TsegModalityProfile(
        modality="CT",
        anatomy_task="total",
        anatomy_task_ids=tuple(harmonize_anatomy_task_ids()),
        face_task=FACE_TASK,
        face_task_id=_CT_FACE_TASK_ID,
        roi_subset=ROI_SUBSET,
        structure_to_region=_ct_structure_to_region(),
        enable_contrast_phase=True,
        face_fill="hu_band",
        loinc_prefix="CT ",
        face_mask_filename=FACE_MASK_FILENAME,
    )


def mr_modality_profile() -> TsegModalityProfile:
    from anonymizer.controller.ai.tseg.model_cache import mr_anatomy_task_ids

    return TsegModalityProfile(
        modality="MR",
        anatomy_task="total_mr",
        anatomy_task_ids=tuple(mr_anatomy_task_ids()),
        face_task=FACE_TASK_MR,
        face_task_id=_MR_FACE_TASK_ID,
        roi_subset=ROI_SUBSET_MR,
        structure_to_region=_mr_structure_to_region(),
        enable_contrast_phase=False,
        face_fill="intensity_percentile",
        loinc_prefix="MR ",
        face_mask_filename=FACE_MASK_FILENAME_MR,
    )


def profile_for_modality(value: object | None) -> TsegModalityProfile | None:
    """
    Resolve a TSEG modality profile.

    Returns None for unsupported modalities (US, XR, …).
    """
    code = normalize_modality(value)
    if code == "CT":
        return ct_modality_profile()
    if code == "MR":
        return mr_modality_profile()
    return None


def profile_from_dataset(ds: object | None) -> TsegModalityProfile | None:
    modality = getattr(ds, "Modality", None) if ds is not None else None
    return profile_for_modality(modality)


def resolve_profile_for_series(series_directory: object) -> TsegModalityProfile | None:
    """Load the first DICOM in ``series_directory`` and resolve its modality profile."""
    from pathlib import Path

    from pydicom import dcmread

    from anonymizer.controller.ai.tseg.dicom_geometry import sorted_dicom_paths

    try:
        paths = sorted_dicom_paths(Path(series_directory))
    except ValueError:
        return None
    if not paths:
        return None
    ds = dcmread(paths[0], stop_before_pixels=True)
    return profile_from_dataset(ds)


def default_ct_profile() -> TsegModalityProfile:
    """Explicit CT default for call sites that omit ``profile`` (back-compat)."""
    return ct_modality_profile()


# Stable CT task-id snapshot for invariant tests (3mm default mode).
CT_FACE_TASK_ID = _CT_FACE_TASK_ID
MR_FACE_TASK_ID = _MR_FACE_TASK_ID
MR_ANATOMY_TASK_IDS_3MM = _MR_ANATOMY_TASK_IDS_3MM
CT_ANATOMY_TASK_IDS_3MM = _CT_ANATOMY_TASK_IDS_3MM
