"""JSON configuration for headless AI batch processing.

Mirrors the GUI AI Batch dialog: features.embedded_phi (pixel / metadata /
reports), features.harmonize, features.face_blur. OCR knobs live under pixel
only; NER replace modes live under metadata and reports.

Public API
----------
AiBatchConfigError
    Invalid AI batch configuration or prerequisites.

AiBatchStudyRef
    One study selection for headless studies lists.

EmbeddedPhiPixelOptions
    Pixel OCR knobs (removal_method, remove_scope, match_mode, use_exclude_areas).

EmbeddedPhiTextOptions
    Metadata or Reports NER knobs (enabled, replace_mode).

EmbeddedPhiFeatureOptions
    Embedded PHI feature (pixel / metadata / reports).

HarmonizeFeatureOptions
    Harmonize feature knobs.

FaceBlurFeatureOptions
    Face Blur feature knobs.

AiBatchConfig
    Headless AI batch configuration (nested features).

validate_ai_batch_config_gates(config) -> None
    Fail fast when selected features lack installed models.

enumerate_studies_from_images_dir(images_dir) -> list[tuple[str, str]]
    Walk public/ for (patient_id, study_uid) pairs.

resolve_ai_batch_studies(config, *, images_dir, anon_model) -> list[tuple[str, str]]
    Resolve studies from config ("all" or explicit refs).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Self

from anonymizer.controller.ai.batch_process import AiBatchAlgorithm, AiBatchProcessOptions
from anonymizer.controller.ai.blur_face import FaceBlurMode
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import PhiMatchMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import PixelPhiRemovalMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrRemoveMode
from anonymizer.controller.ai.feature_availability import (
    brain_structures_allowed,
    embedded_phi_allowed,
    face_blur_allowed,
    harmonize_allowed,
)
from anonymizer.controller.ai.tseg.config import (
    CT_SEGMENTATION_MODE_KEY,
    MR_SEGMENTATION_MODE_KEY,
    set_ct_segmentation_mode,
    set_mr_segmentation_mode,
)
from anonymizer.controller.phi.phi_io import build_phi_index
from anonymizer.model.anonymizer import AnonymizerModel

ReplaceMode = Literal["blank", "synth"]


class AiBatchConfigError(ValueError):
    """Invalid AI batch configuration or prerequisites."""


@dataclass(frozen=True)
class AiBatchStudyRef:
    patient_id: str
    study_uid: str


@dataclass(frozen=True)
class EmbeddedPhiPixelOptions:
    enabled: bool = True
    removal_method: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT
    remove_scope: OcrRemoveMode = OcrRemoveMode.NON_WHITELISTED
    match_mode: PhiMatchMode | None = None
    use_exclude_areas: bool = False


@dataclass(frozen=True)
class EmbeddedPhiTextOptions:
    enabled: bool = True
    replace_mode: ReplaceMode = "blank"


@dataclass(frozen=True)
class EmbeddedPhiFeatureOptions:
    enabled: bool = False
    pixel: EmbeddedPhiPixelOptions = field(default_factory=EmbeddedPhiPixelOptions)
    metadata: EmbeddedPhiTextOptions = field(default_factory=EmbeddedPhiTextOptions)
    reports: EmbeddedPhiTextOptions = field(default_factory=EmbeddedPhiTextOptions)


@dataclass(frozen=True)
class HarmonizeFeatureOptions:
    enabled: bool = False
    include_brain_structures: bool = False
    prefer_description_mappings: bool = True


@dataclass(frozen=True)
class FaceBlurFeatureOptions:
    enabled: bool = False
    blur_mode: FaceBlurMode = FaceBlurMode.GAUSSIAN


@dataclass(frozen=True)
class AiBatchConfig:
    embedded_phi: EmbeddedPhiFeatureOptions = field(default_factory=EmbeddedPhiFeatureOptions)
    harmonize: HarmonizeFeatureOptions = field(default_factory=HarmonizeFeatureOptions)
    face_blur: FaceBlurFeatureOptions = field(default_factory=FaceBlurFeatureOptions)
    series_description_overrides: Mapping[str, str] = field(default_factory=dict)
    study_loinc_overrides: Mapping[str, str] = field(default_factory=dict)
    ct_segmentation_mode: str | None = None
    mr_segmentation_mode: str | None = None
    studies: Literal["all"] | tuple[AiBatchStudyRef, ...] = "all"
    skip_already_processed: bool = True

    @property
    def algorithms(self) -> tuple[AiBatchAlgorithm, ...]:
        """Selected algorithms in canonical GUI order."""
        selected: list[AiBatchAlgorithm] = []
        if self.embedded_phi.enabled:
            selected.append(AiBatchAlgorithm.REMOVE_PIXEL_PHI)
        if self.harmonize.enabled:
            selected.append(AiBatchAlgorithm.HARMONIZE)
        if self.face_blur.enabled:
            selected.append(AiBatchAlgorithm.FACE_BLUR)
        return tuple(selected)

    def to_options(self) -> AiBatchProcessOptions:
        return AiBatchProcessOptions(
            algorithms=self.algorithms,
            blur_mode=self.face_blur.blur_mode,
            pixel_phi_removal_mode=self.embedded_phi.pixel.removal_method,
            ocr_remove_mode=self.embedded_phi.pixel.remove_scope,
            phi_match_mode=self.embedded_phi.pixel.match_mode,
            ocr_use_exclude_areas=self.embedded_phi.pixel.use_exclude_areas,
            include_brain_structures=self.harmonize.include_brain_structures,
            prefer_description_mappings=self.harmonize.prefer_description_mappings,
            series_description_overrides=dict(self.series_description_overrides),
            study_loinc_overrides=dict(self.study_loinc_overrides),
            embedded_phi_pixel_enabled=self.embedded_phi.pixel.enabled,
            embedded_phi_metadata_enabled=self.embedded_phi.metadata.enabled,
            embedded_phi_reports_enabled=self.embedded_phi.reports.enabled,
            metadata_replace_mode=self.embedded_phi.metadata.replace_mode,
            reports_replace_mode=self.embedded_phi.reports.replace_mode,
        )

    def apply_segmentation_modes(self) -> None:
        if self.ct_segmentation_mode is not None:
            set_ct_segmentation_mode(self.ct_segmentation_mode)
        if self.mr_segmentation_mode is not None:
            set_mr_segmentation_mode(self.mr_segmentation_mode)

    def to_dict(self) -> dict[str, Any]:
        studies: Any
        if self.studies == "all":
            studies = "all"
        else:
            studies = [
                {"patient_id": ref.patient_id, "study_uid": ref.study_uid}
                for ref in self.studies
            ]
        payload: dict[str, Any] = {
            "features": {
                "embedded_phi": {
                    "enabled": self.embedded_phi.enabled,
                    "pixel": {
                        "enabled": self.embedded_phi.pixel.enabled,
                        "removal_method": self.embedded_phi.pixel.removal_method.value,
                        "remove_scope": self.embedded_phi.pixel.remove_scope.value,
                        "match_mode": (
                            self.embedded_phi.pixel.match_mode.value
                            if self.embedded_phi.pixel.match_mode is not None
                            else None
                        ),
                        "use_exclude_areas": self.embedded_phi.pixel.use_exclude_areas,
                    },
                    "metadata": {
                        "enabled": self.embedded_phi.metadata.enabled,
                        "replace_mode": self.embedded_phi.metadata.replace_mode,
                    },
                    "reports": {
                        "enabled": self.embedded_phi.reports.enabled,
                        "replace_mode": self.embedded_phi.reports.replace_mode,
                    },
                },
                "harmonize": {
                    "enabled": self.harmonize.enabled,
                    "include_brain_structures": self.harmonize.include_brain_structures,
                    "prefer_description_mappings": self.harmonize.prefer_description_mappings,
                },
                "face_blur": {
                    "enabled": self.face_blur.enabled,
                    "blur_mode": self.face_blur.blur_mode.value,
                },
            },
            "studies": studies,
            "skip_already_processed": self.skip_already_processed,
        }
        if self.ct_segmentation_mode is not None:
            payload[CT_SEGMENTATION_MODE_KEY] = self.ct_segmentation_mode
        if self.mr_segmentation_mode is not None:
            payload[MR_SEGMENTATION_MODE_KEY] = self.mr_segmentation_mode
        return payload

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        if not isinstance(data, dict):
            raise AiBatchConfigError("AI batch config must be a JSON object")

        features_raw = data.get("features")
        if not isinstance(features_raw, dict):
            raise AiBatchConfigError("features must be an object")

        studies = _parse_studies(data.get("studies", "all"))
        skip_already_processed = _parse_bool(
            data.get("skip_already_processed", True), field="skip_already_processed"
        )
        if not skip_already_processed:
            raise AiBatchConfigError("skip_already_processed: false is not supported")

        embedded_phi, harmonize, face_blur = _parse_features(features_raw)
        if not (embedded_phi.enabled or harmonize.enabled or face_blur.enabled):
            raise AiBatchConfigError("at least one feature must be enabled")

        return cls(
            embedded_phi=embedded_phi,
            harmonize=harmonize,
            face_blur=face_blur,
            ct_segmentation_mode=_optional_str(data.get(CT_SEGMENTATION_MODE_KEY)),
            mr_segmentation_mode=_optional_str(data.get(MR_SEGMENTATION_MODE_KEY)),
            studies=studies,
            skip_already_processed=skip_already_processed,
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AiBatchConfigError(f"Invalid AI batch JSON: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_path(cls, path: Path) -> Self:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AiBatchConfigError(f"Could not read AI batch config: {path}") from exc
        return cls.from_json(text)


def _parse_features(
    features: dict[str, Any],
) -> tuple[EmbeddedPhiFeatureOptions, HarmonizeFeatureOptions, FaceBlurFeatureOptions]:
    ep_raw = features.get("embedded_phi")
    if ep_raw is None:
        embedded_phi = EmbeddedPhiFeatureOptions()
    elif not isinstance(ep_raw, dict):
        raise AiBatchConfigError("features.embedded_phi must be an object")
    else:
        embedded_phi = _parse_embedded_phi(ep_raw)

    hz_raw = features.get("harmonize")
    if hz_raw is None:
        harmonize = HarmonizeFeatureOptions()
    elif not isinstance(hz_raw, dict):
        raise AiBatchConfigError("features.harmonize must be an object")
    else:
        harmonize = HarmonizeFeatureOptions(
            enabled=_parse_bool(hz_raw.get("enabled", False), field="features.harmonize.enabled"),
            include_brain_structures=_parse_bool(
                hz_raw.get("include_brain_structures", False),
                field="features.harmonize.include_brain_structures",
            ),
            prefer_description_mappings=_parse_bool(
                hz_raw.get("prefer_description_mappings", True),
                field="features.harmonize.prefer_description_mappings",
            ),
        )

    fb_raw = features.get("face_blur")
    if fb_raw is None:
        face_blur = FaceBlurFeatureOptions()
    elif not isinstance(fb_raw, dict):
        raise AiBatchConfigError("features.face_blur must be an object")
    else:
        face_blur = FaceBlurFeatureOptions(
            enabled=_parse_bool(fb_raw.get("enabled", False), field="features.face_blur.enabled"),
            blur_mode=_parse_blur_mode(fb_raw.get("blur_mode", FaceBlurMode.GAUSSIAN.value)),
        )
    return embedded_phi, harmonize, face_blur


def _parse_embedded_phi(raw: dict[str, Any]) -> EmbeddedPhiFeatureOptions:
    enabled = _parse_bool(raw.get("enabled", False), field="features.embedded_phi.enabled")
    pixel_raw = raw.get("pixel")
    if pixel_raw is None:
        pixel = EmbeddedPhiPixelOptions()
    elif not isinstance(pixel_raw, dict):
        raise AiBatchConfigError("features.embedded_phi.pixel must be an object")
    else:
        pixel = EmbeddedPhiPixelOptions(
            enabled=_parse_bool(pixel_raw.get("enabled", True), field="features.embedded_phi.pixel.enabled"),
            removal_method=_parse_removal_method(
                pixel_raw.get("removal_method", PixelPhiRemovalMode.BLACKOUT.value)
            ),
            remove_scope=_parse_remove_scope(
                pixel_raw.get("remove_scope", OcrRemoveMode.NON_WHITELISTED.value)
            ),
            match_mode=_parse_phi_match_mode(
                pixel_raw.get("match_mode"),
                field="features.embedded_phi.pixel.match_mode",
            ),
            use_exclude_areas=_parse_bool(
                pixel_raw.get("use_exclude_areas", False),
                field="features.embedded_phi.pixel.use_exclude_areas",
            ),
        )
    metadata = _parse_text_options(raw.get("metadata"), path="features.embedded_phi.metadata")
    reports = _parse_text_options(raw.get("reports"), path="features.embedded_phi.reports")
    return EmbeddedPhiFeatureOptions(
        enabled=enabled,
        pixel=pixel,
        metadata=metadata,
        reports=reports,
    )


def _parse_text_options(raw: object, *, path: str) -> EmbeddedPhiTextOptions:
    if raw is None:
        return EmbeddedPhiTextOptions()
    if not isinstance(raw, dict):
        raise AiBatchConfigError(f"{path} must be an object")
    return EmbeddedPhiTextOptions(
        enabled=_parse_bool(raw.get("enabled", True), field=f"{path}.enabled"),
        replace_mode=_parse_replace_mode(raw.get("replace_mode", "blank"), field=f"{path}.replace_mode"),
    )


def _parse_blur_mode(value: object) -> FaceBlurMode:
    text = str(value or "").strip().lower()
    try:
        return FaceBlurMode(text)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in FaceBlurMode)
        raise AiBatchConfigError(f"Unknown blur_mode {value!r}; expected one of: {allowed}") from exc


def _parse_removal_method(value: object) -> PixelPhiRemovalMode:
    text = str(value or PixelPhiRemovalMode.BLACKOUT.value).strip().lower()
    for mode in PixelPhiRemovalMode:
        if text == mode.value:
            return mode
    allowed = ", ".join(mode.value for mode in PixelPhiRemovalMode)
    raise AiBatchConfigError(f"Unknown removal_method {value!r}; expected one of: {allowed}")


def _parse_remove_scope(value: object) -> OcrRemoveMode:
    text = str(value or OcrRemoveMode.NON_WHITELISTED.value).strip().lower()
    for mode in OcrRemoveMode:
        if text == mode.value:
            return mode
    allowed = ", ".join(mode.value for mode in OcrRemoveMode)
    raise AiBatchConfigError(f"Unknown remove_scope {value!r}; expected one of: {allowed}")


def _parse_phi_match_mode(value: object, *, field: str) -> PhiMatchMode | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    for mode in PhiMatchMode:
        if text == mode.value:
            return mode
    allowed = ", ".join(mode.value for mode in PhiMatchMode)
    raise AiBatchConfigError(f"{field} must be one of: {allowed}")


def _parse_replace_mode(value: object, *, field: str) -> ReplaceMode:
    text = str(value or "blank").strip().lower()
    if text in ("blank", "synth"):
        return text  # type: ignore[return-value]
    raise AiBatchConfigError(f"{field} must be 'blank' or 'synth'")


def _parse_bool(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise AiBatchConfigError(f"{field} must be a boolean")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_studies(value: object) -> Literal["all"] | tuple[AiBatchStudyRef, ...]:
    if value == "all":
        return "all"
    if not isinstance(value, list) or not value:
        raise AiBatchConfigError('studies must be "all" or a non-empty list of {patient_id, study_uid} objects')
    refs: list[AiBatchStudyRef] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise AiBatchConfigError(f"studies[{index}] must be an object with patient_id and study_uid")
        patient_id = str(item.get("patient_id", "")).strip()
        study_uid = str(item.get("study_uid", "")).strip()
        if not patient_id or not study_uid:
            raise AiBatchConfigError(f"studies[{index}] requires non-empty patient_id and study_uid")
        refs.append(AiBatchStudyRef(patient_id=patient_id, study_uid=study_uid))
    return tuple(refs)


def validate_ai_batch_config_gates(config: AiBatchConfig) -> None:
    errors: list[str] = []
    for algorithm in config.algorithms:
        if algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI and not embedded_phi_allowed():
            errors.append("embedded_phi: Embedded PHI models are not installed")
        elif algorithm is AiBatchAlgorithm.HARMONIZE and not harmonize_allowed():
            errors.append("harmonize: TotalSegmentator anatomy models are not installed")
        elif algorithm is AiBatchAlgorithm.FACE_BLUR and not face_blur_allowed():
            errors.append("face_blur: face models or license are not available")
    if config.harmonize.include_brain_structures and not brain_structures_allowed():
        errors.append("include_brain_structures: brain structures models or license are not available")
    if errors:
        raise AiBatchConfigError("; ".join(errors))


def enumerate_studies_from_images_dir(images_dir: Path) -> list[tuple[str, str]]:
    if not images_dir.is_dir():
        return []
    studies: list[tuple[str, str]] = []
    for patient_dir in sorted(images_dir.iterdir()):
        if not patient_dir.is_dir() or patient_dir.name.startswith("."):
            continue
        for study_dir in sorted(patient_dir.iterdir()):
            if study_dir.is_dir() and not study_dir.name.startswith("."):
                studies.append((patient_dir.name, study_dir.name))
    return studies


def resolve_ai_batch_studies(
    config: AiBatchConfig,
    *,
    images_dir: Path,
    anon_model: AnonymizerModel,
) -> list[tuple[str, str]]:
    if config.studies != "all":
        studies: list[tuple[str, str]] = []
        for ref in config.studies:
            study_path = images_dir / ref.patient_id / ref.study_uid
            if not study_path.is_dir():
                raise AiBatchConfigError(f"Study directory not found: {study_path}")
            studies.append((ref.patient_id, ref.study_uid))
        return studies

    records = build_phi_index(anon_model) or []
    if records:
        return [(record.anon_patient_id, record.anon_study_uid) for record in records]
    return enumerate_studies_from_images_dir(images_dir)
