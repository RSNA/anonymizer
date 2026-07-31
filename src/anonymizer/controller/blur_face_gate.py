"""CT head eligibility gate for Series View Blur Face (metadata + cached anatomy regions)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path

from pydicom import Dataset

from anonymizer.controller.tseg.config import MIN_STRUCTURE_VOXELS, ROI_SUBSET
from anonymizer.controller.tseg.dicom_geometry import SeriesGeometryResult
from anonymizer.controller.tseg.segment import (
    body_parts_present,
    collect_structure_voxels,
    dominant_region_from_voxels,
    series_cache_dir,
)
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

MIN_FACE_MASK_VOXELS = MIN_STRUCTURE_VOXELS


class FaceBlurGateDecision(StrEnum):
    ALLOW = auto()
    CONFIRM = auto()
    BLOCK = auto()


class FaceBlurGateReason(StrEnum):
    MODALITY = auto()
    FEATURE_DISABLED = auto()
    GEOMETRY = auto()
    CACHED_REGIONS_HEAD = auto()
    CACHED_REGIONS_NON_HEAD = auto()
    CACHED_REGIONS_MULTI = auto()
    METADATA_HEAD = auto()
    METADATA_NON_HEAD = auto()
    AMBIGUOUS = auto()
    INSUFFICIENT_FACE_MASK = auto()
    ALREADY_APPLIED = auto()


class MetadataSignal(StrEnum):
    HEAD = auto()
    NON_HEAD = auto()
    AMBIGUOUS = auto()


class CachedRegionSignal(StrEnum):
    HEAD = auto()
    NON_HEAD = auto()
    MULTI_REGION = auto()
    UNAVAILABLE = auto()


@dataclass(frozen=True)
class FaceBlurEligibility:
    decision: FaceBlurGateDecision
    reason: FaceBlurGateReason


_REASON_MSGIDS: dict[FaceBlurGateReason, str] = {
    FaceBlurGateReason.MODALITY: "Face blur is available for CT series only.",
    FaceBlurGateReason.FEATURE_DISABLED: "Face blur is not enabled in this installation.",
    FaceBlurGateReason.GEOMETRY: "This series type is not suitable for face segmentation.",
    FaceBlurGateReason.CACHED_REGIONS_HEAD: "Head anatomy detected from prior segmentation.",
    FaceBlurGateReason.CACHED_REGIONS_NON_HEAD: (
        "This series appears to be a chest or abdomen study, not a head CT."
    ),
    FaceBlurGateReason.CACHED_REGIONS_MULTI: (
        "This series spans multiple body regions. Face blur is intended for head CT. Continue?"
    ),
    FaceBlurGateReason.METADATA_HEAD: "Series metadata indicates a head study.",
    FaceBlurGateReason.METADATA_NON_HEAD: "Series metadata indicates this is not a head CT.",
    FaceBlurGateReason.AMBIGUOUS: (
        "Could not confirm this is a head CT. Face blur is intended for head studies. Continue?"
    ),
    FaceBlurGateReason.INSUFFICIENT_FACE_MASK: (
        "This appears to be a head CT, but TotalSegmentator found no face region to blur. "
        "The series may already be face-blurred or otherwise unsuitable for re-blur."
    ),
    FaceBlurGateReason.ALREADY_APPLIED: (
        "Face blur has already been applied to this series and cannot be run again."
    ),
}

# DICOM keyword heuristics (not user-facing).
_HEAD_KEYWORDS: tuple[str, ...] = (
    "HEAD",
    "BRAIN",
    "SKULL",
    "NECK",
    "ORBIT",
    "SINUS",
    "FACIAL",
    "CEREB",
    "STROKE",
    "CTA HEAD",
    "HEAD NECK",
)

_NON_HEAD_KEYWORDS: tuple[str, ...] = (
    "CHEST",
    "THOR",
    "ABDOM",
    "PELV",
    "LUNG",
    "LIVER",
    "RENAL",
    "KUB",
    "EXTREM",
    "LOWER LIMB",
    "UPPER LIMB",
    "FOOT",
    "ANKLE",
    "KNEE",
    "HIP",
)

_CACHED_SIGNAL_ELIGIBILITY: dict[
    CachedRegionSignal,
    FaceBlurEligibility | None,
] = {
    CachedRegionSignal.HEAD: FaceBlurEligibility(
        FaceBlurGateDecision.ALLOW,
        FaceBlurGateReason.CACHED_REGIONS_HEAD,
    ),
    CachedRegionSignal.NON_HEAD: FaceBlurEligibility(
        FaceBlurGateDecision.BLOCK,
        FaceBlurGateReason.CACHED_REGIONS_NON_HEAD,
    ),
    CachedRegionSignal.MULTI_REGION: FaceBlurEligibility(
        FaceBlurGateDecision.CONFIRM,
        FaceBlurGateReason.CACHED_REGIONS_MULTI,
    ),
    CachedRegionSignal.UNAVAILABLE: None,
}

_METADATA_SIGNAL_ELIGIBILITY: dict[MetadataSignal, FaceBlurEligibility] = {
    MetadataSignal.HEAD: FaceBlurEligibility(
        FaceBlurGateDecision.ALLOW,
        FaceBlurGateReason.METADATA_HEAD,
    ),
    MetadataSignal.NON_HEAD: FaceBlurEligibility(
        FaceBlurGateDecision.BLOCK,
        FaceBlurGateReason.METADATA_NON_HEAD,
    ),
    MetadataSignal.AMBIGUOUS: FaceBlurEligibility(
        FaceBlurGateDecision.CONFIRM,
        FaceBlurGateReason.AMBIGUOUS,
    ),
}


def face_blur_gate_message(reason: FaceBlurGateReason) -> str:
    """Return the translated user-facing message for a gate reason."""
    return _(_REASON_MSGIDS[reason])


def face_blur_context_hint(
    eligibility: FaceBlurEligibility,
    geometry: SeriesGeometryResult | None,
) -> str | None:
    """
    Optional geometry-line suffix when the block reason is not already covered there.

    Geometry blocks are omitted because the Series View geometry line already states
    segmentation suitability; non-head blocks after Harmonize get a explicit cause.
    """
    if eligibility.decision != FaceBlurGateDecision.BLOCK:
        return None
    if eligibility.reason == FaceBlurGateReason.GEOMETRY:
        return None
    if geometry is None:
        return None
    if eligibility.reason in {
        FaceBlurGateReason.CACHED_REGIONS_NON_HEAD,
        FaceBlurGateReason.METADATA_NON_HEAD,
    }:
        return face_blur_gate_message(eligibility.reason)
    return None


def face_mask_is_substantial(face_voxel_count: int) -> bool:
    return face_voxel_count >= MIN_FACE_MASK_VOXELS


def _dicom_search_text(ds: Dataset | None) -> str:
    if ds is None:
        return ""
    parts = [
        getattr(ds, "BodyPartExamined", None),
        getattr(ds, "SeriesDescription", None),
        getattr(ds, "ProtocolName", None),
        getattr(ds, "StudyDescription", None),
    ]
    return " ".join(str(part).strip() for part in parts if part).upper()


def metadata_signal(ds: Dataset | None) -> MetadataSignal:
    text = _dicom_search_text(ds)
    if not text:
        return MetadataSignal.AMBIGUOUS
    has_head = any(keyword in text for keyword in _HEAD_KEYWORDS)
    has_non_head = any(keyword in text for keyword in _NON_HEAD_KEYWORDS)
    if has_head and not has_non_head:
        return MetadataSignal.HEAD
    if has_non_head and not has_head:
        return MetadataSignal.NON_HEAD
    return MetadataSignal.AMBIGUOUS


def cached_region_signal(series_directory: Path) -> CachedRegionSignal:
    """
    Infer head vs non-head from cached TotalSegmentator ROI masks (``A_TS_SEG/seg/``).

    Returns ``UNAVAILABLE`` when harmonize/regions has not populated the cache.
    """
    seg_dir = series_cache_dir(series_directory) / "seg"
    if not seg_dir.is_dir():
        return CachedRegionSignal.UNAVAILABLE

    structure_voxels = collect_structure_voxels(seg_dir, list(ROI_SUBSET))
    if not any(count >= MIN_STRUCTURE_VOXELS for count in structure_voxels.values()):
        return CachedRegionSignal.UNAVAILABLE

    region = dominant_region_from_voxels(structure_voxels)
    regions_label = body_parts_present(region.region_voxels)
    if not regions_label:
        return CachedRegionSignal.UNAVAILABLE

    head_present = "Head" in regions_label.split("+")
    if "+" in regions_label and head_present:
        return CachedRegionSignal.MULTI_REGION
    if region.dominant_region == "Head" or head_present:
        return CachedRegionSignal.HEAD
    if region.dominant_region in {"Chest", "Abdomen"}:
        return CachedRegionSignal.NON_HEAD
    return CachedRegionSignal.UNAVAILABLE


def _eligibility(
    decision: FaceBlurGateDecision,
    reason: FaceBlurGateReason,
) -> FaceBlurEligibility:
    return FaceBlurEligibility(decision, reason)


def evaluate_face_blur_eligibility(
    series_directory: Path,
    *,
    ds: Dataset | None = None,
    geometry: SeriesGeometryResult | None = None,
    modality: str | None = None,
    enable_tseg_face: bool = True,
    face_blur_already_applied: bool = False,
) -> FaceBlurEligibility:
    """
    Decide whether Blur Face should run, prompt for confirmation, or stay disabled.

    Cached anatomy regions (when present) override DICOM metadata heuristics.
    """
    if face_blur_already_applied:
        return _eligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.ALREADY_APPLIED)

    series_directory = Path(series_directory).resolve()
    resolved_modality = modality
    if resolved_modality is None and ds is not None:
        resolved_modality = getattr(ds, "Modality", None)

    if resolved_modality != "CT":
        return _eligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.MODALITY)
    if not enable_tseg_face:
        return _eligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.FEATURE_DISABLED)
    if geometry is None or not geometry.ts_suitable:
        return _eligibility(FaceBlurGateDecision.BLOCK, FaceBlurGateReason.GEOMETRY)

    cached = cached_region_signal(series_directory)
    cached_eligibility = _CACHED_SIGNAL_ELIGIBILITY[cached]
    if cached_eligibility is not None:
        logger.debug("Face blur gate: %s (cached signal=%s)", cached_eligibility.reason.name, cached.name)
        return cached_eligibility

    meta = metadata_signal(ds)
    meta_eligibility = _METADATA_SIGNAL_ELIGIBILITY[meta]
    logger.debug("Face blur gate: %s (metadata signal=%s)", meta_eligibility.reason.name, meta.name)
    return meta_eligibility
