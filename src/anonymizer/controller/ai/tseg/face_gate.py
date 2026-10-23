"""Face blur eligibility vocabulary (gate decisions/reasons/messages); leaf shared by tseg and blur_face.

Public API
----------
MIN_FACE_MASK_VOXELS
    Min face mask voxels.

FaceBlurGateDecision
    FaceBlurGateDecision type.

FaceBlurGateReason
    FaceBlurGateReason type.

FaceBlurEligibility
    FaceBlurEligibility type.

face_blur_gate_message(reason: FaceBlurGateReason) -> str
    Return the translated user-facing message for a gate reason.

face_mask_is_substantial(face_voxel_count: int) -> bool
    Face mask is substantial.
"""
from dataclasses import dataclass
from enum import StrEnum, auto

from anonymizer.controller.ai.tseg.config import MIN_STRUCTURE_VOXELS
from anonymizer.utils.translate import _

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


@dataclass(frozen=True)
class FaceBlurEligibility:
    decision: FaceBlurGateDecision
    reason: FaceBlurGateReason


_REASON_MSGIDS: dict[FaceBlurGateReason, str] = {
    FaceBlurGateReason.MODALITY: "Face blur is available for CT and MR series only.",
    FaceBlurGateReason.FEATURE_DISABLED: "Face blur is not enabled in this installation.",
    FaceBlurGateReason.GEOMETRY: "This series type is not suitable for face segmentation.",
    FaceBlurGateReason.CACHED_REGIONS_HEAD: "Head anatomy detected from prior segmentation.",
    FaceBlurGateReason.CACHED_REGIONS_NON_HEAD: ("This series appears to be a chest or abdomen study, not a head CT."),
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
    FaceBlurGateReason.ALREADY_APPLIED: ("Face blur has already been applied to this series and cannot be run again."),
}


def face_blur_gate_message(reason: FaceBlurGateReason) -> str:
    """Return the translated user-facing message for a gate reason."""
    return _(_REASON_MSGIDS[reason])


def face_mask_is_substantial(face_voxel_count: int) -> bool:
    return face_voxel_count >= MIN_FACE_MASK_VOXELS
