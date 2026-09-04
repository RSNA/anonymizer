"""AI Features catalog: IDs, slim specs, titles, and frozen registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from anonymizer.controller.ai.remove_pixel_phi import download_ocr_models, remove_ocr_models
from anonymizer.controller.ai.tseg.readiness import (
    TsWeightKind,
    download_segmentation_model,
    remove_segmentation_model,
)
from anonymizer.utils.translate import _


class AiFeatureId(StrEnum):
    """Top-level AI Features."""

    REMOVE_PIXEL_PHI = "remove_pixel_phi"
    HARMONIZE = "enable_harmonize"
    FACE_BLUR = "enable_face_blur"
    BRAIN_STRUCTURES = "enable_brain_structures"


class AiModelGroupId(StrEnum):
    """Downloadable model groups shown under a parent feature."""

    OCR = "remove_pixel_phi"
    HARMONIZE_CT = "harmonize_ct_models"
    HARMONIZE_MR = "harmonize_mr_models"
    FACE_CT = "face_ct_models"
    FACE_MR = "face_mr_models"
    BRAIN_STRUCTURES = "enable_brain_structures"


DOWNLOAD_ID_OCR = AiModelGroupId.OCR.value
DOWNLOAD_ID_HARMONIZE_CT = AiModelGroupId.HARMONIZE_CT.value
DOWNLOAD_ID_HARMONIZE_MR = AiModelGroupId.HARMONIZE_MR.value
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
        DOWNLOAD_ID_OCR,
        DOWNLOAD_ID_HARMONIZE_CT,
        DOWNLOAD_ID_HARMONIZE_MR,
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
        AiFeatureId.REMOVE_PIXEL_PHI.value: _("Remove Burnt-in Annotation"),
        AiFeatureId.HARMONIZE.value: _("Harmonize"),
        AiFeatureId.BRAIN_STRUCTURES.value: _("Brain structures"),
        AiFeatureId.FACE_BLUR.value: _("Face De-identify"),
        AiModelGroupId.HARMONIZE_CT.value: _("CT models"),
        AiModelGroupId.HARMONIZE_MR.value: _("MR models"),
        AiModelGroupId.FACE_CT.value: _("CT models"),
        AiModelGroupId.FACE_MR.value: _("MR models"),
    }[key]


def feature_description(key: str) -> str:
    return {
        AiFeatureId.REMOVE_PIXEL_PHI.value: _("OCR burnt-in text removal."),
        AiFeatureId.HARMONIZE.value: _("Standardize SeriesDescription (CT/MR)."),
        AiFeatureId.BRAIN_STRUCTURES.value: _(
            "Optional CT Head detail after total anatomy (academic license)."
        ),
        AiFeatureId.FACE_BLUR.value: _("Blur face on head CT/MR (academic license)."),
    }[key]


def feature_summary(key: str) -> str:
    return {
        AiFeatureId.REMOVE_PIXEL_PHI.value: _("OCR burnt-in text removal."),
        AiFeatureId.HARMONIZE.value: _("RadLex series naming from anatomy."),
        AiModelGroupId.HARMONIZE_CT.value: "",
        AiModelGroupId.HARMONIZE_MR.value: "",
        AiFeatureId.BRAIN_STRUCTURES.value: _("CT Head detail in Harmonize Description."),
        AiFeatureId.FACE_BLUR.value: _("Head CT/MR face de-identify."),
        AiModelGroupId.FACE_CT.value: "",
        AiModelGroupId.FACE_MR.value: "",
    }[key]


def download_ocr() -> object:
    return download_ocr_models()


def remove_ocr() -> None:
    remove_ocr_models()


def download_kind(kind: TsWeightKind) -> object:
    return download_segmentation_model(kind)


def remove_kind(kind: TsWeightKind) -> None:
    remove_segmentation_model(kind)


TOP_LEVEL_FEATURE_IDS: tuple[AiFeatureId, ...] = (
    AiFeatureId.REMOVE_PIXEL_PHI,
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
    return tuple(_MODEL_GROUPS[gid] for gid in AiModelGroupId)
