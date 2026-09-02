"""RadLex Playbook CT series description: codes, TS/geometry mappers, and Harmonize UI text."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from pydicom import Dataset

from anonymizer.controller.ai.tseg.config import MIN_STRUCTURE_VOXELS
from anonymizer.controller.ai.tseg.dicom_geometry import (
    MPR_KEYWORDS,
    RENDER_KEYWORDS,
    SECONDARY_CAPTURE_SOP,
    PlaneLabel,
    SeriesGeometryResult,
    dimensionality_label,
    format_geometry_summary,
    plane_label,
    provenance_label,
)
from anonymizer.controller.ai.tseg.segment import TS_result
from anonymizer.controller.ai.tseg.series_classification import metadata_diagnostic_fallback_allowed
from anonymizer.utils.modalities import is_mr_modality
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

# Playbook body-part codes (RSNA Study-Series / LOINC Radiology Playbook abbreviations).
BODY_PART_PLAYBOOK_CODES: frozenset[str] = frozenset(
    {
        "WB",
        "Brain",
        "Head",
        "Pit",
        "TBone",
        "TMJ",
        "Face",
        "Orbit",
        "Sinuses",
        "NP",
        "OP",
        "Larynx",
        "Neck",
        "Thyroid",
        "Parathyroid",
        "Ch",
        "CAP",
        "Mandible",
        "Heart",
        "Coronary",
        "Breast",
        "Abd",
        "Pel",
        "AbdPel",
        "Aorta",
        "Liver",
        "Kidney",
        "Adrenal",
        "Rectum",
        "Uterus",
        "Fetus",
        "Pros",
        "UExt",
        "Shoulder",
        "Elbow",
        "Wrist",
        "Hand",
        "Finger",
        "LExt",
        "Fem",
        "Hip",
        "Knee",
        "Ankle",
        "Foot",
        "Joints",
        "Spine",
        "CSp",
        "TSp",
        "LSp",
        "Sacrum",
        "SIJ",
        "Brain_Face",
        "Brain_Neck",
        "Brain_Face_Csp",
        "Brain_CSp",
        "CSp_TSp",
        "TSp_LSp",
        "CSp_TSp_LSp",
        "SBTT",
    }
)

ANATOMIC_PLANE_PLAYBOOK_CODES: frozenset[str] = frozenset(
    {"Ax", "Sag", "Cor", "Ax_Obl", "Sag_Obl", "Cor_Obl", "Rad_Obl"}
)

IV_CONTRAST_PLAYBOOK_CODES: frozenset[str] = frozenset(
    {
        "WO",
        "W",
        "Art",
        "Ven",
        "Delay",
        "EarlyArt",
        "LateArt",
        "PulmArt",
        "PortVen",
        "Neph",
        "CortMed",
        "Equil",
        "Excretory",
        "Dyn",
    }
)
# RSNA RadLex Series Playbook IV Contrast Phase vocabulary.

SERIES_TYPE_PLAYBOOK_CODES: frozenset[str] = frozenset(
    {
        "Localizer",
        "Radiation_Dose",
        "Monitoring",
        "Postprocess",
        "Screenshot",
        "Fused",
        "Contrast_Dose",
    }
)

# RSNA RadLex Series Playbook slice-thickness buckets (CT Sandbox / RSNA FAQ).
SLICE_THICKNESS_PLAYBOOK_CODES: frozenset[str] = frozenset({"Recon", "Thin", "Std", "Thick"})
# SeriesNameV4 emits only non-default thickness tokens (Med/Std omitted; Recon omitted in v1).
SLICE_THICKNESS_EMITTED_CODES: frozenset[str] = frozenset({"Thin", "Thick"})
_SLICE_THICKNESS_REGULARITY_MIN = 0.85

SERIES_TYPE_MODIFIER_PLAYBOOK_CODES: frozenset[str] = frozenset({"MPR"})

METADATA_HARMONIZE_SERIES_TYPES: frozenset[str] = SERIES_TYPE_PLAYBOOK_CODES

STRUCTURED_REPORT_SOP_PREFIX = "1.2.840.10008.5.1.4.1.1.88"

_TSEG_REGION_TO_BODY_PART_CODE: dict[str, str] = {
    "Chest": "Ch",
    "Abdomen": "Abd",
}

# DICOM ``BodyPartExamined`` (uppercase) → Playbook body-part code for localizer/scout series.
_DICOM_BODY_PART_EXACT: dict[str, str] = {
    "HEAD": "Brain",
    "BRAIN": "Brain",
    "NECK": "Neck",
    "CHEST": "Ch",
    "CHST": "Ch",
    "THORAX": "Ch",
    "ABDOMEN": "Abd",
    "ABD": "Abd",
    "ABDPELVIS": "AbdPel",
    "ABDPELV": "AbdPel",
    "PELVIS": "Pel",
    "PELV": "Pel",
    "CAP": "CAP",
    "CHESTABDOMENPELVIS": "CAP",
    "SPINE": "Spine",
    "CSPINE": "CSp",
    "TSPINE": "TSp",
    "LSPINE": "LSp",
    "EXTREMITY": "LExt",
    "UPPEREXTREMITY": "UExt",
    "LOWEREXTREMITY": "LExt",
    "BREAST": "Breast",
    "MAMM": "Breast",
}

# Keyword groups searched in DICOM text fields when ``BodyPartExamined`` is absent.
_DICOM_BODY_PART_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("BRAIN", "HEAD"), "Brain"),
    (("CHEST", "THORAX", "CHST", "LUNG"), "Ch"),
    (("ABDPEL", "ABD/PEL", "CAP", "CHESTABD"), "CAP"),
    (("ABDOMEN", "ABD "), "Abd"),
    (("PELVIS", "PELV"), "Pel"),
    (("NECK", "CERVICAL"), "Neck"),
    (("SPINE", "SPINAL"), "Spine"),
    (("CSPINE", "C-SPINE", "C SPINE"), "CSp"),
    (("TSPINE", "T-SPINE", "T SPINE"), "TSp"),
    (("LSPINE", "L-SPINE", "L SPINE"), "LSp"),
    (("BREAST", "MAMM"), "Breast"),
)

# TS ROI structures used to refine Playbook body-part codes within the Head region.
_HEAD_BRAIN_STRUCTURES: tuple[str, ...] = ("brain",)
_HEAD_SKULL_STRUCTURES: tuple[str, ...] = ("skull", "spinal_cord")

_CARDINAL_PLANE_CODES: dict[PlaneLabel, str] = {
    "axial": "Ax",
    "sagittal": "Sag",
    "coronal": "Cor",
}

_TS_CONTRAST_PHASE_TO_CODE: dict[str, str] = {
    "native": "WO",
    "arterial_early": "EarlyArt",
    "arterial_late": "LateArt",
    "portal_venous": "PortVen",
    "arterial": "Art",
    "venous": "Ven",
    "delayed": "Delay",
    "pulmonary_arterial": "PulmArt",
    "nephrogenic": "Neph",
    "cortomedullary": "CortMed",
    "equilibrium": "Equil",
    "excretory": "Excretory",
    "dynamic": "Dyn",
}

# MR has no TotalSegmentator IV-phase classifier; infer W/WO from DICOM headers.
_MR_WITHOUT_CONTRAST_KEYWORDS: tuple[str, ...] = (
    "WITHOUT CONTRAST",
    "W/O CONTRAST",
    "WO CONTRAST",
    "W/O",
    "PRECONTRAST",
    "PRE-CONTRAST",
    "PRE CONTRAST",
    "NONCONTRAST",
    "NON-CONTRAST",
    "NON CONTRAST",
    "PRE GAD",
    "PRE-GAD",
    "NO CONTRAST",
)
_MR_WITH_CONTRAST_KEYWORDS: tuple[str, ...] = (
    "WITH CONTRAST",
    "W/ CONTRAST",
    "W CONTRAST",
    "POST GAD",
    "POST-GAD",
    "GADOLINIUM",
    "POSTCONTRAST",
    "POST-CONTRAST",
    "POST CONTRAST",
    "CONTRAST ENHANCED",
    "CONTRAST-ENHANCED",
    "+C",
    " C+",
    "CE-",
)

_BODY_PART_MSGIDS: dict[str, str] = {
    "Ch": "Chest",
    "Abd": "Abdomen",
    "Head": "Head",
    "Brain": "Brain",
    "CAP": "Chest abdomen pelvis",
}

_PLANE_MSGIDS: dict[str, str] = {
    "Ax": "Axial",
    "Sag": "Sagittal",
    "Cor": "Coronal",
    "Ax_Obl": "Axial oblique",
    "Sag_Obl": "Sagittal oblique",
    "Cor_Obl": "Coronal oblique",
    "Rad_Obl": "Oblique",
}

_IV_CONTRAST_MSGIDS: dict[str, str] = {
    "WO": "Without contrast",
    "W": "With contrast",
    "EarlyArt": "Early arterial",
    "LateArt": "Late arterial",
    "PortVen": "Portal venous",
    "Art": "Arterial",
    "Ven": "Venous",
    "Delay": "Delayed",
    "PulmArt": "Pulmonary arterial",
    "Neph": "Nephrogenic",
    "CortMed": "Cortomedullary",
    "Equil": "Equilibrium",
    "Excretory": "Excretory",
    "Dyn": "Dynamic",
}

_SLICE_THICKNESS_MSGIDS: dict[str, str] = {
    "Recon": "Reconstruction (< 1 mm)",
    "Thin": "Thin ( 1 mm and < 2.5 mm)",
    "Std": "Standard ( 2.5 mm and  5 mm)",
    "Thick": "Thick ( 5 mm)",
}

_SERIES_TYPE_MSGIDS: dict[str, str] = {
    "Localizer": "Exam localizer",
    "Radiation_Dose": "Radiation dose sheet",
    "Monitoring": "Used for tracking the contrast bolus or heart rhythm",
    "Postprocess": "More than plane reformat; includes 3D lab outputs and AI outputs",
    "Screenshot": "Images saved by radiologists",
    "Fused": "PET/CT fusion and multi spectral energies fused together",
    "Contrast_Dose": "Contrast dose sheet",
}

_SERIES_TYPE_MODIFIER_MSGIDS: dict[str, str] = {
    "MPR": "Multiplanar reformat",
}

_RADIATION_DOSE_KEYWORDS: tuple[str, ...] = (
    "DOSE REPORT",
    "RDSR",
    "CTDI",
    "DLP",
    "RADIATION DOSE",
    "RADIATION DOSE REPORT",
)
_CONTRAST_DOSE_KEYWORDS: tuple[str, ...] = (
    "CONTRAST DOSE",
    "CONTRAST DOSE SHEET",
    "INJECTOR DOSE",
    "CONTRAST SHEET",
)
_MONITORING_KEYWORDS: tuple[str, ...] = (
    "BOLUS TRACK",
    "TEST BOLUS",
    "TIMING BOLUS",
    "BOLUS MONITOR",
    "HEART RATE",
    "CARDIAC MONITOR",
    "ECG",
    "RHYTHM",
    "MONITOR",
    "SURVEILLANCE",
)
_FUSED_KEYWORDS: tuple[str, ...] = (
    "FUSION",
    "FUSED",
    "PET/CT",
    "PET CT",
    "REGISTERED",
    "MULTI ENERGY",
    "MULTIENERGY",
    "DUAL ENERGY",
)
_SCREENSHOT_KEYWORDS: tuple[str, ...] = (
    "SCREENSHOT",
    "SCREEN SHOT",
    "SAVE SCREEN",
    "SCREEN CAPTURE",
    "CAPTURED IMAGE",
)


@dataclass(frozen=True)
class MetadataHarmonizeRoute:
    """Build a Playbook description from DICOM metadata without TS anatomy regions."""

    series_type_code: str
    include_plane: bool
    iv_contrast_from_dicom: bool


@dataclass(frozen=True)
class PlaybookHarmonizeAttributes:
    body_part_code: str
    anatomic_plane_code: str
    iv_contrast_code: str
    series_type_code: str
    body_part_confidence: float | None
    plane_confidence: float | None
    contrast_confidence: float | None
    contrast_phase: str
    slice_thickness_code: str = ""
    slice_thickness_mm: float | None = None
    series_type_modifier_code: str = ""


_PLANE_CODE_TO_CARDINAL: dict[str, PlaneLabel] = {
    "Ax": "axial",
    "Sag": "sagittal",
    "Cor": "coronal",
}


def _plane_deviation_from_geometry(
    geometry: SeriesGeometryResult,
    anatomic_plane_code: str,
) -> tuple[float | None, PlaneLabel | None]:
    """Degrees between slice normal and the Playbook reference cardinal axis."""
    angles = geometry.plane_angles_deg
    if not angles:
        return None, None

    base_code = anatomic_plane_code.split("_", maxsplit=1)[0]
    cardinal = _PLANE_CODE_TO_CARDINAL.get(base_code)
    if cardinal is not None and cardinal in angles:
        return angles[cardinal], cardinal

    nearest = min(angles, key=angles.get)
    return angles[nearest], nearest  # type: ignore[return-value]


def _format_region_voxel_fraction(fraction: float | None) -> str:
    if fraction is None:
        return "—"
    return f"{fraction * 100.0:.2f}% " + _("region voxel fraction")


def _format_plane_deviation(
    geometry: SeriesGeometryResult | None,
    anatomic_plane_code: str,
) -> str:
    if geometry is None:
        return "—"
    deviation_deg, cardinal = _plane_deviation_from_geometry(geometry, anatomic_plane_code)
    if deviation_deg is None or cardinal is None:
        return "—"
    return f"{deviation_deg:.1f}° " + _("from") + f" {plane_label(cardinal)}"


def _format_classifier_confidence(probability: float | None) -> str:
    if probability is None:
        return "—"
    return f"{probability * 100.0:.2f}% " + _("confidence")


def _playbook_localized(mapping: dict[str, str], code: str) -> str:
    return _(mapping.get(code, code))


def _humanize_contrast_phase(phase: str) -> str:
    normalized = str(phase or "").strip().lower().replace("_", " ")
    phase_msgids = {
        "native": "Native",
        "arterial": "Arterial",
        "venous": "Venous",
        "delayed": "Delayed",
        "nephrogenic": "Nephrogenic",
        "cortomedullary": "Cortomedullary",
        "equilibrium": "Equilibrium",
        "excretory": "Excretory",
        "dynamic": "Dynamic",
    }
    if normalized in phase_msgids:
        return _(phase_msgids[normalized])
    if normalized:
        return normalized
    return ""


def _playbook_body_part_evidence(
    *,
    tseg: TS_result | None = None,
    attributes: PlaybookHarmonizeAttributes | None = None,
    geometry: SeriesGeometryResult | None = None,
) -> str:
    if tseg is not None and tseg.body_parts_present.strip() and tseg.error is None:
        from anonymizer.controller.ai.tseg.segment import format_anatomy_regions_summary

        return format_anatomy_regions_summary(tseg)
    if attributes is not None:
        if geometry is not None and is_localizer_geometry(geometry) and attributes.body_part_confidence is None:
            return _("Body part from DICOM fields")
        return _format_region_voxel_fraction(attributes.body_part_confidence)
    return "—"


def _playbook_iv_contrast_evidence(
    *,
    phase: str,
    probability: float | None,
    iv_evidence: str | None = None,
) -> str:
    if iv_evidence:
        return iv_evidence
    confidence = _format_classifier_confidence(probability)
    human_phase = _humanize_contrast_phase(phase)
    if human_phase and confidence != "—":
        return f"{human_phase} · {confidence}"
    if human_phase:
        return human_phase
    return confidence


def body_part_label(code: str) -> str:
    return _playbook_localized(_BODY_PART_MSGIDS, code)


def anatomic_plane_label(code: str) -> str:
    return _playbook_localized(_PLANE_MSGIDS, code)


def iv_contrast_label(code: str) -> str:
    return _playbook_localized(_IV_CONTRAST_MSGIDS, code)


def _iv_contrast_playbook_code(code: str) -> str:
    if code not in IV_CONTRAST_PLAYBOOK_CODES:
        raise ValueError(f"IV contrast code not in RadLex Playbook vocabulary: {code!r}")
    return code


def series_type_label(code: str) -> str:
    if not code:
        return "—"
    return _playbook_localized(_SERIES_TYPE_MSGIDS, code)


def series_type_modifier_label(code: str) -> str:
    if not code:
        return "—"
    return _playbook_localized(_SERIES_TYPE_MODIFIER_MSGIDS, code)


def _normalized_dicom_text(*values: object) -> str:
    parts = [str(value).strip().upper() for value in values if value not in (None, "")]
    return " ".join(part for part in parts if part)


def _contains_dicom_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _series_image_type_tokens(ds: Dataset | None, geometry: SeriesGeometryResult) -> tuple[str, ...]:
    if geometry.image_type:
        return tuple(token.upper() for token in geometry.image_type)
    if ds is None:
        return ()
    image_type = ds.get("ImageType")
    if image_type is None:
        return ()
    if isinstance(image_type, (list, tuple)):
        return tuple(str(token).strip().upper() for token in image_type if str(token).strip())
    return (str(image_type).strip().upper(),)


def map_series_type_code(ds: Dataset | None, geometry: SeriesGeometryResult) -> str:
    """
    Map DICOM metadata and geometry to a Playbook Series Type code.

    Standard diagnostic acquisitions return an empty string (Series Type omitted).
    """
    if is_localizer_geometry(geometry):
        return "Localizer"

    text = _normalized_dicom_text(
        ds.get("SeriesDescription") if ds is not None else None,
        ds.get("StudyDescription") if ds is not None else None,
        ds.get("ProtocolName") if ds is not None else None,
        ds.get("DerivationDescription") if ds is not None else None,
    )
    image_type = _series_image_type_tokens(ds, geometry)
    sop_class = str(ds.get("SOPClassUID", "") if ds is not None else "")

    if sop_class.startswith(STRUCTURED_REPORT_SOP_PREFIX) and _contains_dicom_keyword(text, _RADIATION_DOSE_KEYWORDS):
        return "Radiation_Dose"

    if _contains_dicom_keyword(text, _CONTRAST_DOSE_KEYWORDS):
        return "Contrast_Dose"

    if _contains_dicom_keyword(text, _MONITORING_KEYWORDS):
        return "Monitoring"

    if "FUSED" in image_type or _contains_dicom_keyword(text, _FUSED_KEYWORDS):
        return "Fused"

    if sop_class == SECONDARY_CAPTURE_SOP or geometry.dimensionality == "projection_2d":
        if "SECONDARY" in image_type or geometry.provenance == "derived_secondary":
            return "Screenshot"
        if _contains_dicom_keyword(text, _SCREENSHOT_KEYWORDS):
            return "Screenshot"

    if geometry.provenance == "derived_3d_render":
        return "Postprocess"
    if geometry.provenance == "derived_secondary":
        return "Postprocess"
    if image_type and image_type[0] == "DERIVED":
        if _contains_dicom_keyword(text, RENDER_KEYWORDS):
            return "Postprocess"
        if "PROJECTION" in image_type and not _contains_dicom_keyword(text, MPR_KEYWORDS):
            return "Postprocess"

    if _contains_dicom_keyword(text, _RADIATION_DOSE_KEYWORDS):
        return "Radiation_Dose"

    return ""


def _series_type_evidence(
    code: str,
    *,
    ds: Dataset | None,
    geometry: SeriesGeometryResult | None,
) -> tuple[str, str]:
    if not code:
        return _("Omitted for standard diagnostic volumes"), _("RadLex Playbook")

    if code == "Localizer":
        return _("Localizer geometry classification"), _("DICOM geometry")
    if geometry is not None and code == "Postprocess":
        return (
            f"{provenance_label(geometry.provenance)} · {geometry.provenance_confidence:.0%}",
            _("DICOM geometry"),
        )
    if geometry is not None and code == "Screenshot":
        return dimensionality_label(geometry.dimensionality), _("DICOM geometry")

    if ds is not None:
        image_type = _dicom_field_display(ds, "ImageType")
        if image_type != "—":
            return image_type, _("DICOM ImageType")
        dicom_sources = {
            "SeriesDescription": _("DICOM SeriesDescription"),
            "ProtocolName": _("DICOM ProtocolName"),
            "DerivationDescription": _("DICOM DerivationDescription"),
        }
        for keyword, source in dicom_sources.items():
            value = _dicom_field_display(ds, keyword)
            if value != "—":
                return value, source

    if geometry is not None and geometry.image_type:
        return " ".join(geometry.image_type), _("DICOM geometry")

    return "—", _("DICOM metadata")


def map_series_type_modifier_code(
    ds: Dataset | None,
    geometry: SeriesGeometryResult,
    *,
    series_type_code: str,
) -> str:
    """
    Map DICOM metadata and geometry to a Playbook Series Type Modifier code.

    Standard diagnostic originals and special series types return an empty string.
    """
    if series_type_code in SERIES_TYPE_PLAYBOOK_CODES:
        return ""

    text = _normalized_dicom_text(
        ds.get("SeriesDescription") if ds is not None else None,
        ds.get("StudyDescription") if ds is not None else None,
        ds.get("ProtocolName") if ds is not None else None,
        ds.get("DerivationDescription") if ds is not None else None,
    )
    image_type = _series_image_type_tokens(ds, geometry)

    if geometry.provenance == "derived_3d_render":
        return ""
    if _contains_dicom_keyword(text, RENDER_KEYWORDS) and not _contains_dicom_keyword(text, MPR_KEYWORDS):
        return ""

    if geometry.provenance == "derived_reformat":
        return "MPR"

    if image_type:
        is_derived = image_type[0] == "DERIVED"
        is_secondary = "SECONDARY" in image_type
        is_reformatted = "REFORMATTED" in image_type
        if (is_derived and is_secondary and _contains_dicom_keyword(text, MPR_KEYWORDS)) or (
            is_reformatted and _contains_dicom_keyword(text, MPR_KEYWORDS)
        ):
            return "MPR"

    return ""


def should_emit_series_type_modifier(code: str) -> bool:
    """Return whether a series-type modifier token belongs in the SeriesDescription string."""
    if not code:
        return False
    return False  # SeriesNameV4 omits MPR from output strings in v1.


def _attach_series_type_modifier(
    attributes: PlaybookHarmonizeAttributes,
    geometry: SeriesGeometryResult,
    ds: Dataset | None,
) -> PlaybookHarmonizeAttributes:
    detected = map_series_type_modifier_code(
        ds,
        geometry,
        series_type_code=attributes.series_type_code,
    )
    if detected == attributes.series_type_modifier_code:
        return attributes
    return replace(attributes, series_type_modifier_code=detected)


def map_body_part_code(
    body_parts_present: str,
    structures_present: dict[str, int] | None = None,
) -> str:
    """
    Map TS ``body_parts_present`` (``Head``, ``Chest+Abdomen``, …) to Playbook code(s).

    The internal TS region label ``Head`` is not a Playbook series-description token.
    When brain parenchyma is segmented, the Playbook body-part code is ``Brain``.
    """
    if not body_parts_present.strip():
        raise ValueError("body_parts_present is required for Playbook body part")

    structures = structures_present or {}
    codes: list[str] = []
    for region in body_parts_present.split("+"):
        region = region.strip()
        if region == "Head":
            code = _head_region_playbook_code(structures)
        else:
            code = _TSEG_REGION_TO_BODY_PART_CODE.get(region)
            if code is None:
                raise ValueError(f"Unsupported TS body region for Playbook mapping: {region!r}")
        if code not in BODY_PART_PLAYBOOK_CODES:
            raise ValueError(f"Playbook body part code not registered: {code!r}")
        codes.append(code)

    body_part_code = "+".join(codes)
    logger.debug(
        "Playbook map body part: ts_regions=%r structures=%s → code=%s",
        body_parts_present,
        sorted(structures),
        body_part_code,
    )
    return body_part_code


def _head_region_playbook_code(structures_present: dict[str, int]) -> str:
    """Resolve Playbook body-part code for TS Head region using segmented structures."""
    brain_voxels = max(structures_present.get(name, 0) for name in _HEAD_BRAIN_STRUCTURES)
    skull_voxels = max(
        (structures_present.get(name, 0) for name in _HEAD_SKULL_STRUCTURES),
        default=0,
    )

    if brain_voxels >= MIN_STRUCTURE_VOXELS:
        return "Brain"
    if skull_voxels >= MIN_STRUCTURE_VOXELS and brain_voxels == 0:
        logger.debug("Playbook map body part: Head region with skull/spinal cord but no brain → Head")
        return "Head"
    if brain_voxels > 0 or skull_voxels > 0:
        return "Brain"
    logger.debug("Playbook map body part: Head region without structure detail; defaulting to Brain")
    return "Brain"


def is_localizer_geometry(geometry: SeriesGeometryResult) -> bool:
    return geometry.dimensionality == "localizer_2d"


def map_slice_thickness_bucket(mm: float) -> str:
    """Map effective through-plane thickness (mm) to a Playbook slice-thickness bucket."""
    if mm < 1.0:
        return "Recon"
    if mm < 2.5:
        return "Thin"
    if mm <= 5.0:
        return "Std"
    return "Thick"


def slice_thickness_label(code: str) -> str:
    if not code:
        return "—"
    return _playbook_localized(_SLICE_THICKNESS_MSGIDS, code)


def _dicom_slice_thickness_mm(ds: Dataset) -> float | None:
    for keyword in ("SliceThickness", "SpacingBetweenSlices"):
        raw = ds.get(keyword)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return None


def effective_slice_thickness_mm(
    geometry: SeriesGeometryResult,
    ds: Dataset | None = None,
) -> float | None:
    """
    Effective through-plane thickness (mm) for Playbook bucketing.

    Prefer regular IPP-derived spacing; fall back to DICOM thickness tags when spacing
    is irregular or the stack is too short.
    """
    if (
        geometry.slice_spacing_mm is not None
        and geometry.n_slices >= 2
        and geometry.spacing_regularity is not None
        and geometry.spacing_regularity >= _SLICE_THICKNESS_REGULARITY_MIN
    ):
        return geometry.slice_spacing_mm

    if ds is not None:
        return _dicom_slice_thickness_mm(ds)
    return None


def should_emit_slice_thickness(
    bucket: str,
    geometry: SeriesGeometryResult,
    series_type_code: str,
) -> bool:
    """Return whether a slice-thickness token belongs in the SeriesDescription string."""
    if bucket not in SLICE_THICKNESS_EMITTED_CODES:
        return False
    if geometry.dimensionality != "volume_3d":
        return False
    if series_type_code:
        return False
    return not is_localizer_geometry(geometry)


def resolve_slice_thickness_for_playbook(
    geometry: SeriesGeometryResult,
    ds: Dataset | None,
    *,
    series_type_code: str,
) -> tuple[str, float | None, str]:
    """
    Return ``(emitted_code, mm, bucket)`` for harmonize.

    ``emitted_code`` is empty when the bucket is omitted from SeriesNameV4 (Std/Recon v1).
    """
    mm = effective_slice_thickness_mm(geometry, ds)
    if mm is None:
        return "", None, ""
    bucket = map_slice_thickness_bucket(mm)
    emitted = bucket if should_emit_slice_thickness(bucket, geometry, series_type_code) else ""
    return emitted, mm, bucket


def _attach_slice_thickness(
    attributes: PlaybookHarmonizeAttributes,
    geometry: SeriesGeometryResult,
    ds: Dataset | None,
) -> PlaybookHarmonizeAttributes:
    emitted, mm, _bucket = resolve_slice_thickness_for_playbook(
        geometry,
        ds,
        series_type_code=attributes.series_type_code,
    )
    if emitted == attributes.slice_thickness_code and mm == attributes.slice_thickness_mm:
        return attributes
    return replace(
        attributes,
        slice_thickness_code=emitted,
        slice_thickness_mm=mm,
    )


def _finalize_playbook_attributes(
    attributes: PlaybookHarmonizeAttributes,
    geometry: SeriesGeometryResult,
    ds: Dataset | None,
) -> PlaybookHarmonizeAttributes:
    return _attach_series_type_modifier(
        _attach_slice_thickness(attributes, geometry, ds),
        geometry,
        ds,
    )


def _metadata_route_for_series_type(series_type_code: str, ds: Dataset) -> MetadataHarmonizeRoute:
    if series_type_code == "Localizer":
        return MetadataHarmonizeRoute("Localizer", include_plane=False, iv_contrast_from_dicom=False)
    if series_type_code in {"Radiation_Dose", "Contrast_Dose", "Monitoring", "Screenshot"}:
        return MetadataHarmonizeRoute(series_type_code, include_plane=False, iv_contrast_from_dicom=False)
    return MetadataHarmonizeRoute(
        series_type_code,
        include_plane=True,
        iv_contrast_from_dicom=is_mr_modality(ds.get("Modality")),
    )


def resolve_metadata_harmonize_route(
    ds: Dataset,
    geometry: SeriesGeometryResult,
    *,
    tseg: TS_result | None = None,
) -> MetadataHarmonizeRoute | None:
    """
    Return a metadata-only harmonize route, or ``None`` when TS anatomy merge is required.

    Localizers are handled separately (optional TS fallback) in the harmonize pipeline.
    When ``tseg`` is passed, anatomy analysis may have run but produced no Playbook body
    regions; DICOM metadata is used as a fallback when a body part can be inferred.
    """
    if is_localizer_geometry(geometry):
        return None

    series_type = map_series_type_code(ds, geometry)
    if series_type in METADATA_HARMONIZE_SERIES_TYPES:
        return _metadata_route_for_series_type(series_type, ds)

    if not geometry.ts_suitable and metadata_diagnostic_fallback_allowed(geometry.ts_skip_category):
        return MetadataHarmonizeRoute(
            "",
            include_plane=True,
            iv_contrast_from_dicom=is_mr_modality(ds.get("Modality")),
        )

    if (
        tseg is not None
        and geometry.ts_suitable
        and not tseg.body_parts_present.strip()
    ):
        try:
            map_body_part_from_dicom(ds)
        except ValueError:
            return None
        logger.info(
            "Playbook harmonize: using DICOM metadata fallback (TS anatomy regions unavailable)",
        )
        return MetadataHarmonizeRoute(
            "",
            include_plane=True,
            iv_contrast_from_dicom=is_mr_modality(ds.get("Modality")),
        )
    return None


def map_body_part_from_dicom(ds: Dataset) -> str:
    """
    Map DICOM metadata to a Playbook body-part code for localizer/scout series.

    RSNA RadLex Series Playbook: localizers omit anatomic plane and use study context
    for body region when ML anatomy segmentation is unavailable.
    """
    body_part_examined = str(ds.get("BodyPartExamined", "") or "").strip().upper()
    if body_part_examined:
        exact = _DICOM_BODY_PART_EXACT.get(body_part_examined.replace(" ", ""))
        if exact is not None:
            logger.debug("Playbook localizer body part: BodyPartExamined=%r → %s", body_part_examined, exact)
            return exact

    combined = " ".join(
        str(ds.get(keyword, "") or "")
        for keyword in ("SeriesDescription", "StudyDescription", "ProtocolName", "BodyPartExamined")
    ).upper()
    for keywords, code in _DICOM_BODY_PART_KEYWORDS:
        if any(keyword in combined for keyword in keywords):
            logger.debug("Playbook localizer body part: text match %r → %s", keywords[0], code)
            return code

    raise ValueError("Could not determine Playbook body part from DICOM metadata for this localizer series")


def build_metadata_playbook_attributes(
    ds: Dataset,
    geometry: SeriesGeometryResult,
    route: MetadataHarmonizeRoute,
) -> PlaybookHarmonizeAttributes:
    body_part_code = map_body_part_from_dicom(ds)
    anatomic_plane_code = map_anatomic_plane_code(geometry) if route.include_plane else ""
    if route.iv_contrast_from_dicom:
        iv_contrast_code, _evidence = map_mr_iv_contrast_from_dicom(ds)
    else:
        iv_contrast_code = "WO"
    attributes = PlaybookHarmonizeAttributes(
        body_part_code=body_part_code,
        anatomic_plane_code=anatomic_plane_code,
        iv_contrast_code=iv_contrast_code,
        series_type_code=route.series_type_code,
        body_part_confidence=None,
        plane_confidence=geometry.plane_confidence,
        contrast_confidence=None,
        contrast_phase="native",
    )
    return _finalize_playbook_attributes(attributes, geometry, ds)


def build_metadata_harmonized_series_description(
    ds: Dataset,
    geometry: SeriesGeometryResult,
    route: MetadataHarmonizeRoute,
) -> tuple[str, PlaybookHarmonizeAttributes]:
    attributes = build_metadata_playbook_attributes(ds, geometry, route)
    description = format_playbook_series_description(attributes, geometry)
    return description, attributes


def build_localizer_playbook_attributes(
    ds: Dataset,
    geometry: SeriesGeometryResult,
) -> PlaybookHarmonizeAttributes:
    return build_metadata_playbook_attributes(
        ds,
        geometry,
        _metadata_route_for_series_type("Localizer", ds),
    )


def build_localizer_harmonized_series_description(
    ds: Dataset,
    geometry: SeriesGeometryResult,
) -> tuple[str, PlaybookHarmonizeAttributes]:
    route = _metadata_route_for_series_type("Localizer", ds)
    return build_metadata_harmonized_series_description(ds, geometry, route)


def build_postprocess_playbook_attributes(
    ds: Dataset,
    geometry: SeriesGeometryResult,
) -> PlaybookHarmonizeAttributes:
    return build_metadata_playbook_attributes(
        ds,
        geometry,
        _metadata_route_for_series_type("Postprocess", ds),
    )


def build_postprocess_harmonized_series_description(
    ds: Dataset,
    geometry: SeriesGeometryResult,
) -> tuple[str, PlaybookHarmonizeAttributes]:
    route = _metadata_route_for_series_type("Postprocess", ds)
    return build_metadata_harmonized_series_description(ds, geometry, route)


def map_anatomic_plane_code(geometry: SeriesGeometryResult) -> str:
    """
    Map geometry to a Playbook anatomic-plane code.

    Oblique acquisitions use the nearest cardinal plane with an ``_Obl`` suffix (e.g. ``Ax_Obl``).
    """
    plane = geometry.plane
    if plane == "unknown":
        code = "Rad_Obl"
    elif plane == "oblique":
        angles = geometry.plane_angles_deg
        nearest = min(_CARDINAL_PLANE_CODES, key=lambda name: angles.get(name, 90.0))
        code = f"{_CARDINAL_PLANE_CODES[nearest]}_Obl"
    else:
        code = _CARDINAL_PLANE_CODES.get(plane, "Rad_Obl")

    if code not in ANATOMIC_PLANE_PLAYBOOK_CODES:
        raise ValueError(f"Playbook anatomic plane code not registered: {code!r}")

    logger.debug(
        "Playbook map anatomic plane: geometry.plane=%s confidence=%.3f → code=%s",
        geometry.plane,
        geometry.plane_confidence,
        code,
    )
    return code


def map_mr_iv_contrast_from_dicom(ds: Dataset) -> tuple[str, str]:
    """
    Infer Playbook ``W`` / ``WO`` for MR from DICOM headers only.

    Returns ``(iv_contrast_code, evidence)``. Prefer explicit without-contrast text,
    then bolus tags, then with-contrast text; default ``WO`` when none are present.
    """
    agent = str(ds.get("ContrastBolusAgent") or "").strip()
    route = str(ds.get("ContrastBolusRoute") or "").strip()
    volume = str(ds.get("ContrastBolusVolume") or "").strip()
    text = _normalized_dicom_text(
        ds.get("SeriesDescription"),
        ds.get("ProtocolName"),
        ds.get("StudyDescription"),
        ds.get("DerivationDescription"),
    )

    if _contains_dicom_keyword(text, _MR_WITHOUT_CONTRAST_KEYWORDS):
        matched = next(k for k in _MR_WITHOUT_CONTRAST_KEYWORDS if k in text)
        return _iv_contrast_playbook_code("WO"), _("Series/protocol text") + f": {matched}"

    if agent:
        return _iv_contrast_playbook_code("W"), _("ContrastBolusAgent") + f": {agent}"
    if route:
        return _iv_contrast_playbook_code("W"), _("ContrastBolusRoute") + f": {route}"
    if volume and volume not in {"0", "0.0"}:
        return _iv_contrast_playbook_code("W"), _("ContrastBolusVolume") + f": {volume}"

    if _contains_dicom_keyword(text, _MR_WITH_CONTRAST_KEYWORDS):
        matched = next(k for k in _MR_WITH_CONTRAST_KEYWORDS if k in text)
        return _iv_contrast_playbook_code("W"), _("Series/protocol text") + f": {matched}"

    return (
        _iv_contrast_playbook_code("WO"),
        _("No contrast indicators in DICOM headers"),
    )


def map_iv_contrast_code(tseg: TS_result) -> str:
    """Map TS contrast phase to a Playbook IV contrast code from ``IV_CONTRAST_PLAYBOOK_CODES``."""
    phase = (tseg.contrast_phase or "").strip().lower()
    if phase:
        code = _TS_CONTRAST_PHASE_TO_CODE.get(phase)
        if code is None:
            code = "W" if tseg.iv_contrast else "WO"
            logger.warning(
                "Playbook map IV contrast: unknown TS phase %r; using fallback code %s",
                tseg.contrast_phase,
                code,
            )
        else:
            logger.debug(
                "Playbook map IV contrast: ts_phase=%s iv_contrast=%s → code=%s",
                tseg.contrast_phase,
                tseg.iv_contrast,
                code,
            )
        return _iv_contrast_playbook_code(code)

    code = "W" if tseg.iv_contrast else "WO"
    logger.debug(
        "Playbook map IV contrast: no TS phase; iv_contrast=%s → code=%s",
        tseg.iv_contrast,
        code,
    )
    return _iv_contrast_playbook_code(code)


def build_playbook_attributes(
    tseg: TS_result,
    geometry: SeriesGeometryResult,
    *,
    ds: Dataset | None = None,
) -> PlaybookHarmonizeAttributes:
    body_part_code = map_body_part_code(tseg.body_parts_present, tseg.structures_present)
    anatomic_plane_code = map_anatomic_plane_code(geometry)
    series_type_code = map_series_type_code(ds, geometry)

    if ds is not None and is_mr_modality(ds.get("Modality")):
        iv_contrast_code, _evidence = map_mr_iv_contrast_from_dicom(ds)
        attributes = PlaybookHarmonizeAttributes(
            body_part_code=body_part_code,
            anatomic_plane_code=anatomic_plane_code,
            iv_contrast_code=iv_contrast_code,
            series_type_code=series_type_code,
            body_part_confidence=tseg.region_fraction,
            plane_confidence=geometry.plane_confidence,
            contrast_confidence=None,
            contrast_phase="",
        )
        return _finalize_playbook_attributes(attributes, geometry, ds)

    iv_contrast_code = map_iv_contrast_code(tseg)
    attributes = PlaybookHarmonizeAttributes(
        body_part_code=body_part_code,
        anatomic_plane_code=anatomic_plane_code,
        iv_contrast_code=iv_contrast_code,
        series_type_code=series_type_code,
        body_part_confidence=tseg.region_fraction,
        plane_confidence=geometry.plane_confidence,
        contrast_confidence=tseg.phase_probability if tseg.contrast_phase else None,
        contrast_phase=tseg.contrast_phase,
    )
    return _finalize_playbook_attributes(attributes, geometry, ds)


def playbook_series_description_elements(
    attributes: PlaybookHarmonizeAttributes,
    geometry: SeriesGeometryResult,
    *,
    include_modality: bool = False,
) -> list[str]:
    """
    Ordered Playbook CT series-name elements implemented by harmonize.

    Full CT convention order (RSNA spreadsheet): Laterality, Body Part, Body Part
    Modifier, Maneuvers, Anatomic Plane, IV Contrast, Slice Thickness, … Harmonize
    currently emits Body Part → Anatomic Plane → IV Contrast → Slice Thickness (Thin/Thick
    only when non-default) → Series Type (when applicable).

    For single-modality CT exams the ``CT`` modality prefix is omitted per Playbook rules.
    """
    elements: list[str] = []
    if include_modality:
        elements.append("CT")
    elements.append(attributes.body_part_code)

    if geometry.dimensionality != "localizer_2d" and attributes.anatomic_plane_code:
        elements.append(attributes.anatomic_plane_code)

    if attributes.iv_contrast_code:
        elements.append(attributes.iv_contrast_code)

    if attributes.slice_thickness_code:
        elements.append(attributes.slice_thickness_code)

    if attributes.series_type_code:
        elements.append(attributes.series_type_code)

    return elements


def format_playbook_series_description(
    attributes: PlaybookHarmonizeAttributes,
    geometry: SeriesGeometryResult,
    *,
    include_modality: bool = False,
) -> str:
    """
    Build the Playbook-compliant CT series description string.

    Element order: ``{BodyPart[+…]} {AnatomicPlane} {IVContrastPhase} [{Thin|Thick}] {SeriesType}``.
    Standard-range thickness (≥2.5 mm and <5 mm) and sub-1 mm reconstructions are omitted
    per RSNA CT Sandbox SeriesNameV4. ``WO`` is emitted for native series.
    """
    elements = playbook_series_description_elements(
        attributes,
        geometry,
        include_modality=include_modality,
    )
    description = " ".join(elements)
    if len(description) > 64:
        logger.warning(
            "Playbook series description exceeds 64 characters (%d): %r",
            len(description),
            description,
        )
    logger.debug(
        "Playbook series description: elements=%s → %r",
        elements,
        description,
    )
    return description


def build_harmonized_series_description(
    tseg: TS_result,
    geometry: SeriesGeometryResult,
    *,
    include_modality: bool = False,
    ds: Dataset | None = None,
) -> tuple[str, PlaybookHarmonizeAttributes]:
    attributes = build_playbook_attributes(tseg, geometry, ds=ds)
    return (
        format_playbook_series_description(
            attributes,
            geometry,
            include_modality=include_modality,
        ),
        attributes,
    )


def _dicom_field_display(ds: Dataset, keyword: str) -> str:
    value = ds.get(keyword)
    if value is None or value == "":
        return "—"
    return str(value).strip()


def harmonize_dicom_rows(ds: Dataset) -> list[tuple[str, str, str]]:
    """DICOM tags relevant to Playbook series-description harmonization (blank values included)."""
    rows = [
        (_("Study Description"), "(0008,1030)", _dicom_field_display(ds, "StudyDescription")),
        (_("Modality"), "(0008,0060)", _dicom_field_display(ds, "Modality")),
        (_("Series Description"), "(0008,103E)", _dicom_field_display(ds, "SeriesDescription")),
        (_("Series Number"), "(0020,0011)", _dicom_field_display(ds, "SeriesNumber")),
        (_("Image Type"), "(0008,0008)", _dicom_field_display(ds, "ImageType")),
        (_("SOP Class UID"), "(0008,0016)", _dicom_field_display(ds, "SOPClassUID")),
        (_("Derivation Description"), "(0008,2111)", _dicom_field_display(ds, "DerivationDescription")),
        (_("Body Part Examined"), "(0018,0015)", _dicom_field_display(ds, "BodyPartExamined")),
        (_("Slice Thickness"), "(0018,0050)", _dicom_field_display(ds, "SliceThickness")),
        (_("Spacing Between Slices"), "(0018,0088)", _dicom_field_display(ds, "SpacingBetweenSlices")),
        (_("Protocol Name"), "(0018,1030)", _dicom_field_display(ds, "ProtocolName")),
        (_("Scanning Sequence"), "(0018,0020)", _dicom_field_display(ds, "ScanningSequence")),
        (_("Image Orientation Patient"), "(0020,0037)", _dicom_field_display(ds, "ImageOrientationPatient")),
        (_("Patient Orientation"), "(0020,0020)", _dicom_field_display(ds, "PatientOrientation")),
        (_("View Position"), "(0018,5101)", _dicom_field_display(ds, "ViewPosition")),
        (_("Contrast Bolus Agent"), "(0018,0010)", _dicom_field_display(ds, "ContrastBolusAgent")),
        (_("Contrast Bolus Route"), "(0018,1040)", _dicom_field_display(ds, "ContrastBolusRoute")),
        (_("Contrast Bolus Volume"), "(0018,1041)", _dicom_field_display(ds, "ContrastBolusVolume")),
    ]
    return rows


def playbook_body_part_row_values(
    attributes: PlaybookHarmonizeAttributes | None = None,
    *,
    tseg: TS_result | None = None,
    geometry: SeriesGeometryResult | None = None,
) -> tuple[str, str, str, str, str]:
    if attributes is not None:
        source = _("TotalSegmentator anatomy")
        evidence = _playbook_body_part_evidence(
            tseg=tseg,
            attributes=attributes,
            geometry=geometry,
        )
        if geometry is not None and is_localizer_geometry(geometry) and attributes.body_part_confidence is None:
            source = _("DICOM metadata")
        return (
            _("Body Part"),
            attributes.body_part_code,
            body_part_label(attributes.body_part_code),
            evidence,
            source,
        )
    if tseg is not None and tseg.body_parts_present.strip() and tseg.error is None:
        code = map_body_part_code(tseg.body_parts_present, tseg.structures_present)
        return (
            _("Body Part"),
            code,
            body_part_label(code),
            _playbook_body_part_evidence(tseg=tseg),
            _("TotalSegmentator anatomy"),
        )
    return (_("Body Part"), "—", "—", "—", "—")


def playbook_plane_row_values(
    geometry: SeriesGeometryResult | None,
    anatomic_plane_code: str | None = None,
) -> tuple[str, str, str, str, str]:
    if geometry is not None and is_localizer_geometry(geometry):
        return (
            _("Anatomic Plane"),
            "—",
            _("Omitted"),
            _("RadLex Playbook localizer rule"),
            _("RadLex Playbook"),
        )
    if geometry is None:
        return (_("Anatomic Plane"), "—", "—", "—", "—")
    code = anatomic_plane_code or map_anatomic_plane_code(geometry)
    evidence = format_geometry_summary(geometry)
    if not geometry.ts_suitable:
        from anonymizer.controller.ai.tseg.dicom_geometry import geometry_skip_reason_label

        evidence = f"{evidence} — {geometry_skip_reason_label(geometry)}"
    return (
        _("Anatomic Plane"),
        code,
        anatomic_plane_label(code),
        evidence,
        _("DICOM ImageOrientationPatient"),
    )


def playbook_iv_contrast_row_values(
    attributes: PlaybookHarmonizeAttributes | None = None,
    contrast_phase: str = "",
    iv_evidence: str | None = None,
    *,
    tseg: TS_result | None = None,
    geometry: SeriesGeometryResult | None = None,
    ds: Dataset | None = None,
) -> tuple[str, str, str, str, str]:
    """Playbook table row for IV contrast (CT phase classifier or MR DICOM headers)."""
    if ds is not None and is_mr_modality(ds.get("Modality")):
        if attributes is not None:
            code = attributes.iv_contrast_code
            evidence = map_mr_iv_contrast_from_dicom(ds)[1]
        else:
            code, evidence = map_mr_iv_contrast_from_dicom(ds)
        if iv_evidence:
            evidence = iv_evidence
        return (
            _("IV Contrast"),
            code,
            iv_contrast_label(code),
            evidence,
            _("DICOM metadata"),
        )

    if attributes is not None:
        phase = attributes.contrast_phase or ""
        if attributes.iv_contrast_code != "WO" and attributes.contrast_phase:
            phase = attributes.contrast_phase
        if tseg is not None and tseg.contrast_phase:
            phase = tseg.contrast_phase
            probability = tseg.phase_probability if tseg.contrast_phase else None
        else:
            probability = attributes.contrast_confidence
        evidence = _playbook_iv_contrast_evidence(
            phase=phase,
            probability=probability,
            iv_evidence=iv_evidence,
        )
        source = _("TotalSegmentator contrast")
        if geometry is not None and is_localizer_geometry(geometry) and attributes.contrast_confidence is None:
            source = _("RadLex Playbook")
            evidence = _("Native (assumed for localizer)")
        return (
            _("IV Contrast Phase"),
            attributes.iv_contrast_code,
            iv_contrast_label(attributes.iv_contrast_code),
            evidence,
            source,
        )
    if tseg is not None and tseg.contrast_phase:
        code = map_iv_contrast_code(tseg)
        return (
            _("IV Contrast Phase"),
            code,
            iv_contrast_label(code),
            _playbook_iv_contrast_evidence(
                phase=tseg.contrast_phase,
                probability=tseg.phase_probability if tseg.contrast_phase else None,
            ),
            _("TotalSegmentator contrast"),
        )
    return (_("IV Contrast Phase"), "—", "—", "—", "—")


def _slice_thickness_evidence(
    *,
    mm: float | None,
    bucket: str,
    emitted: str,
    geometry: SeriesGeometryResult | None,
    ds: Dataset | None,
) -> str:
    parts: list[str] = []
    if mm is not None:
        parts.append(f"{mm:g} mm")
    if bucket:
        parts.append(slice_thickness_label(bucket))
    if geometry is not None and geometry.slice_spacing_mm is not None:
        parts.append(_("IPP spacing") + f" {geometry.slice_spacing_mm:g} mm")
    if ds is not None:
        tag_mm = _dicom_slice_thickness_mm(ds)
        if tag_mm is not None:
            parts.append(_("SliceThickness tag") + f" {tag_mm:g} mm")
    if bucket and not emitted:
        parts.append(_("Omitted (standard or recon bucket)"))
    return " · ".join(parts) if parts else "—"


def playbook_slice_thickness_row_values(
    attributes: PlaybookHarmonizeAttributes | None = None,
    *,
    geometry: SeriesGeometryResult | None = None,
    ds: Dataset | None = None,
) -> tuple[str, str, str, str, str]:
    if attributes is not None and geometry is not None:
        emitted, mm, bucket = resolve_slice_thickness_for_playbook(
            geometry,
            ds,
            series_type_code=attributes.series_type_code,
        )
        if mm is None:
            return (_("Slice Thickness"), "—", "—", "—", _("DICOM metadata"))
        code = emitted or "—"
        value = slice_thickness_label(bucket) if bucket else "—"
        if emitted:
            value = slice_thickness_label(emitted)
        evidence = _slice_thickness_evidence(
            mm=mm,
            bucket=bucket,
            emitted=emitted,
            geometry=geometry,
            ds=ds,
        )
        return (
            _("Slice Thickness"),
            code,
            value,
            evidence,
            _("DICOM metadata"),
        )
    if geometry is not None:
        emitted, mm, bucket = resolve_slice_thickness_for_playbook(
            geometry,
            ds,
            series_type_code=map_series_type_code(ds, geometry),
        )
        if mm is None:
            return (_("Slice Thickness"), "—", "—", "—", _("DICOM metadata"))
        return (
            _("Slice Thickness"),
            emitted or "—",
            slice_thickness_label(emitted or bucket),
            _slice_thickness_evidence(mm=mm, bucket=bucket, emitted=emitted, geometry=geometry, ds=ds),
            _("DICOM metadata"),
        )
    return (_("Slice Thickness"), "—", "—", "—", "—")


def playbook_series_type_row_values(
    series_type_code: str = "",
    attributes: PlaybookHarmonizeAttributes | None = None,
    *,
    ds: Dataset | None = None,
    geometry: SeriesGeometryResult | None = None,
) -> tuple[str, str, str, str, str]:
    code = series_type_code or (attributes.series_type_code if attributes is not None else "")
    if not code and geometry is not None:
        code = map_series_type_code(ds, geometry)
    evidence, source = _series_type_evidence(code, ds=ds, geometry=geometry)
    if code:
        return (
            _("Series Type"),
            code,
            series_type_label(code),
            evidence,
            source,
        )
    return (
        _("Series Type"),
        "—",
        _("Standard diagnostic"),
        evidence,
        source,
    )


def playbook_series_type_modifier_row_values(
    attributes: PlaybookHarmonizeAttributes | None = None,
    *,
    ds: Dataset | None = None,
    geometry: SeriesGeometryResult | None = None,
) -> tuple[str, str, str, str, str]:
    series_type_code = attributes.series_type_code if attributes is not None else ""
    if geometry is not None and not series_type_code:
        series_type_code = map_series_type_code(ds, geometry)

    detected = ""
    if attributes is not None:
        detected = attributes.series_type_modifier_code
    elif geometry is not None:
        detected = map_series_type_modifier_code(
            ds,
            geometry,
            series_type_code=series_type_code,
        )

    if not detected:
        return (
            _("Series Type Modifier"),
            "—",
            "—",
            _("Omitted for standard diagnostic volumes"),
            _("RadLex Playbook"),
        )

    evidence_parts = [series_type_modifier_label(detected)]
    if geometry is not None:
        evidence_parts.insert(0, provenance_label(geometry.provenance))
    if not should_emit_series_type_modifier(detected):
        evidence_parts.append(_("Omitted per SeriesNameV4"))
    return (
        _("Series Type Modifier"),
        detected,
        series_type_modifier_label(detected),
        " · ".join(evidence_parts),
        _("DICOM geometry"),
    )


PLAYBOOK_TREE_IIDS: tuple[str, str, str, str, str, str] = (
    "playbook_body_part",
    "playbook_plane",
    "playbook_iv_contrast",
    "playbook_slice_thickness",
    "playbook_series_type",
    "playbook_series_type_modifier",
)


def harmonize_analysis_rows(
    attributes: PlaybookHarmonizeAttributes,
    *,
    geometry: SeriesGeometryResult | None = None,
    ds: Dataset | None = None,
    tseg: TS_result | None = None,
) -> list[tuple[str, str, str, str, str]]:
    """Return ``(element, code, value, evidence, source)`` rows for harmonize results UI."""
    return [
        playbook_body_part_row_values(attributes, geometry=geometry, tseg=tseg),
        playbook_plane_row_values(geometry, attributes.anatomic_plane_code),
        playbook_iv_contrast_row_values(attributes, geometry=geometry, tseg=tseg, ds=ds),
        playbook_slice_thickness_row_values(attributes, geometry=geometry, ds=ds),
        playbook_series_type_row_values(attributes=attributes, ds=ds, geometry=geometry),
        playbook_series_type_modifier_row_values(attributes=attributes, ds=ds, geometry=geometry),
    ]


def format_playbook_analysis_log_lines(
    attributes: PlaybookHarmonizeAttributes,
    *,
    geometry: SeriesGeometryResult | None = None,
    ds: Dataset | None = None,
    tseg: TS_result | None = None,
) -> list[str]:
    """One line per Playbook row, aligned with the harmonize results table."""
    lines: list[str] = []
    for element, _code, value, evidence, source in harmonize_analysis_rows(
        attributes,
        geometry=geometry,
        ds=ds,
        tseg=tseg,
    ):
        if value == "—":
            continue
        line = f"{element}: {value}"
        if evidence and evidence != "—":
            line += f" — {evidence}"
        if source and source != "—":
            line += f" ({source})"
        lines.append(line)
    return lines


def format_harmonize_analysis_section(
    attributes: PlaybookHarmonizeAttributes | None,
    *,
    tseg: TS_result | None = None,
    geometry: SeriesGeometryResult | None = None,
) -> str:
    """Compact text summary (tests and logging)."""
    if attributes is None or tseg is None or not tseg.body_parts_present.strip():
        error = tseg.error if tseg is not None and tseg.error else _("Not available")
        return error

    lines = [
        f"{element}: {value} [{code}] — {evidence} ({source})"
        for element, code, value, evidence, source in harmonize_analysis_rows(attributes, geometry=geometry)
    ]
    return "\n".join(lines)
