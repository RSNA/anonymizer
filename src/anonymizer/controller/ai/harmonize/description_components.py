"""RadLex Playbook series description: component-wise options and assembly.

Avoids cartesian-product catalogs. Callers pick one value per field and
``format_*`` builds the Playbook string from the existing vocabularies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from anonymizer.controller.ai.harmonize.loinc_study import parse_playbook_series_description
from anonymizer.controller.ai.harmonize.playbook import (
    BODY_PART_PLAYBOOK_CODES,
    SLICE_THICKNESS_EMITTED_CODES,
)

# Closest edit sets + full vocab in clinical / SeriesNameV4 frequency order
# (typical codes first — never alphabetical for short enums).
_EDIT_PLANES: tuple[str, ...] = ("Ax", "Cor", "Sag")
_ORDERED_PLANES: tuple[str, ...] = (
    "Ax",
    "Cor",
    "Sag",
    "Ax_Obl",
    "Cor_Obl",
    "Sag_Obl",
    "Rad_Obl",
)
_EDIT_CONTRASTS: tuple[str, ...] = ("WO", "W", "Art", "Ven", "PortVen", "Delay", "PulmArt")
_ORDERED_CONTRASTS: tuple[str, ...] = (
    "WO",
    "W",
    "Art",
    "Ven",
    "PortVen",
    "Delay",
    "EarlyArt",
    "LateArt",
    "PulmArt",
    "Neph",
    "CortMed",
    "Equil",
    "Excretory",
    "Dyn",
)
_EDIT_THICKNESS: tuple[str, ...] = ("", "Sub1", "Thin", "Thick")
_ORDERED_THICKNESS: tuple[str, ...] = ("", "Sub1", "Thin", "Thick")
_EDIT_LATERALITIES_CT: tuple[str, ...] = ("", "L", "R", "B")
_ORDERED_LATERALITIES_CT: tuple[str, ...] = ("", "L", "R", "B")
_EDIT_LUMINALS: tuple[str, ...] = ("", "PO", "PR")
_ORDERED_LUMINALS: tuple[str, ...] = (
    "",
    "PO",
    "PR",
    "Cysto",
    "PostVoid",
    "Tube",
    "Intra-articular",
    "Intra-thecal",
)
_EDIT_KERNELS: tuple[str, ...] = ("", "Bone", "Lung")
_ORDERED_KERNELS: tuple[str, ...] = ("", "Bone", "Lung")
_EDIT_VIEWS_CT: tuple[str, ...] = ("", "Prone", "LLD", "RLD")
_ORDERED_VIEWS_CT: tuple[str, ...] = ("", "Prone", "LLD", "RLD")
_ORDERED_SERIES_TYPES: tuple[str, ...] = (
    "",
    "Localizer",
    "Monitoring",
    "Radiation_Dose",
    "Postprocess",
    "Screenshot",
    "Fused",
    "Contrast_Dose",
)
_ORDERED_SERIES_TYPE_MODIFIERS: tuple[str, ...] = ("", "MPR")
# Common body parts first, then remaining codes alphabetically.
_BODY_PART_COMMON: tuple[str, ...] = (
    "Brain",
    "Head",
    "Ch",
    "Abd",
    "Pel",
    "AbdPel",
    "CAP",
    "Neck",
    "Face",
    "CSp",
    "TSp",
    "LSp",
    "Spine",
    "Hip",
    "Knee",
    "Shoulder",
    "Ankle",
    "Wrist",
    "Hand",
    "Foot",
    "Liver",
    "Kidney",
    "Heart",
    "Coronary",
    "Breast",
)
_EDIT_XR_VIEWS: tuple[str, ...] = ("AP", "PA", "Lat", "Obl", "2V", "3V")
_EDIT_MG_VIEWS: tuple[str, ...] = ("CC", "MLO", "ML", "LM", "XCCL", "XCCM")
_EDIT_US_MODES: tuple[str, ...] = ("", "Doppler")
_EDIT_LATERALITIES: tuple[str, ...] = ("", "L", "R", "Bilat")

_EDIT_PLANAR_ANATOMY_LABELS: frozenset[str] = frozenset(
    {
        "Head",
        "Neck",
        "Chest",
        "Abdomen",
        "Pelvis",
        "Abdomen Pelvis",
        "Chest Abdomen Pelvis",
        "Spine",
        "Cervical spine",
        "Thoracic spine",
        "Lumbar spine",
        "Breast",
        "Upper extremity",
        "Lower extremity",
        "Hand",
        "Wrist",
        "Elbow",
        "Shoulder",
        "Hip",
        "Knee",
        "Ankle",
        "Foot",
        "Thyroid",
        "Axilla",
        "Liver",
        "Kidney",
    }
)

_US_CORE_ANATOMY: tuple[str, ...] = (
    "Abdomen",
    "Pelvis",
    "Chest",
    "Neck",
    "Thyroid",
    "Head",
    "Liver",
    "Kidney",
    "Axilla",
)

# LOINC anatomy → Playbook body-part codes (same map as pipeline edit).
_LOINC_ANATOMY_TO_PLAYBOOK_BODY: dict[str, str] = {
    "Head": "Head",
    "Brain": "Brain",
    "Neck": "Neck",
    "Chest": "Ch",
    "Abdomen": "Abd",
    "Pelvis": "Pel",
    "Spine": "Spine",
    "Cervical spine": "CSp",
    "Thoracic spine": "TSp",
    "Lumbar spine": "LSp",
    "Breast": "Breast",
}

TSEG_COMPONENT_FIELDS: tuple[str, ...] = (
    "laterality",
    "body_part",
    "plane",
    "contrast",
    "luminal",
    "series_type",
    "series_type_modifier",
    "slice_thickness",
    "kernel",
    "view",
)

PLANAR_COMPONENT_FIELDS: tuple[str, ...] = (
    "anatomy",
    "view",
    "laterality",
    "mode",
)


@dataclass(frozen=True)
class PlaybookComponentSelection:
    """CT|MR Playbook series description components (RadLex Series Playbook)."""

    body_parts: tuple[str, ...] = ()
    plane: str = ""
    contrast: str = ""
    slice_thickness: str = ""
    series_type: str = ""
    series_type_modifier: str = ""
    laterality: str = ""
    luminal: str = ""
    kernel: str = ""
    view: str = ""


@dataclass(frozen=True)
class PlanarComponentSelection:
    """XR|MG|US Playbook series description components."""

    anatomy: str = ""
    view: str = ""
    laterality: str = ""
    mode: str = ""
    cohort: str = "XR"


def format_playbook_series_description(selection: PlaybookComponentSelection) -> str:
    """
    Assemble a CT|MR Playbook series description (SeriesNameV4 order).

    ``Laterality? BodyPart Plane IV Luminal? SeriesType? Modifier? ST? Kernel? View?``
    Soft kernel, Supine view, and Med thickness are omitted by leaving those fields empty.
    """
    parts: list[str] = []
    if selection.laterality:
        parts.append(selection.laterality)
    if selection.body_parts:
        parts.append("+".join(selection.body_parts))

    if selection.series_type == "Localizer":
        if selection.contrast:
            parts.append(selection.contrast)
        parts.append("Localizer")
        return " ".join(parts)

    if selection.plane:
        parts.append(selection.plane)
    if selection.contrast:
        parts.append(selection.contrast)
    if selection.luminal:
        parts.append(selection.luminal)
    if selection.series_type:
        parts.append(selection.series_type)
    if selection.series_type_modifier:
        parts.append(selection.series_type_modifier)
    if selection.slice_thickness in SLICE_THICKNESS_EMITTED_CODES:
        parts.append(selection.slice_thickness)
    if selection.kernel:
        parts.append(selection.kernel)
    if selection.view:
        parts.append(selection.view)
    return " ".join(p for p in parts if p).strip()


def format_planar_component_description(selection: PlanarComponentSelection) -> str:
    """Assemble an XR|MG|US Playbook series description from component codes."""
    parts: list[str] = []
    if selection.mode:
        parts.append(selection.mode)
    if selection.anatomy:
        parts.append(selection.anatomy)
    if selection.laterality and selection.cohort in {"XR", "MG"}:
        parts.append(selection.laterality)
    if selection.view:
        parts.append(selection.view)
    return " ".join(p for p in parts if p).strip()


def playbook_selection_from_field_map(fields: dict[str, str]) -> PlaybookComponentSelection:
    """Build a selection from UI field → code map (body_part may be ``Ch+Abd``)."""
    raw = (fields.get("body_part") or "").strip()
    body_parts = tuple(p for p in raw.split("+") if p.strip()) if raw else ()
    return PlaybookComponentSelection(
        laterality=(fields.get("laterality") or "").strip(),
        body_parts=body_parts,
        plane=(fields.get("plane") or "").strip(),
        contrast=(fields.get("contrast") or "").strip(),
        luminal=(fields.get("luminal") or "").strip(),
        slice_thickness=(fields.get("slice_thickness") or "").strip(),
        series_type=(fields.get("series_type") or "").strip(),
        series_type_modifier=(fields.get("series_type_modifier") or "").strip(),
        kernel=(fields.get("kernel") or "").strip(),
        view=(fields.get("view") or "").strip(),
    )


def planar_selection_from_field_map(
    fields: dict[str, str],
    *,
    cohort: str,
) -> PlanarComponentSelection:
    return PlanarComponentSelection(
        anatomy=(fields.get("anatomy") or "").strip(),
        view=(fields.get("view") or "").strip(),
        laterality=(fields.get("laterality") or "").strip(),
        mode=(fields.get("mode") or "").strip(),
        cohort=cohort,
    )


def _prefer_first(preferred: Sequence[str], ordered_universe: Sequence[str]) -> list[str]:
    """Stable unique list: preferred values first, then remaining in ``ordered_universe`` order."""
    allowed = set(ordered_universe)
    result: list[str] = []
    seen: set[str] = set()
    for code in preferred:
        if code in seen:
            continue
        if code == "" or code in allowed:
            seen.add(code)
            result.append(code)
    for code in ordered_universe:
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


def _clinical_order(ordered_universe: Sequence[str], *current: str) -> list[str]:
    """Keep clinical / frequency order; append any unknown non-empty current code."""
    result = list(ordered_universe)
    seen = set(result)
    for code in current:
        if code and code not in seen:
            result.append(code)
            seen.add(code)
    return result


def _ordered_body_parts(preferred: Sequence[str], *, include_all: bool) -> list[str]:
    """Current/hinted first, then common anatomy, then remaining codes A–Z."""
    if include_all:
        rest = sorted(code for code in BODY_PART_PLAYBOOK_CODES if code not in _BODY_PART_COMMON)
        universe: list[str] = [*_BODY_PART_COMMON, *rest]
        # Allow a joined compound (Ch+Abd) not in the frozenset.
        for code in preferred:
            if code and code not in universe:
                universe.insert(0, code)
        return _prefer_first(preferred, universe)
    return list(dict.fromkeys([c for c in preferred if c] or ["Ch"]))


def _playbook_body_parts_from_anatomy_hint(anatomy_hint: str) -> list[str]:
    from anonymizer.controller.ai.harmonize.loinc_study import infer_loinc_anatomy_from_text

    codes: list[str] = []
    seen: set[str] = set()
    for anat in infer_loinc_anatomy_from_text(anatomy_hint):
        code = _LOINC_ANATOMY_TO_PLAYBOOK_BODY.get(anat)
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
        if anat == "Head" and "Brain" not in seen:
            seen.add("Brain")
            codes.append("Brain")
    return codes


def _planar_recognized_anatomy(tokens: Sequence[str]) -> str | None:
    import re

    if not tokens:
        return None
    joined = " ".join(tokens)
    for label in sorted(_EDIT_PLANAR_ANATOMY_LABELS, key=len, reverse=True):
        if re.search(rf"(?i)\b{re.escape(label)}\b", joined):
            return label
    for tok in tokens:
        if tok in _EDIT_PLANAR_ANATOMY_LABELS:
            return tok
    return None


def _tseg_component_options(
    current: str,
    *,
    anatomy_hint: str,
    full_vocab: bool,
) -> dict[str, list[str]]:
    parsed = parse_playbook_series_description(current)
    parsed_parts = [str(p) for p in (parsed.get("body_parts") or [])]
    hinted = _playbook_body_parts_from_anatomy_hint(anatomy_hint) if anatomy_hint else []
    body_joined = "+".join(parsed_parts) if parsed_parts else ""

    laterality = str(parsed.get("laterality") or "")
    plane = str(parsed.get("plane") or "")
    contrast = str(parsed.get("contrast") or "")
    luminal = str(parsed.get("luminal") or "")
    thickness = str(parsed.get("slice_thickness") or "")
    series_type = str(parsed.get("series_type") or "")
    modifier = str(parsed.get("series_type_modifier") or "")
    kernel = str(parsed.get("kernel") or "")
    view = str(parsed.get("view") or "")

    if full_vocab:
        body_options = _ordered_body_parts(
            [body_joined, *parsed_parts, *hinted],
            include_all=True,
        )
        laterality_options = _clinical_order(_ORDERED_LATERALITIES_CT, laterality)
        plane_options = _clinical_order(_ORDERED_PLANES, plane)
        contrast_options = _clinical_order(_ORDERED_CONTRASTS, contrast or "WO")
        luminal_options = _clinical_order(_ORDERED_LUMINALS, luminal)
        thickness_options = _clinical_order(_ORDERED_THICKNESS, thickness)
        type_options = _clinical_order(_ORDERED_SERIES_TYPES, series_type)
        modifier_options = _clinical_order(_ORDERED_SERIES_TYPE_MODIFIERS, modifier)
        kernel_options = _clinical_order(_ORDERED_KERNELS, kernel)
        view_options = _clinical_order(_ORDERED_VIEWS_CT, view)
    else:
        body_options = _ordered_body_parts(
            [body_joined, *parsed_parts, *hinted],
            include_all=False,
        )
        laterality_options = _clinical_order(_EDIT_LATERALITIES_CT, laterality)
        plane_options = _clinical_order(_EDIT_PLANES, plane)
        contrast_options = _clinical_order(_EDIT_CONTRASTS, contrast or "WO")
        luminal_options = _clinical_order(_EDIT_LUMINALS, luminal)
        thickness_options = _clinical_order(_EDIT_THICKNESS, thickness)
        type_options = _clinical_order(
            ("", "Localizer", "Monitoring", "Radiation_Dose"), series_type
        )
        modifier_options = _clinical_order(("", "MPR"), modifier)
        kernel_options = _clinical_order(_EDIT_KERNELS, kernel)
        view_options = _clinical_order(_EDIT_VIEWS_CT, view)

    return {
        "laterality": laterality_options,
        "body_part": body_options,
        "plane": plane_options,
        "contrast": contrast_options,
        "luminal": luminal_options,
        "series_type": type_options,
        "series_type_modifier": modifier_options,
        "slice_thickness": thickness_options,
        "kernel": kernel_options,
        "view": view_options,
    }


def _planar_component_options(
    current: str,
    *,
    cohort: str,
    full_vocab: bool,
) -> dict[str, list[str]]:
    tokens = [tok for tok in current.split() if tok]
    anatomy = _planar_recognized_anatomy(tokens) or (
        "Breast" if cohort == "MG" else ("Abdomen" if cohort == "US" else "Chest")
    )
    laterality = ""
    for tok in tokens:
        if tok in {"L", "R", "Bilat"}:
            laterality = tok
            break
    view_set = _EDIT_MG_VIEWS if cohort == "MG" else _EDIT_XR_VIEWS
    current_view = next((tok for tok in tokens if tok in view_set), "")
    mode = "Doppler" if tokens and tokens[0] == "Doppler" else ""

    if cohort == "US":
        if full_vocab:
            anat_ordered = (anatomy, *_US_CORE_ANATOMY, *sorted(_EDIT_PLANAR_ANATOMY_LABELS))
            anatomy_options = _prefer_first([anatomy], anat_ordered)
        else:
            anatomy_options = list(dict.fromkeys([anatomy, *_US_CORE_ANATOMY]))
        return {
            "anatomy": anatomy_options,
            "view": [""],
            "laterality": [""],
            "mode": _prefer_first([mode], _EDIT_US_MODES),
        }

    if cohort == "MG":
        anatomy_options = ["Breast"]
        if full_vocab:
            lat_options = _prefer_first([laterality], _EDIT_LATERALITIES)
            view_options = _prefer_first([current_view], view_set)
        else:
            lat_options = list(dict.fromkeys([laterality or "L", "L", "R", "Bilat", ""]))
            view_options = _prefer_first([current_view], view_set)
        return {
            "anatomy": anatomy_options,
            "view": view_options,
            "laterality": lat_options,
            "mode": [""],
        }

    # XR / CR / DX
    if full_vocab:
        anat_ordered = (anatomy, *sorted(_EDIT_PLANAR_ANATOMY_LABELS))
        anatomy_options = _prefer_first([anatomy], anat_ordered)
        view_options = _prefer_first([current_view], view_set)
        lat_options = _prefer_first([laterality], _EDIT_LATERALITIES)
    else:
        anatomy_options = [anatomy]
        view_options = _prefer_first([current_view], view_set)
        lat_options = list(dict.fromkeys([laterality, ""]))
    return {
        "anatomy": anatomy_options,
        "view": view_options,
        "laterality": lat_options,
        "mode": [""],
    }


def series_playbook_component_options(
    *,
    modality: object | None,
    current_description: str,
    anatomy_hint: str = "",
    full_vocab: bool = False,
) -> dict[str, list[str]]:
    """
    Per-field Playbook code lists for the series description composer.

    Closest (``full_vocab=False``): current parse + small edit vocabularies.
    Full (``full_vocab=True``): entire frozenset vocabulary per field — never a
    cartesian product of composed strings.
    """
    from anonymizer.utils.modalities import (
        planar_harmonize_cohort,
        series_is_planar_harmonize_eligible,
        series_is_tseg_eligible,
    )

    current = (current_description or "").strip()
    hint = (anatomy_hint or "").strip()

    if series_is_tseg_eligible(modality):
        if not current:
            parts = _playbook_body_parts_from_anatomy_hint(hint) if hint else []
            current = f"{parts[0]} Ax WO" if parts else "Ch Ax WO"
        return _tseg_component_options(current, anatomy_hint=hint or current, full_vocab=full_vocab)

    if series_is_planar_harmonize_eligible(modality):
        cohort = planar_harmonize_cohort(modality) or "XR"
        if not current:
            if cohort == "US":
                current = "Abdomen"
            elif cohort == "MG":
                current = "Breast L CC"
            else:
                current = "Chest AP"
        return _planar_component_options(current, cohort=cohort, full_vocab=full_vocab)

    return {}


def series_playbook_component_initial(
    *,
    modality: object | None,
    current_description: str,
    anatomy_hint: str = "",
) -> dict[str, str]:
    """Default field → code map for the composer (from parse / modality seed).

    Blank descriptions stay empty — do not invent ``Ch Ax WO`` (or similar) defaults.
    """
    options = series_playbook_component_options(
        modality=modality,
        current_description=current_description,
        anatomy_hint=anatomy_hint,
        full_vocab=False,
    )
    if not (current_description or "").strip():
        return {field: "" for field in options}
    return {field: (codes[0] if codes else "") for field, codes in options.items()}


def series_playbook_component_field_order(modality: object | None) -> tuple[str, ...]:
    from anonymizer.utils.modalities import series_is_tseg_eligible

    if series_is_tseg_eligible(modality):
        return TSEG_COMPONENT_FIELDS
    return PLANAR_COMPONENT_FIELDS


def format_series_playbook_fields(
    fields: dict[str, str],
    *,
    modality: object | None,
) -> str:
    """Assemble description from a UI field map for the given modality."""
    from anonymizer.utils.modalities import (
        planar_harmonize_cohort,
        series_is_planar_harmonize_eligible,
        series_is_tseg_eligible,
    )

    if series_is_tseg_eligible(modality):
        return format_playbook_series_description(playbook_selection_from_field_map(fields))
    if series_is_planar_harmonize_eligible(modality):
        cohort = planar_harmonize_cohort(modality) or "XR"
        return format_planar_component_description(
            planar_selection_from_field_map(fields, cohort=cohort)
        )
    return ""
