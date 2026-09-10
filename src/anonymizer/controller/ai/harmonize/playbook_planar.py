"""Planar (XR / US / MG) metadata Playbook series descriptions.

Isolated from CT/MR :mod:`playbook` SeriesNameV4 emission. Uses DICOM tags and
keywords only — never TotalSegmentator or geometry thickness/contrast.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pydicom import Dataset

from anonymizer.controller.ai.harmonize.planar_profile import (
    PlanarModalityProfile,
    loinc_prefix_for_planar_cohort,
    planar_profile_from_dataset,
)
from anonymizer.controller.ai.harmonize.playbook import map_body_part_from_dicom
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

# Playbook body-part codes → human-readable LOINC-friendly anatomy for planar strings.
_PLAYBOOK_CODE_TO_ANATOMY_LABEL: dict[str, str] = {
    "Brain": "Head",
    "Head": "Head",
    "Neck": "Neck",
    "Ch": "Chest",
    "Abd": "Abdomen",
    "Pel": "Pelvis",
    "AbdPel": "Abdomen Pelvis",
    "CAP": "Chest Abdomen Pelvis",
    "Spine": "Spine",
    "CSp": "Cervical spine",
    "TSp": "Thoracic spine",
    "LSp": "Lumbar spine",
    "Breast": "Breast",
    "UExt": "Upper extremity",
    "LExt": "Lower extremity",
    "Hand": "Hand",
    "Wrist": "Wrist",
    "Elbow": "Elbow",
    "Shoulder": "Shoulder",
    "Hip": "Hip",
    "Knee": "Knee",
    "Ankle": "Ankle",
    "Foot": "Foot",
}

_EXTRA_BODY_PART_EXACT: dict[str, str] = {
    "HAND": "Hand",
    "WRIST": "Wrist",
    "ELBOW": "Elbow",
    "SHOULDER": "Shoulder",
    "HIP": "Hip",
    "KNEE": "Knee",
    "ANKLE": "Ankle",
    "FOOT": "Foot",
    "FINGER": "Hand",
    "TOE": "Foot",
    "SKULL": "Head",
    "FACIAL": "Head",
    "SINUS": "Head",
    "RIB": "Chest",
    "RIBS": "Chest",
    "CLAVICLE": "Shoulder",
    "HUMERUS": "Upper extremity",
    "FEMUR": "Lower extremity",
    "TIBIA": "Lower extremity",
    "LIVER": "Abdomen",
    "KIDNEY": "Abdomen",
    "RENAL": "Abdomen",
    "GALLBLADDER": "Abdomen",
    "THYROID": "Neck",
    "CAROTID": "Neck",
    "SCROTUM": "Pelvis",
    "PROSTATE": "Pelvis",
    "UTERUS": "Pelvis",
    "OVARY": "Pelvis",
    "OB": "Pelvis",
}

_EXTRA_BODY_PART_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("HAND", "FINGER", "DIGIT"), "Hand"),
    (("WRIST",), "Wrist"),
    (("ELBOW",), "Elbow"),
    (("SHOULDER", "CLAVICLE", "AC JOINT"), "Shoulder"),
    (("HIP", "PELVIS"), "Hip"),
    (("KNEE", "PATELLA"), "Knee"),
    (("ANKLE",), "Ankle"),
    (("FOOT", "TOE", "HEEL"), "Foot"),
    (("LIVER", "HEPATIC", "RUQ"), "Abdomen"),
    (("KIDNEY", "RENAL", "HYDRONEPH"), "Abdomen"),
    (("THYROID",), "Neck"),
    (("CAROTID",), "Neck"),
    (("BREAST", "MAMM"), "Breast"),
    (("CHEST", "THORAX", "LUNG", "CXR", "PA AND LAT"), "Chest"),
    (("ABDOMEN", "ABD", "KUB"), "Abdomen"),
    (("HEAD", "SKULL", "SINUS", "FACIAL"), "Head"),
)

_XR_VIEW_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("PA AND LAT", "PA/LAT", "2V", "2 V", "TWO VIEW"), "2V"),
    (("3V", "3 V", "THREE VIEW"), "3V"),
    (("LATERAL", " LAT", "LAT "), "Lat"),
    (("OBLIQUE", "OBL"), "Obl"),
    (("AP ", " AP", "ANTEROPOSTERIOR"), "AP"),
    (("PA ", " PA", "POSTEROANTERIOR"), "PA"),
)

_MG_VIEW_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("MLO", "MEDIOLATERAL OBLIQUE"), "MLO"),
    (("CC", "CRANIOCAUDAL"), "CC"),
    (("ML ", "MEDIOLATERAL"), "ML"),
    (("LM ", "LATEROMEDIAL"), "LM"),
    (("XCCL",), "XCCL"),
    (("XCCM",), "XCCM"),
)

_LATERALITY_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("BILAT", "BILATERAL", " BOTH"), "Bilat"),
    (("LEFT", " LT", "LT ", " L "), "L"),
    (("RIGHT", " RT", "RT ", " R "), "R"),
)

_DOPPLER_KEYWORDS: tuple[str, ...] = (
    "DOPPLER",
    "DUPLEX",
    "COLOR FLOW",
    "SPECTRAL",
    "PWD",
    "CFI",
)

_DBT_KEYWORDS: tuple[str, ...] = ("DBT", "TOMO", "TOMOSYNTHESIS", "3D MAMMO")
_FFD_KEYWORDS: tuple[str, ...] = ("FFD", "FFDM", "FULL FIELD")


@dataclass(frozen=True)
class PlanarPlaybookAttributes:
    """Attributes for a planar Harmonize series description."""

    cohort: str
    body_part_label: str
    laterality_code: str = ""
    view_code: str = ""
    mode_code: str = ""  # e.g. Doppler
    technique_code: str = ""  # DBT / FFD for MG
    body_part_evidence: str = ""
    laterality_evidence: str = ""
    view_evidence: str = ""
    mode_evidence: str = ""
    body_part_source: str = "DICOM"  # DICOM | pixel | fused
    pixel_body_part_label: str = ""
    pixel_body_part_confidence: float | None = None
    view_source: str = "DICOM"  # DICOM | pixel | fused
    pixel_view_code: str = ""
    pixel_view_confidence: float | None = None
    rotation_label: str = ""
    rotation_confidence: float | None = None


def _metadata_blob(ds: Dataset) -> str:
    parts = [
        str(ds.get(keyword, "") or "")
        for keyword in (
            "BodyPartExamined",
            "SeriesDescription",
            "StudyDescription",
            "ProtocolName",
            "ViewPosition",
            "ImageLaterality",
            "Laterality",
        )
    ]
    return " ".join(p for p in parts if p).upper()


def _map_planar_body_part_label(ds: Dataset) -> tuple[str, str]:
    """Return (anatomy label, evidence)."""
    body_part_examined = str(ds.get("BodyPartExamined", "") or "").strip().upper()
    if body_part_examined:
        compact = body_part_examined.replace(" ", "")
        extra = _EXTRA_BODY_PART_EXACT.get(compact)
        if extra is not None:
            return extra, f"BodyPartExamined={body_part_examined}"
        try:
            code = map_body_part_from_dicom(ds)
            label = _PLAYBOOK_CODE_TO_ANATOMY_LABEL.get(code, code)
            return label, f"BodyPartExamined→{code}"
        except ValueError:
            pass

    blob = _metadata_blob(ds)
    for keywords, label in _EXTRA_BODY_PART_KEYWORDS:
        if any(keyword in blob for keyword in keywords):
            return label, f"keyword:{keywords[0]}"

    # Fall back to CT/MR localizer mapper (may raise).
    try:
        code = map_body_part_from_dicom(ds)
        label = _PLAYBOOK_CODE_TO_ANATOMY_LABEL.get(code, code)
        return label, f"playbook:{code}"
    except ValueError as exc:
        raise ValueError(
            "Could not determine body part from DICOM metadata for planar Harmonize"
        ) from exc


def _map_laterality(ds: Dataset, blob: str) -> tuple[str, str]:
    image_lat = str(ds.get("ImageLaterality", "") or ds.get("Laterality", "") or "").strip().upper()
    if image_lat in {"L", "LEFT"}:
        return "L", f"ImageLaterality={image_lat}"
    if image_lat in {"R", "RIGHT"}:
        return "R", f"ImageLaterality={image_lat}"
    if image_lat in {"B", "U", "BOTH", "BILATERAL"}:
        return "Bilat", f"ImageLaterality={image_lat}"

    for keywords, code in _LATERALITY_KEYWORDS:
        if any(keyword in blob for keyword in keywords):
            return code, f"keyword:{keywords[0].strip()}"
    return "", ""


def _map_xr_view(blob: str, ds: Dataset) -> tuple[str, str]:
    view_pos = str(ds.get("ViewPosition", "") or "").strip().upper()
    if view_pos in {"PA", "AP", "LL", "RL", "LATERAL", "LAT"}:
        code = "Lat" if view_pos in {"LL", "RL", "LATERAL", "LAT"} else view_pos
        return code, f"ViewPosition={view_pos}"
    for keywords, code in _XR_VIEW_KEYWORDS:
        if any(keyword in blob for keyword in keywords):
            return code, f"keyword:{keywords[0].strip()}"
    return "", ""


def _map_mg_view(ds: Dataset, blob: str) -> tuple[str, str]:
    view_pos = str(ds.get("ViewPosition", "") or "").strip().upper()
    if view_pos:
        for keywords, code in _MG_VIEW_KEYWORDS:
            if any(keyword in view_pos for keyword in keywords):
                return code, f"ViewPosition={view_pos}"
    # ViewCodeSequence CodeMeaning / CodeValue
    try:
        seq = ds.get("ViewCodeSequence")
        if seq:
            item = seq[0]
            meaning = str(getattr(item, "CodeMeaning", "") or "").upper()
            value = str(getattr(item, "CodeValue", "") or "").upper()
            combined = f"{meaning} {value}"
            for keywords, code in _MG_VIEW_KEYWORDS:
                if any(keyword in combined for keyword in keywords):
                    return code, f"ViewCodeSequence={meaning or value}"
    except Exception:
        logger.debug("ViewCodeSequence parse failed", exc_info=True)

    for keywords, code in _MG_VIEW_KEYWORDS:
        if any(keyword in blob for keyword in keywords):
            return code, f"keyword:{keywords[0]}"
    return "", ""


def _map_us_mode(blob: str) -> tuple[str, str]:
    if any(keyword in blob for keyword in _DOPPLER_KEYWORDS):
        return "Doppler", "keyword:DOPPLER"
    return "", ""


def _map_mg_technique(blob: str) -> tuple[str, str]:
    if any(keyword in blob for keyword in _DBT_KEYWORDS):
        return "DBT", "keyword:DBT"
    if any(keyword in blob for keyword in _FFD_KEYWORDS):
        return "FFD", "keyword:FFD"
    return "", ""


def build_planar_playbook_attributes(
    ds: Dataset,
    *,
    pixel_pred: object | None = None,
    pixel_view_pred: object | None = None,
) -> PlanarPlaybookAttributes:
    profile = planar_profile_from_dataset(ds)
    if profile is None:
        raise ValueError("Not a planar Harmonize modality (XR/US/MG)")

    blob = _metadata_blob(ds)
    dicom_label: str | None
    dicom_ev: str
    try:
        dicom_label, dicom_ev = _map_planar_body_part_label(ds)
    except ValueError:
        dicom_label, dicom_ev = None, ""

    body_source = "DICOM"
    pixel_label = ""
    pixel_conf: float | None = None

    if profile.cohort == "XR" and pixel_pred is not None:
        from anonymizer.controller.ai.harmonize.xp_bodypart.fuse import fuse_planar_anatomy
        from anonymizer.controller.ai.harmonize.xp_bodypart.predict import XpBodypartPrediction

        if not isinstance(pixel_pred, XpBodypartPrediction):
            raise TypeError("pixel_pred must be XpBodypartPrediction or None")
        fused = fuse_planar_anatomy(
            dicom_label=dicom_label,
            dicom_evidence=dicom_ev,
            pixel_pred=pixel_pred,
        )
        body_label = fused.label
        body_ev = fused.evidence
        body_source = fused.source
        pixel_label = fused.pixel_label or ""
        pixel_conf = fused.pixel_confidence
    elif dicom_label is None:
        raise ValueError(
            "Could not determine body part from DICOM metadata for planar Harmonize"
        )
    else:
        body_label = dicom_label
        body_ev = dicom_ev

    laterality, lat_ev = _map_laterality(ds, blob)

    view, view_ev = "", ""
    view_source = "DICOM"
    pixel_view = ""
    pixel_view_conf: float | None = None
    rotation_label = ""
    rotation_conf: float | None = None
    mode, mode_ev = "", ""
    technique, tech_ev = "", ""

    if profile.cohort == "XR":
        view, view_ev = _map_xr_view(blob, ds)
        if pixel_view_pred is not None:
            from anonymizer.controller.ai.harmonize.cxp_view.fuse import fuse_xr_view
            from anonymizer.controller.ai.harmonize.cxp_view.predict import CxpViewPrediction

            if not isinstance(pixel_view_pred, CxpViewPrediction):
                raise TypeError("pixel_view_pred must be CxpViewPrediction or None")
            fused_view = fuse_xr_view(
                dicom_view=view or None,
                dicom_evidence=view_ev,
                pixel_pred=pixel_view_pred,
            )
            view = fused_view.view_code
            view_ev = fused_view.evidence
            view_source = fused_view.source
            pixel_view = fused_view.pixel_view_code or ""
            pixel_view_conf = fused_view.pixel_view_confidence
            rotation_label = fused_view.rotation_label or ""
            rotation_conf = fused_view.rotation_confidence
    elif profile.cohort == "US":
        mode, mode_ev = _map_us_mode(blob)
    elif profile.cohort == "MG":
        if not body_label or body_label == "Head":
            body_label = "Breast"
            body_ev = body_ev or "default:Breast"
            body_source = "DICOM"
        view, view_ev = _map_mg_view(ds, blob)
        technique, tech_ev = _map_mg_technique(blob)
        if not laterality:
            laterality, lat_ev = "Bilat", "default:screening"

    return PlanarPlaybookAttributes(
        cohort=profile.cohort,
        body_part_label=body_label,
        laterality_code=laterality,
        view_code=view,
        mode_code=mode,
        technique_code=technique,
        body_part_evidence=body_ev,
        laterality_evidence=lat_ev or tech_ev,
        view_evidence=view_ev,
        mode_evidence=mode_ev,
        body_part_source=body_source,
        pixel_body_part_label=pixel_label,
        pixel_body_part_confidence=pixel_conf,
        view_source=view_source,
        pixel_view_code=pixel_view,
        pixel_view_confidence=pixel_view_conf,
        rotation_label=rotation_label,
        rotation_confidence=rotation_conf,
    )


def format_planar_series_description(attributes: PlanarPlaybookAttributes) -> str:
    """Emit modality-free planar series description."""
    parts: list[str] = []
    if attributes.mode_code:
        parts.append(attributes.mode_code)
    parts.append(attributes.body_part_label)
    if attributes.laterality_code and attributes.cohort in {"XR", "MG"}:
        parts.append(attributes.laterality_code)
    if attributes.view_code:
        parts.append(attributes.view_code)
    return " ".join(p for p in parts if p).strip()


def build_planar_harmonized_series_description(
    ds: Dataset,
    *,
    pixel_pred: object | None = None,
    pixel_view_pred: object | None = None,
) -> tuple[str, PlanarPlaybookAttributes]:
    attributes = build_planar_playbook_attributes(
        ds, pixel_pred=pixel_pred, pixel_view_pred=pixel_view_pred
    )
    description = format_planar_series_description(attributes)
    if not description:
        raise ValueError("Empty planar Harmonize series description")
    return description, attributes


def planar_loinc_prefix_from_attributes(
    attributes: PlanarPlaybookAttributes,
    profile: PlanarModalityProfile | None = None,
) -> str:
    cohort = attributes.cohort
    return loinc_prefix_for_planar_cohort(
        cohort,
        doppler=attributes.mode_code == "Doppler",
        dbt=attributes.technique_code == "DBT",
        ffd=attributes.technique_code == "FFD",
    )


def planar_loinc_prefix_for_series_descriptions(
    cohort: str,
    series_descriptions: list[str] | tuple[str, ...],
) -> str:
    """Choose LOINC prefix from cohort + emitted planar series strings."""
    joined = " ".join(series_descriptions).upper()
    if cohort == "US" and "DOPPLER" in joined:
        return "US.doppler "
    if cohort == "MG" and re.search(r"\bDBT\b", joined):
        return "DBT "
    if cohort == "MG" and re.search(r"\bFFD\b", joined):
        return "FFD "
    return loinc_prefix_for_planar_cohort(cohort)


def _display_dicom_source() -> str:
    return _("DICOM metadata")


def _display_body_part_source(source: str) -> str:
    """Map internal fusion codes to CT-style model/source labels."""
    if source == "pixel":
        return _("Xp-Bodypart")
    if source == "fused":
        return _("Xp-Bodypart + DICOM")
    return _display_dicom_source()


def _display_view_source(source: str) -> str:
    if source == "pixel":
        return _("CXp-Projection-Rotation")
    if source == "fused":
        return _("CXp-Projection-Rotation + DICOM")
    return _display_dicom_source()


def _format_confidence_evidence(label: str, confidence: float | None) -> str:
    if confidence is None:
        return label or "—"
    return f"{label} · {confidence * 100.0:.2f}% " + _("confidence")


def planar_harmonize_analysis_rows(
    attributes: PlanarPlaybookAttributes,
) -> list[tuple[str, str, str, str, str]]:
    """Rows for Harmonize Playbook table: (element, code, value, evidence, source).

    Source names the concrete model (like CT's ``TotalSegmentator anatomy``), not
    generic ``pixel`` / ``planar`` tokens.
    """
    rows: list[tuple[str, str, str, str, str]] = [
        (
            _("Cohort"),
            attributes.cohort,
            attributes.cohort,
            _("CR/DX/US/MG planar cohort from Modality"),
            _("RadLex Playbook"),
        ),
        (
            _("Body Part"),
            attributes.body_part_label,
            attributes.body_part_label,
            attributes.body_part_evidence or "—",
            _display_body_part_source(attributes.body_part_source or "DICOM"),
        ),
    ]
    if attributes.laterality_code:
        rows.append(
            (
                _("Laterality"),
                attributes.laterality_code,
                attributes.laterality_code,
                attributes.laterality_evidence or "—",
                _display_dicom_source(),
            )
        )
    if attributes.view_code:
        rows.append(
            (
                _("View"),
                attributes.view_code,
                attributes.view_code,
                attributes.view_evidence or "—",
                _display_view_source(attributes.view_source or "DICOM"),
            )
        )
    if attributes.rotation_label:
        rows.append(
            (
                _("Rotation"),
                attributes.rotation_label,
                attributes.rotation_label,
                _format_confidence_evidence(
                    attributes.rotation_label, attributes.rotation_confidence
                ),
                _("CXp-Projection-Rotation"),
            )
        )
    if attributes.mode_code:
        rows.append(
            (
                _("Mode"),
                attributes.mode_code,
                attributes.mode_code,
                attributes.mode_evidence or "—",
                _display_dicom_source(),
            )
        )
    if attributes.technique_code:
        rows.append(
            (
                _("Technique"),
                attributes.technique_code,
                attributes.technique_code,
                attributes.laterality_evidence or "—",
                _display_dicom_source(),
            )
        )
    return rows
