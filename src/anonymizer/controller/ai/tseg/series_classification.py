"""Classify DICOM series for TotalSegmentator eligibility and metadata-only harmonize.

Centralizes keyword lists and evaluation order so geometry analysis and Harmonize share
one structured decision flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydicom import Dataset

from anonymizer.controller.ai.tseg.config import SURVEY_MIN_SLICE_SPACING_MM

if TYPE_CHECKING:
    from anonymizer.controller.ai.tseg.dicom_geometry import (
        DimensionalityLabel,
        ProvenanceLabel,
        StackMetrics,
    )

TsSkipCategory = Literal[
    "localizer",
    "parametric_map",
    "derived_3d_render",
    "single_slice",
    "projection",
    "unknown_dimensionality",
    "unsupported_dimensionality",
    "body_part_no_roi",
    "angio_sequence",
    "spectroscopy",
    "monitoring",
    "dose_report",
    "fused",
]

MPR_KEYWORDS = ("MPR", "REFORMAT", "REFORMATTED", "OBLIQUE", "CURVED")
RENDER_KEYWORDS = ("MIP", "MINIP", "VR", "VRT", "3D", "SSD", "AVERAGE", "THICK SLAB")
LOCALIZER_KEYWORDS = (
    "SCOUT",
    "TOPO",
    "TOPOGRAM",
    "SCANOGRAM",
    "LOCALIZER",
    "SURVIEW",
    "PLAN",
    "HASTE_SAG",
)
# Survey-style acquisitions: thick slices with survey naming (not diagnostic stacks).
SURVEY_LOCALIZER_KEYWORDS = (
    "SURVEY",
    "OVERVIEW",
    "WHOLE BODY",
    "WHOLE SPINE",
    "BODY SURV",
    "STIR SURV",
    "STIR_SURV",
)
PARAMETRIC_MAP_KEYWORDS = (
    "ADC",
    "DWI",
    "DIFFUSION WEIGHTED",
    "APPARENT DIFFUSION",
    "B VALUE",
    "B-VALUE",
    "BVALUE",
    "EADC",
    "TRACEW",
    "FA MAP",
    "MD MAP",
    "COLOR FA",
    "T1 MAP",
    "T2 MAP",
    "T2 STAR",
    "T2*",
    "R2 STAR",
    "R2*",
    "B800",
    "B1000",
    "PERFUSION",
    "CBF",
    "CBV",
    "MTT",
    "TMAX",
    "TTP",
    "KTRANS",
    "K TRANS",
    "RELCBV",
    "RELCBF",
    "BOLD",
    "FAT FRAC",
    "FAT FRACTION",
    "IODINE MAP",
    "VIRTUAL MONO",
    "MTR MAP",
    "MAGNETIZATION TRANSFER",
    "SUBTRACTION",
)
PARAMETRIC_MAP_EXACT_TOKENS = frozenset(
    {
        "B0",
        "B800",
        "B1000",
        "CBF",
        "CBV",
        "MTT",
        "TMAX",
        "TTP",
        "FA",
        "MD",
    }
)
BODY_PARTS_WITHOUT_TS_ROI = frozenset({"BREAST", "MAMM", "PROSTATE"})
ANGIO_SEQUENCE_KEYWORDS = (
    "MR ANGIO",
    "MRANGIO",
    " MRA ",
    "CEMRA",
    "CE-MRA",
    "CE MRA",
    " TOF",
    "TOF ",
    "ANGIOGRAPHY",
    " ANGIO ",
    "CT ANGIO",
    "CTANGIO",
    " CTA ",
)
SPECTROSCOPY_KEYWORDS = (
    "SPECTROSCOPY",
    " SVS ",
    " CSI ",
    "1H-MRS",
    "1H MRS",
    " MRS ",
    " MRS",
)
MONITORING_SEQUENCE_KEYWORDS = (
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
RADIATION_DOSE_SEQUENCE_KEYWORDS = (
    "DOSE REPORT",
    "RDSR",
    "CTDI",
    "DLP",
    "RADIATION DOSE",
    "RADIATION DOSE REPORT",
)
CONTRAST_DOSE_SEQUENCE_KEYWORDS = (
    "CONTRAST DOSE",
    "CONTRAST DOSE SHEET",
    "INJECTOR DOSE",
    "CONTRAST SHEET",
)
FUSED_SEQUENCE_KEYWORDS = (
    "FUSION",
    "FUSED",
    "PET/CT",
    "PET CT",
    "REGISTERED",
    "MULTI ENERGY",
    "MULTIENERGY",
    "DUAL ENERGY",
)

METADATA_DIAGNOSTIC_SKIP_CATEGORIES: frozenset[TsSkipCategory] = frozenset(
    {
        "body_part_no_roi",
        "angio_sequence",
        "spectroscopy",
    }
)


@dataclass(frozen=True)
class TsSuitability:
    """Structured TotalSegmentator eligibility outcome."""

    suitable: bool
    skip_category: TsSkipCategory | None
    notes: str


def normalized_series_text(*parts: str | None) -> str:
    return " ".join(part.strip().upper() for part in parts if part and str(part).strip())


def contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def image_type_values(header: Dataset) -> tuple[str, ...] | None:
    image_type = getattr(header, "ImageType", None)
    if image_type is None:
        return None
    return tuple(str(value).upper() for value in image_type)


def series_description_text(
    headers: list[Dataset],
    *,
    series_description: str | None = None,
) -> str:
    if not headers:
        return ""
    header = headers[0]
    return normalized_series_text(
        series_description or getattr(header, "SeriesDescription", None),
        getattr(header, "ProtocolName", None),
        getattr(header, "StudyDescription", None),
    )


def series_level_description_text(
    headers: list[Dataset],
    *,
    series_description: str | None = None,
) -> str:
    """Series/protocol naming only (study description excluded).

    Study-level labels such as ``CTA CHEST`` must not suppress TotalSegmentator on
    unrelated diagnostic series in the same exam (e.g. ``PE CHEST 2.5mm``).
    """
    if not headers:
        return ""
    header = headers[0]
    return normalized_series_text(
        series_description or getattr(header, "SeriesDescription", None),
        getattr(header, "ProtocolName", None),
    )


def description_suggests_localizer(
    headers: list[Dataset],
    *,
    series_description: str | None = None,
) -> bool:
    if not headers:
        return False

    header = headers[0]
    description_text = series_description_text(headers, series_description=series_description)
    image_type = image_type_values(header)
    if image_type and any(token in image_type for token in ("LOCALIZER", "SCOUT", "TOPOGRAM")):
        return True
    return contains_keyword(description_text, LOCALIZER_KEYWORDS)


def stack_suggests_survey_localizer(
    stack: StackMetrics,
    description_text: str,
) -> bool:
    if not contains_keyword(description_text, SURVEY_LOCALIZER_KEYWORDS):
        return False
    spacing = stack.slice_spacing_mm
    return spacing is not None and spacing >= SURVEY_MIN_SLICE_SPACING_MM


def description_suggests_parametric_map(
    headers: list[Dataset],
    *,
    series_description: str | None = None,
) -> bool:
    if not headers:
        return False

    header = headers[0]
    image_type = image_type_values(header)
    if image_type and image_type[0] != "DERIVED":
        return False

    description_text = series_description_text(headers, series_description=series_description)
    if not description_text:
        return False

    tokens = {
        token
        for token in description_text.replace("=", " ").replace("/", " ").split()
        if token
    }
    if tokens & PARAMETRIC_MAP_EXACT_TOKENS:
        return True
    return contains_keyword(description_text, PARAMETRIC_MAP_KEYWORDS)


def body_part_lacks_ts_roi(header: Dataset) -> bool:
    body_part = str(getattr(header, "BodyPartExamined", "") or "").strip().upper().replace(" ", "")
    return body_part in BODY_PARTS_WITHOUT_TS_ROI


def description_suggests_angio_sequence(description_text: str) -> bool:
    padded = f" {description_text} "
    return contains_keyword(padded, ANGIO_SEQUENCE_KEYWORDS)


def description_suggests_spectroscopy(description_text: str) -> bool:
    padded = f" {description_text} "
    return contains_keyword(padded, SPECTROSCOPY_KEYWORDS) or description_text.startswith("MRS")


def description_suggests_monitoring(description_text: str) -> bool:
    return contains_keyword(description_text, MONITORING_SEQUENCE_KEYWORDS)


def description_suggests_radiation_dose(description_text: str) -> bool:
    return contains_keyword(description_text, RADIATION_DOSE_SEQUENCE_KEYWORDS)


def description_suggests_contrast_dose(description_text: str) -> bool:
    return contains_keyword(description_text, CONTRAST_DOSE_SEQUENCE_KEYWORDS)


def description_suggests_fused(description_text: str) -> bool:
    return contains_keyword(description_text, FUSED_SEQUENCE_KEYWORDS)


def metadata_diagnostic_fallback_allowed(skip_category: TsSkipCategory | None) -> bool:
    return skip_category in METADATA_DIAGNOSTIC_SKIP_CATEGORIES


def evaluate_ts_suitability(
    *,
    dimensionality: DimensionalityLabel,
    provenance: ProvenanceLabel,
    headers: list[Dataset],
    stack: StackMetrics,
    series_description: str | None = None,
) -> TsSuitability:
    """
    Decide whether TotalSegmentator anatomy segmentation should run.

    Evaluation order mirrors clinical priority: dimensionality and provenance first,
    then derived parametric maps, then body-part and sequence-type gaps.
    """
    description_text = series_level_description_text(headers, series_description=series_description)

    if dimensionality == "localizer_2d":
        return TsSuitability(False, "localizer", f"Not a diagnostic 3D volume ({dimensionality})")
    if dimensionality == "single_slice_2d":
        return TsSuitability(False, "single_slice", f"Not a diagnostic 3D volume ({dimensionality})")
    if dimensionality == "projection_2d":
        return TsSuitability(False, "projection", f"Not a diagnostic 3D volume ({dimensionality})")
    if dimensionality == "unknown":
        return TsSuitability(False, "unknown_dimensionality", "Could not classify series dimensionality")
    if provenance == "derived_3d_render":
        return TsSuitability(
            False,
            "derived_3d_render",
            "Derived 3D render (MIP/VR) is not suitable for organ segmentation",
        )
    if dimensionality not in {"volume_3d", "multiframe_volume"}:
        return TsSuitability(
            False,
            "unsupported_dimensionality",
            f"Unsupported dimensionality: {dimensionality}",
        )

    if description_suggests_parametric_map(headers, series_description=series_description):
        return TsSuitability(
            False,
            "parametric_map",
            "Derived parametric map is not suitable for organ segmentation",
        )
    if headers and body_part_lacks_ts_roi(headers[0]):
        return TsSuitability(
            False,
            "body_part_no_roi",
            "Body part is not covered by anatomy segmentation models",
        )
    if description_suggests_angio_sequence(description_text):
        return TsSuitability(
            False,
            "angio_sequence",
            "Angiographic series is not suitable for organ segmentation",
        )
    if description_suggests_spectroscopy(description_text):
        return TsSuitability(
            False,
            "spectroscopy",
            "MR spectroscopy is not suitable for organ segmentation",
        )
    if description_suggests_monitoring(description_text):
        return TsSuitability(
            False,
            "monitoring",
            "Monitoring series is not suitable for organ segmentation",
        )
    if description_suggests_contrast_dose(description_text):
        return TsSuitability(
            False,
            "dose_report",
            "Contrast dose report is not suitable for organ segmentation",
        )
    if description_suggests_radiation_dose(description_text):
        return TsSuitability(
            False,
            "dose_report",
            "Radiation dose report is not suitable for organ segmentation",
        )
    if description_suggests_fused(description_text):
        return TsSuitability(
            False,
            "fused",
            "Fused multimodality series is not suitable for organ segmentation",
        )

    return TsSuitability(True, None, "")


def infer_survey_localizer_dimensionality(
    headers: list[Dataset],
    stack: StackMetrics,
    *,
    series_description: str | None = None,
) -> bool:
    """True when thick-slice survey naming indicates a localizer rather than diagnostic volume."""
    description_text = series_description_text(headers, series_description=series_description)
    return stack_suggests_survey_localizer(stack, description_text)
