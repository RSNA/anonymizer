"""AI feature and download identity (product vocabulary).

Public API
----------
AiFeatureId
    Top-level AI Features identifiers.

AiModelGroupId
    Downloadable model group identifiers.

DOWNLOAD_ID_*
    Stable download-progress / cache keys for each model group.

all_download_ids() -> tuple[str, ...]
    Every download id used by the Features panel and caches.

download_id_for_weight_kind(kind) -> str
weight_kind_for_download_id(download_id) -> TsWeightKind | None
    Bridge TotalSegmentator weight kinds to download ids.

DEID_OPTION_FEATURES
    De-identification option → executing AI feature (or None).

ai_feature_for_deid_option(code) -> AiFeatureId | None
    Feature that executes a de-identification option.
"""

from enum import StrEnum

from anonymizer.controller.ai.tseg.ts_probe import TsWeightKind
from anonymizer.utils.dicom import DeidMethodCode


class AiFeatureId(StrEnum):
    """Top-level AI Features."""

    EMBEDDED_PHI = "embedded_phi"
    HARMONIZE = "enable_harmonize"
    FACE_BLUR = "enable_face_blur"
    BRAIN_STRUCTURES = "enable_brain_structures"


class AiModelGroupId(StrEnum):
    """Downloadable model groups shown under a parent feature."""

    EMBEDDED_PHI = "embedded_phi"
    HARMONIZE_CT = "harmonize_ct_models"
    HARMONIZE_MR = "harmonize_mr_models"
    HARMONIZE_XR_BODYPART = "harmonize_xr_bodypart"
    HARMONIZE_CXR_VIEW = "harmonize_cxr_view"
    FACE_CT = "face_ct_models"
    FACE_MR = "face_mr_models"
    BRAIN_STRUCTURES = "enable_brain_structures"


DOWNLOAD_ID_EMBEDDED_PHI = AiModelGroupId.EMBEDDED_PHI.value
DOWNLOAD_ID_HARMONIZE_CT = AiModelGroupId.HARMONIZE_CT.value
DOWNLOAD_ID_HARMONIZE_MR = AiModelGroupId.HARMONIZE_MR.value
DOWNLOAD_ID_HARMONIZE_XR_BODYPART = AiModelGroupId.HARMONIZE_XR_BODYPART.value
DOWNLOAD_ID_HARMONIZE_CXR_VIEW = AiModelGroupId.HARMONIZE_CXR_VIEW.value
DOWNLOAD_ID_FACE_CT = AiModelGroupId.FACE_CT.value
DOWNLOAD_ID_FACE_MR = AiModelGroupId.FACE_MR.value
DOWNLOAD_ID_BRAIN = AiModelGroupId.BRAIN_STRUCTURES.value

_WEIGHT_KIND_TO_DOWNLOAD_ID: dict[TsWeightKind, str] = {
    TsWeightKind.ANATOMY: DOWNLOAD_ID_HARMONIZE_CT,
    TsWeightKind.ANATOMY_MR: DOWNLOAD_ID_HARMONIZE_MR,
    TsWeightKind.FACE: DOWNLOAD_ID_FACE_CT,
    TsWeightKind.FACE_MR: DOWNLOAD_ID_FACE_MR,
    TsWeightKind.BRAIN_STRUCTURES: DOWNLOAD_ID_BRAIN,
}

_DOWNLOAD_ID_TO_WEIGHT_KIND: dict[str, TsWeightKind] = {
    v: k for k, v in _WEIGHT_KIND_TO_DOWNLOAD_ID.items()
}


def download_id_for_weight_kind(kind: TsWeightKind) -> str:
    """Download id for a TotalSegmentator weight kind."""
    return _WEIGHT_KIND_TO_DOWNLOAD_ID[kind]


def weight_kind_for_download_id(download_id: str) -> TsWeightKind | None:
    """Weight kind for a download id, or None when not a TS pack."""
    return _DOWNLOAD_ID_TO_WEIGHT_KIND.get(download_id)


def all_download_ids() -> tuple[str, ...]:
    """Every download id used by Features download progress and caches."""
    return (
        DOWNLOAD_ID_EMBEDDED_PHI,
        DOWNLOAD_ID_HARMONIZE_CT,
        DOWNLOAD_ID_HARMONIZE_MR,
        DOWNLOAD_ID_HARMONIZE_XR_BODYPART,
        DOWNLOAD_ID_HARMONIZE_CXR_VIEW,
        DOWNLOAD_ID_BRAIN,
        DOWNLOAD_ID_FACE_CT,
        DOWNLOAD_ID_FACE_MR,
    )


# De-identification option → AI feature that executes it. Ingest options and
# CLEAN_GRAPHICS have no feature (CLEAN_GRAPHICS is never executed yet);
# Harmonize and Brain Structures execute no de-identification option.
DEID_OPTION_FEATURES: dict[DeidMethodCode, AiFeatureId | None] = {
    DeidMethodCode.CLEAN_PIXEL_DATA: AiFeatureId.EMBEDDED_PHI,
    DeidMethodCode.CLEAN_STRUCTURED_CONTENT: AiFeatureId.EMBEDDED_PHI,
    DeidMethodCode.CLEAN_DESCRIPTORS: AiFeatureId.EMBEDDED_PHI,
    DeidMethodCode.CLEAN_VISUAL_FEATURES: AiFeatureId.FACE_BLUR,
    DeidMethodCode.CLEAN_GRAPHICS: None,
}


def ai_feature_for_deid_option(code: DeidMethodCode) -> AiFeatureId | None:
    """
    AI feature that executes a de-identification option.

    Args:
        code: De-identification option code.

    Returns:
        The executing feature, or None for ingest options and options no
        feature executes.
    """
    return DEID_OPTION_FEATURES.get(DeidMethodCode(code))
