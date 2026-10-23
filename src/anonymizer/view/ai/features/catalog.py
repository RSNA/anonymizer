"""AI Features catalog: IDs, slim specs, titles, and frozen registry."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from anonymizer.controller.ai import feature_availability as feature_gates
from anonymizer.controller.ai.embedded_phi.ner.cache import download_ner_models, remove_ner_models
from anonymizer.controller.ai.embedded_phi.pixel.cache import download_ocr_models, remove_ocr_models
from anonymizer.controller.ai.harmonize.xp_bodypart import download_xp_bodypart_models, remove_xp_bodypart_models
from anonymizer.controller.ai.harmonize.xr_chest_view import download_xr_chest_view_models, remove_xr_chest_view_models
from anonymizer.controller.ai.tseg.readiness import TsWeightKind, download_segmentation_model, remove_segmentation_model
from anonymizer.model.project import AT_INGEST
from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.utils.translate import _


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

_DOWNLOAD_ID_TO_WEIGHT_KIND: dict[str, TsWeightKind] = {v: k for k, v in _WEIGHT_KIND_TO_DOWNLOAD_ID.items()}


def download_id_for_weight_kind(kind: TsWeightKind) -> str:
    return _WEIGHT_KIND_TO_DOWNLOAD_ID[kind]


def weight_kind_for_download_id(download_id: str) -> TsWeightKind | None:
    return _DOWNLOAD_ID_TO_WEIGHT_KIND.get(download_id)


def all_download_ids() -> tuple[str, ...]:
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


@dataclass(frozen=True)
class AiModelGroupSpec:
    """One downloadable model group under a parent feature."""

    id: AiModelGroupId
    download_id: str
    title: Callable[[], str]
    summary: Callable[[], str]
    status: Callable[[], str]
    needs_download: Callable[[], bool]
    has_models: Callable[[], bool]
    download: Callable[[], object]
    remove: Callable[[], None]
    has_resolution_picker: bool = False


@dataclass(frozen=True)
class AiFeatureSpec:
    """Top-level AI Features tool (may own nested model groups)."""

    id: AiFeatureId
    title: Callable[[], str]
    description: Callable[[], str]
    summary: Callable[[], str]
    status: Callable[[], str]
    model_group_ids: tuple[AiModelGroupId, ...] = ()


def feature_title(key: str) -> str:
    return {
        AiFeatureId.EMBEDDED_PHI.value: _("Embedded PHI"),
        AiFeatureId.HARMONIZE.value: _("Harmonize"),
        AiFeatureId.BRAIN_STRUCTURES.value: _("Brain structures"),
        AiFeatureId.FACE_BLUR.value: _("Face De-identify"),
        AiModelGroupId.HARMONIZE_CT.value: _("CT models"),
        AiModelGroupId.HARMONIZE_MR.value: _("MR models"),
        AiModelGroupId.HARMONIZE_XR_BODYPART.value: _("XR body part"),
        AiModelGroupId.HARMONIZE_CXR_VIEW.value: _("XR chest view"),
        AiModelGroupId.FACE_CT.value: _("CT models"),
        AiModelGroupId.FACE_MR.value: _("MR models"),
    }[key]


def feature_capability_description(key: str) -> str:
    """What the feature does at runtime (AI Batch copy; no download/install wording)."""
    return {
        AiFeatureId.EMBEDDED_PHI.value: _(
            "Remove identifiers from burnt-in pixels and English free text."
        ),
        AiFeatureId.HARMONIZE.value: _(
            "Harmonize Series Description using RadLex playbook and Study Description using LOINC dictionary."
        ),
        AiFeatureId.BRAIN_STRUCTURES.value: _(
            "Optional CT Head detail after total anatomy (academic license)."
        ),
        AiFeatureId.FACE_BLUR.value: _(
            "Blur faces on head CT/MR. Requires TotalSegmentator academic license."
        ),
    }[key]


def feature_description(key: str) -> str:
    """Setup hover-tooltip text (includes download notes where they apply)."""
    capability = feature_capability_description(key)
    if key == AiFeatureId.EMBEDDED_PHI.value:
        return capability + " " + _("Download installs OCR + NER together.")
    return capability


def feature_summary(key: str) -> str:
    return {
        AiFeatureId.EMBEDDED_PHI.value: _("OCR + English PHI NER for pixels and reports."),
        AiFeatureId.HARMONIZE.value: _("RadLex series naming from anatomy."),
        AiModelGroupId.HARMONIZE_CT.value: "",
        AiModelGroupId.HARMONIZE_MR.value: "",
        AiModelGroupId.HARMONIZE_XR_BODYPART.value: _(
            "Optional pixel body-part for CR/DX (Xp-Bodypart-Checker)."
        ),
        AiModelGroupId.HARMONIZE_CXR_VIEW.value: _(
            "Optional XR chest view (AP/PA/Lateral + rotation) for chest CR/DX."
        ),
        AiFeatureId.BRAIN_STRUCTURES.value: _("CT Head detail in Harmonize Description."),
        AiFeatureId.FACE_BLUR.value: _("Head CT/MR face de-identify."),
        AiModelGroupId.FACE_CT.value: "",
        AiModelGroupId.FACE_MR.value: "",
    }[key]


def download_embedded_phi() -> object:
    ocr_ok, ocr_msg = download_ocr_models()
    if not ocr_ok:
        return False, ocr_msg
    return download_ner_models()


def remove_embedded_phi() -> None:
    remove_ocr_models()
    remove_ner_models()


def download_xp_bodypart() -> object:
    return download_xp_bodypart_models()


def remove_xp_bodypart() -> None:
    remove_xp_bodypart_models()


def download_xr_chest_view() -> object:
    return download_xr_chest_view_models()


def remove_xr_chest_view() -> None:
    remove_xr_chest_view_models()


# Back-compat aliases for AI Features panel wiring
download_cxp_view = download_xr_chest_view
remove_cxp_view = remove_xr_chest_view


def download_kind(kind: TsWeightKind) -> object:
    return download_segmentation_model(kind)


def remove_kind(kind: TsWeightKind) -> None:
    remove_segmentation_model(kind)


TOP_LEVEL_FEATURE_IDS: tuple[AiFeatureId, ...] = (
    AiFeatureId.EMBEDDED_PHI,
    AiFeatureId.HARMONIZE,
    AiFeatureId.FACE_BLUR,
)

_MODEL_GROUPS: dict[AiModelGroupId, AiModelGroupSpec] = {}
_FEATURES: dict[AiFeatureId, AiFeatureSpec] = {}


def install_registry(
    model_groups: dict[AiModelGroupId, AiModelGroupSpec],
    features: dict[AiFeatureId, AiFeatureSpec],
) -> None:
    """Bind status/download callables from availability (avoids import cycles)."""
    _MODEL_GROUPS.clear()
    _MODEL_GROUPS.update(model_groups)
    _FEATURES.clear()
    _FEATURES.update(features)


def feature_spec(feature_id: AiFeatureId) -> AiFeatureSpec:
    return _FEATURES[feature_id]


def model_group_spec(group_id: AiModelGroupId) -> AiModelGroupSpec:
    return _MODEL_GROUPS[group_id]


def top_level_features() -> tuple[AiFeatureSpec, ...]:
    return tuple(_FEATURES[fid] for fid in TOP_LEVEL_FEATURE_IDS)


def groups_for(parent: AiFeatureId) -> tuple[AiModelGroupSpec, ...]:
    feature = _FEATURES[parent]
    return tuple(_MODEL_GROUPS[gid] for gid in feature.model_group_ids)


def group_by_download_id(download_id: str) -> AiModelGroupSpec | None:
    for group in _MODEL_GROUPS.values():
        if group.download_id == download_id:
            return group
    return None


def all_model_groups() -> tuple[AiModelGroupSpec, ...]:
    return tuple(_MODEL_GROUPS[gid] for gid in _MODEL_GROUPS)


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


def deid_option_ready(code: DeidMethodCode) -> bool:
    """
    Whether the option can be selected: its AI feature reports ready.

    Ingest options need no download and are always ready; options no task
    executes are never ready.

    Args:
        code: De-identification option code.

    Returns:
        True when the option may be selected.
    """
    code = DeidMethodCode(code)
    if code in AT_INGEST:
        return True
    if code is DeidMethodCode.CLEAN_PIXEL_DATA:
        return feature_gates.embedded_phi_allowed()
    if code in (DeidMethodCode.CLEAN_STRUCTURED_CONTENT, DeidMethodCode.CLEAN_DESCRIPTORS):
        return feature_gates.report_text_phi_ready()
    if code is DeidMethodCode.CLEAN_VISUAL_FEATURES:
        return feature_gates.face_blur_allowed()
    return False
