"""Modality profiles for TotalSegmentator Harmonize / Face Blur (CT vs MR).

CT profile constants match today's production values exactly so existing CT
call sites that omit ``profile`` keep identical behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydicom import Dataset

from anonymizer.controller.ai.tseg.config import (
    FACE_MASK_FILENAME,
    FACE_TASK,
    ROI_SUBSET,
)
from anonymizer.utils.modalities import normalize_modality

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
# Combined ``vertebrae`` is mapped per-series via :func:`mr_structure_to_region_for_series`
# (DICOM metadata + Chest default) so ``total_mr`` spine masks can drive Harmonize regions.
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


def _ct_structure_to_region() -> dict[str, str]:
    # Lazy import: avoid circular import with segment.py (which may take a profile).
    from anonymizer.controller.ai.tseg.segment import STRUCTURE_TO_REGION

    return dict(STRUCTURE_TO_REGION)


def _mr_structure_to_region() -> dict[str, str]:
    from anonymizer.controller.ai.tseg.segment import STRUCTURE_TO_REGION

    merged = dict(STRUCTURE_TO_REGION)
    merged.update(STRUCTURE_TO_REGION_MR_EXTRA)
    return merged


_HARMONIZE_METADATA_ATTRS = (
    "BodyPartExamined",
    "SeriesDescription",
    "ProtocolName",
    "StudyDescription",
    "SequenceName",
)

_MR_VERTEBRAE_HEAD_KEYWORDS: tuple[str, ...] = (
    "HEAD",
    "BRAIN",
    "SKULL",
    "CERVICAL",
    "C-SPINE",
    "CSPINE",
    "NECK",
)

_MR_VERTEBRAE_CHEST_KEYWORDS: tuple[str, ...] = (
    "CHEST",
    "THORACIC",
    "T-SPINE",
    "TSPINE",
)

_MR_VERTEBRAE_ABDOMEN_KEYWORDS: tuple[str, ...] = (
    "ABDOMEN",
    "LUMBAR",
    "L-SPINE",
    "LSPINE",
    "PELVIS",
    "PELVIC",
    "SACRUM",
)


def harmonize_metadata_text(ds: Dataset | None) -> str:
    if ds is None:
        return ""
    parts = [
        getattr(ds, attr, None)
        for attr in _HARMONIZE_METADATA_ATTRS
    ]
    return " ".join(str(part).strip() for part in parts if part).upper()


def infer_mr_vertebrae_region(ds: Dataset | None) -> str:
    """Map MR ``total_mr`` combined ``vertebrae`` mask to a Playbook body region."""
    text = harmonize_metadata_text(ds)
    if not text:
        return "Chest"

    has_head = any(keyword in text for keyword in _MR_VERTEBRAE_HEAD_KEYWORDS)
    has_chest = any(keyword in text for keyword in _MR_VERTEBRAE_CHEST_KEYWORDS)
    has_abdomen = any(keyword in text for keyword in _MR_VERTEBRAE_ABDOMEN_KEYWORDS)

    if has_abdomen and not has_head and not has_chest:
        return "Abdomen"
    if has_head and not has_chest and not has_abdomen:
        return "Head"
    if has_chest and not has_head and not has_abdomen:
        return "Chest"

    if has_abdomen:
        return "Abdomen"
    if has_head:
        return "Head"
    if has_chest:
        return "Chest"
    if "SPINE" in text:
        return "Chest"
    return "Chest"


def mr_structure_to_region_for_series(ds: Dataset | None) -> dict[str, str]:
    """MR structure→region map including metadata-aware combined ``vertebrae``."""
    mapping = _mr_structure_to_region()
    mapping["vertebrae"] = infer_mr_vertebrae_region(ds)
    return mapping


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
    ds = load_series_header_dataset(series_directory)
    if ds is None:
        return None
    return profile_from_dataset(ds)


def load_series_header_dataset(series_directory: object) -> Dataset | None:
    """Read the first stackable DICOM header in a series directory."""
    from pathlib import Path

    from pydicom import dcmread

    from anonymizer.controller.ai.tseg.dicom_geometry import sorted_dicom_paths

    try:
        paths = sorted_dicom_paths(Path(series_directory))
    except ValueError:
        return None
    if not paths:
        return None
    try:
        return dcmread(paths[0], stop_before_pixels=True)
    except OSError:
        return None


# Stable CT task-id snapshot for invariant tests (3mm default mode).
CT_FACE_TASK_ID = _CT_FACE_TASK_ID
MR_FACE_TASK_ID = _MR_FACE_TASK_ID
MR_ANATOMY_TASK_IDS_3MM = _MR_ANATOMY_TASK_IDS_3MM
CT_ANATOMY_TASK_IDS_3MM = _CT_ANATOMY_TASK_IDS_3MM
