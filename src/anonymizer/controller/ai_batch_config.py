"""JSON configuration for headless AI batch processing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from anonymizer.controller.ai.blur_face import FaceBlurMode
from anonymizer.controller.ai.feature_availability import (
    brain_structures_allowed,
    face_blur_allowed,
    harmonize_allowed,
    pixel_phi_allowed,
)
from anonymizer.controller.ai.remove_pixel_phi import PixelPhiRemovalMode
from anonymizer.controller.ai.tseg.config import (
    CT_SEGMENTATION_MODE_KEY,
    MR_SEGMENTATION_MODE_KEY,
    set_ct_segmentation_mode,
    set_mr_segmentation_mode,
)
from anonymizer.controller.ai_batch_process import AiBatchAlgorithm, AiBatchProcessOptions
from anonymizer.controller.phi_io import build_phi_index
from anonymizer.model.anonymizer import AnonymizerModel

_ALGORITHM_ALIASES: dict[str, AiBatchAlgorithm] = {
    "remove_pixel_phi": AiBatchAlgorithm.REMOVE_PIXEL_PHI,
    "removepixelphi": AiBatchAlgorithm.REMOVE_PIXEL_PHI,
    "pixel_phi": AiBatchAlgorithm.REMOVE_PIXEL_PHI,
    "harmonize": AiBatchAlgorithm.HARMONIZE,
    "face_blur": AiBatchAlgorithm.FACE_BLUR,
    "faceblur": AiBatchAlgorithm.FACE_BLUR,
}


class AiBatchConfigError(ValueError):
    """Invalid AI batch configuration or prerequisites."""


@dataclass(frozen=True)
class AiBatchStudyRef:
    patient_id: str
    study_uid: str


@dataclass(frozen=True)
class AiBatchConfig:
    algorithms: tuple[AiBatchAlgorithm, ...]
    blur_mode: FaceBlurMode = FaceBlurMode.GAUSSIAN
    pixel_phi_removal_mode: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT
    use_modality_whitelist: bool = True
    include_brain_structures: bool = False
    ct_segmentation_mode: str | None = None
    mr_segmentation_mode: str | None = None
    studies: Literal["all"] | tuple[AiBatchStudyRef, ...] = "all"
    skip_already_processed: bool = True

    def to_options(self) -> AiBatchProcessOptions:
        return AiBatchProcessOptions(
            algorithms=self.algorithms,
            blur_mode=self.blur_mode,
            pixel_phi_removal_mode=self.pixel_phi_removal_mode,
            use_modality_whitelist=self.use_modality_whitelist,
            include_brain_structures=self.include_brain_structures,
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
            "algorithms": [algorithm.value for algorithm in self.algorithms],
            "blur_mode": self.blur_mode.value,
            "pixel_phi_removal_mode": self.pixel_phi_removal_mode.value,
            "use_modality_whitelist": self.use_modality_whitelist,
            "include_brain_structures": self.include_brain_structures,
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
    def from_dict(cls, data: dict[str, Any]) -> AiBatchConfig:
        if not isinstance(data, dict):
            raise AiBatchConfigError("AI batch config must be a JSON object")

        algorithms = _parse_algorithms(data.get("algorithms"))
        blur_mode = _parse_blur_mode(data.get("blur_mode", FaceBlurMode.GAUSSIAN.value))
        pixel_phi_removal_mode = _parse_pixel_phi_removal_mode(
            data.get("pixel_phi_removal_mode", PixelPhiRemovalMode.BLACKOUT.value)
        )
        use_modality_whitelist = _parse_bool(data.get("use_modality_whitelist", True), field="use_modality_whitelist")
        include_brain_structures = _parse_bool(
            data.get("include_brain_structures", False),
            field="include_brain_structures",
        )
        ct_segmentation_mode = _optional_str(data.get(CT_SEGMENTATION_MODE_KEY))
        mr_segmentation_mode = _optional_str(data.get(MR_SEGMENTATION_MODE_KEY))
        studies = _parse_studies(data.get("studies", "all"))
        skip_already_processed = _parse_bool(data.get("skip_already_processed", True), field="skip_already_processed")
        if not skip_already_processed:
            raise AiBatchConfigError("skip_already_processed: false is not supported")

        return cls(
            algorithms=algorithms,
            blur_mode=blur_mode,
            pixel_phi_removal_mode=pixel_phi_removal_mode,
            use_modality_whitelist=use_modality_whitelist,
            include_brain_structures=include_brain_structures,
            ct_segmentation_mode=ct_segmentation_mode,
            mr_segmentation_mode=mr_segmentation_mode,
            studies=studies,
            skip_already_processed=skip_already_processed,
        )

    @classmethod
    def from_json(cls, text: str) -> AiBatchConfig:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AiBatchConfigError(f"Invalid AI batch JSON: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_path(cls, path: Path) -> AiBatchConfig:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AiBatchConfigError(f"Could not read AI batch config: {path}") from exc
        return cls.from_json(text)


def _parse_algorithms(value: object) -> tuple[AiBatchAlgorithm, ...]:
    if not isinstance(value, list) or not value:
        raise AiBatchConfigError("algorithms must be a non-empty list")
    algorithms: list[AiBatchAlgorithm] = []
    for item in value:
        key = str(item).strip().lower().replace("-", "_").replace(" ", "_")
        if key not in _ALGORITHM_ALIASES:
            allowed = ", ".join(sorted(_ALGORITHM_ALIASES))
            raise AiBatchConfigError(f"Unknown algorithm {item!r}; expected one of: {allowed}")
        algorithm = _ALGORITHM_ALIASES[key]
        if algorithm not in algorithms:
            algorithms.append(algorithm)
    return tuple(algorithms)


def _parse_blur_mode(value: object) -> FaceBlurMode:
    text = str(value or "").strip().lower()
    try:
        return FaceBlurMode(text)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in FaceBlurMode)
        raise AiBatchConfigError(f"Unknown blur_mode {value!r}; expected one of: {allowed}") from exc


def _parse_pixel_phi_removal_mode(value: object) -> PixelPhiRemovalMode:
    text = str(value or "").strip().lower()
    try:
        return PixelPhiRemovalMode(text)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in PixelPhiRemovalMode)
        raise AiBatchConfigError(
            f"Unknown pixel_phi_removal_mode {value!r}; expected one of: {allowed}"
        ) from exc


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
        if algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI and not pixel_phi_allowed():
            errors.append("remove_pixel_phi: OCR models are not installed")
        elif algorithm is AiBatchAlgorithm.HARMONIZE and not harmonize_allowed():
            errors.append("harmonize: TotalSegmentator anatomy models are not installed")
        elif algorithm is AiBatchAlgorithm.FACE_BLUR and not face_blur_allowed():
            errors.append("face_blur: face models or license are not available")
    if config.include_brain_structures and not brain_structures_allowed():
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
