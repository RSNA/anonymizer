"""Plain-language explanations for DICOM de-identification options.

Owns product copy shown in the De-identification Options dialog. DICOM Code
Meanings for (0012,0064) stay in utils.dicom.deid_method_meaning.

Public API
----------
DeidOptionExplanation
    title, summary, when_it_runs, optional notes, and optional source link.

deid_option_explanation(code) -> DeidOptionExplanation
    Explanation for a DeidMethodCode (strings are gettext-translated).

option_abbreviation(code) -> str
    Short label for status lines (e.g. Patient, Device).

options_status_line(selected) -> str
    Abbreviated selected options (never Custom). Basic alone → Basic.

script_is_custom(document, selected, *, base_script_path) -> bool
    True when any script operand differs from compile_script(selected).

script_status_line(document, selected, *, base_script_path) -> str
    Custom when the script was edited; otherwise options_status_line.

options_summary_label(selected) -> str
    Alias of options_status_line (checkbox sets are never labeled Custom).

apply_date_option_exclusivity(selected, *, enabled) -> frozenset[DeidMethodCode]
    Clear Full vs Modified Dates conflict when enabling one date option.
"""

from dataclasses import dataclass
from pathlib import Path

from anonymizer.controller.private_tags.private_tags import (
    TCIA_PRIVATE_TAG_KB_ASSET_RELPATH,
    TCIA_PRIVATE_TAG_KB_PAGE_URL,
)
from anonymizer.controller.script.compile import (
    compile_script,
    normalize_script_operation,
    script_operations_by_tag,
)
from anonymizer.controller.script.document import ScriptDocument
from anonymizer.controller.script.paths import packaged_default_script_path
from anonymizer.utils.dicom import DeidMethodCode, deid_method_meaning
from anonymizer.utils.translate import _


@dataclass(frozen=True)
class DeidOptionExplanation:
    """Plain-language copy for one de-identification option in the UI."""

    title: str
    summary: str
    when_it_runs: str
    notes: str = ""
    source_line: str = ""
    link_label: str = ""
    link_url: str = ""
    link_tooltip: str = ""


# Stable display order for non-Basic options on the script status line.
_STATUS_ORDER: tuple[DeidMethodCode, ...] = (
    DeidMethodCode.FULL_DATES,
    DeidMethodCode.MODIFIED_DATES,
    DeidMethodCode.PATIENT_CHARACTERISTICS,
    DeidMethodCode.DEVICE_IDENTITY,
    DeidMethodCode.INSTITUTION_IDENTITY,
    DeidMethodCode.RETAIN_UIDS,
    DeidMethodCode.SAFE_PRIVATE,
    DeidMethodCode.CLEAN_PIXEL_DATA,
    DeidMethodCode.CLEAN_VISUAL_FEATURES,
    DeidMethodCode.CLEAN_GRAPHICS,
    DeidMethodCode.CLEAN_STRUCTURED_CONTENT,
    DeidMethodCode.CLEAN_DESCRIPTORS,
)

_ABBREVIATIONS: dict[DeidMethodCode, str] = {
    DeidMethodCode.BASIC: "Basic",
    DeidMethodCode.FULL_DATES: "Full Dates",
    DeidMethodCode.MODIFIED_DATES: "Modified Dates",
    DeidMethodCode.PATIENT_CHARACTERISTICS: "Patient",
    DeidMethodCode.DEVICE_IDENTITY: "Device",
    DeidMethodCode.INSTITUTION_IDENTITY: "Institution",
    DeidMethodCode.RETAIN_UIDS: "UIDs",
    DeidMethodCode.SAFE_PRIVATE: "Safe Private",
    DeidMethodCode.CLEAN_PIXEL_DATA: "Clean Pixels",
    DeidMethodCode.CLEAN_VISUAL_FEATURES: "Face",
    DeidMethodCode.CLEAN_GRAPHICS: "Graphics",
    DeidMethodCode.CLEAN_STRUCTURED_CONTENT: "Structured",
    DeidMethodCode.CLEAN_DESCRIPTORS: "Descriptors",
}


def option_abbreviation(code: DeidMethodCode) -> str:
    """
    Short translated label for one de-identification option.

    Args:
        code: Option code.

    Returns:
        Abbreviation for status lines.
    """
    code = DeidMethodCode(code)
    return _(_ABBREVIATIONS[code])


def options_status_line(selected: frozenset[DeidMethodCode]) -> str:
    """
    Abbreviated selected options for chrome (never Custom).

    Args:
        selected: Selected de-identification option codes.

    Returns:
        Basic when only the Basic Profile is selected; otherwise a
        comma-separated list of non-Basic abbreviations in stable order.
    """
    options = frozenset(DeidMethodCode(code) for code in selected) | {DeidMethodCode.BASIC}
    extras = [code for code in _STATUS_ORDER if code in options]
    if not extras:
        return option_abbreviation(DeidMethodCode.BASIC)
    return ", ".join(option_abbreviation(code) for code in extras)


def options_summary_label(selected: frozenset[DeidMethodCode]) -> str:
    """Alias of options_status_line (option sets alone are never Custom)."""
    return options_status_line(selected)


def script_is_custom(
    document: ScriptDocument,
    selected: frozenset[DeidMethodCode],
    *,
    base_script_path: Path | None = None,
) -> bool:
    """
    True when any script operand differs from the option-compiled baseline.

    Args:
        document: Script currently open or installed.
        selected: Project de-identification options.
        base_script_path: Packaged default script; None uses the shipped path.

    Returns:
        True when the document is a hand-edited Custom script relative to options.
    """
    base = Path(base_script_path) if base_script_path is not None else packaged_default_script_path()
    compiled = compile_script(frozenset(selected), base)
    compiled_ops = script_operations_by_tag(compiled)
    document_ops = script_operations_by_tag(document)
    if set(document_ops) != set(compiled_ops):
        return True
    return any(
        normalize_script_operation(document_ops[tag]) != normalize_script_operation(compiled_ops[tag])
        for tag in compiled_ops
    )


def script_status_line(
    document: ScriptDocument,
    selected: frozenset[DeidMethodCode],
    *,
    base_script_path: Path | None = None,
) -> str:
    """
    Status line for the Anonymizer Script dialog.

    Args:
        document: Script currently open.
        selected: Project de-identification options.
        base_script_path: Packaged default script path override.

    Returns:
        Custom when operands diverge from compile_script; otherwise options_status_line.
    """
    if script_is_custom(document, selected, base_script_path=base_script_path):
        return _("Custom")
    return options_status_line(selected)


def apply_date_option_exclusivity(
    selected: frozenset[DeidMethodCode],
    *,
    enabled: DeidMethodCode,
) -> frozenset[DeidMethodCode]:
    """
    Ensure Full Dates and Modified Dates are not both selected.

    Args:
        selected: Current selection before exclusivity.
        enabled: Date option the user just turned on.

    Returns:
        Selection including BASIC and ``enabled``, with the other date option cleared.
    """
    result = set(selected) | {DeidMethodCode.BASIC, enabled}
    if enabled is DeidMethodCode.FULL_DATES:
        result.discard(DeidMethodCode.MODIFIED_DATES)
    elif enabled is DeidMethodCode.MODIFIED_DATES:
        result.discard(DeidMethodCode.FULL_DATES)
    return frozenset(result)


def _when_ai_batch(feature_msgid: str) -> str:
    """Build a translated 'when it runs' line for options applied via AI Batch."""
    return _(
        "Does not change files at import. Run AI Batch Process with {feature} enabled to apply this option."
    ).format(feature=_(feature_msgid))


# English msgids for xgettext. gettext applied in deid_option_explanation.
# Direct primary actions only; no "such as", no cross-option "unless", no parentheses.
_COPY: dict[DeidMethodCode, tuple[str, str, str]] = {
    DeidMethodCode.BASIC: (
        "At import: removes all private tags; removes curve and overlay groups; "
        "sets Patient Name and Patient ID to the site ID plus a sequential "
        "patient number that stays the same for that person in this project; "
        "replaces Accession Number with a deterministic hash of the original; "
        "replaces Study, Series, and Instance UIDs with project-prefixed values "
        "derived from the originals; shifts calendar dates by a fixed "
        "per-patient day offset so study order and spacing stay meaningful; "
        "removes birth date; removes referring and performing physician names; "
        "removes institution name and related site identity; removes "
        "manufacturer, model, serial number, station name, and related device "
        "identity; removes sex, size, weight, and related patient "
        "characteristics; rounds Patient Age to a five-year band.",
        "During import.",
        "Always on for every project.",
    ),
    DeidMethodCode.CLEAN_PIXEL_DATA: (
        "After import, detect text drawn into image pixels and blank rectangles "
        "classified as PHI. Uses on-device text detection. Does not change the "
        "anonymizer script.",
        "",
        "Requires Embedded PHI models.",
    ),
    DeidMethodCode.CLEAN_VISUAL_FEATURES: (
        "After import, blur faces on eligible head CT and MR volumes so a "
        "person cannot be recognized from the reconstructed surface. Does not "
        "blank burnt-in text in pixels.",
        "",
        "Requires face-blur models and a suitable head series.",
    ),
    DeidMethodCode.CLEAN_GRAPHICS: (
        "Reserved for cleaning non-text burned-in graphics (logos, rulers, "
        "decorative marks). Curve and overlay groups are already removed at "
        "import. Remaining non-text burned-in graphics are uncommon in modern "
        "research archives; most residual pixel PHI is text (Clean Pixel Data).",
        "Selectable for project records, but no processing task executes this "
        "option — legacy/uncommon edge case, not implemented.",
        "Selecting it only records intent; it is not stamped as executed.",
    ),
    DeidMethodCode.CLEAN_STRUCTURED_CONTENT: (
        "After import, find identifying text in Structured Reports and "
        "encapsulated PDF documents and blank or replace it. Enables accepting "
        "SR and PDF modalities for the project. Does not change image pixels.",
        "",
        "Requires Embedded PHI models.",
    ),
    DeidMethodCode.CLEAN_DESCRIPTORS: (
        "After import, find identifying text in free-text metadata fields "
        "including Study Description, Series Description, and Image Comments, "
        "and blank or replace it. Enables accepting SR and PDF modalities for "
        "the project.",
        "",
        "Requires Embedded PHI models.",
    ),
    DeidMethodCode.FULL_DATES: (
        "Keep original calendar dates and times on every script date attribute. "
        "Use only when your privacy review allows absolute dates to leave the site.",
        "During import.",
        "Cannot be combined with Modified Dates — choose one date strategy.",
    ),
    DeidMethodCode.MODIFIED_DATES: (
        "Shift every script date attribute with one consistent per-patient day "
        "offset so study order and spacing stay meaningful while calendar dates "
        "are not the originals. Time of day is left unchanged.",
        "During import.",
        "Cannot be combined with Full Dates — choose one date strategy.",
    ),
    DeidMethodCode.PATIENT_CHARACTERISTICS: (
        "Keep sex, size, weight, ethnic group, smoking status, pregnancy "
        "status, and related patient characteristics. Patient Age stays "
        "rounded to a five-year band.",
        "During import.",
        "",
    ),
    DeidMethodCode.DEVICE_IDENTITY: (
        "Keep manufacturer, model name, software versions, device serial "
        "number, station name, detector and gantry IDs, and related equipment "
        "identity attributes.",
        "During import.",
        "",
    ),
    DeidMethodCode.RETAIN_UIDS: (
        "Keep original Study, Series, SOP Instance, and other DICOM UIDs.",
        "During import.",
        "Weakens unlinkability; confirm with your privacy officer.",
    ),
    DeidMethodCode.SAFE_PRIVATE: (
        "At import, resolve each private element with the TCIA private-tag "
        "knowledge base: keep, shift dates, remap UIDs, or remove. Remove "
        "private elements the knowledge base does not list.",
        "During import.",
        "Included in the Retain preset.",
    ),
    DeidMethodCode.INSTITUTION_IDENTITY: (
        "Keep institution name, institution address, institutional department "
        "name, and related clinical-trial site identity attributes.",
        "During import.",
        "",
    ),
}

# AI feature title msgids (match AI Features / AI Batch product names).
_AI_BATCH_FEATURE: dict[DeidMethodCode, str] = {
    DeidMethodCode.CLEAN_PIXEL_DATA: "Embedded PHI",
    DeidMethodCode.CLEAN_VISUAL_FEATURES: "Face De-identify",
    DeidMethodCode.CLEAN_STRUCTURED_CONTENT: "Embedded PHI",
    DeidMethodCode.CLEAN_DESCRIPTORS: "Embedded PHI",
}


def deid_option_explanation(code: DeidMethodCode) -> DeidOptionExplanation:
    """
    Plain-language explanation for a de-identification option.

    Args:
        code: DICOM confidentiality option code.

    Returns:
        DeidOptionExplanation for the dialog detail panel.

    Raises:
        KeyError: If code has no explanation entry.
    """
    code = DeidMethodCode(code)
    summary_en, when_en, notes_en = _COPY[code]
    when = _when_ai_batch(_AI_BATCH_FEATURE[code]) if code in _AI_BATCH_FEATURE else _(when_en)
    source_line = ""
    link_label = ""
    link_url = ""
    link_tooltip = ""
    if code is DeidMethodCode.SAFE_PRIVATE:
        source_line = _(
            "Keep/remove rules come from The Cancer Imaging Archive (TCIA) "
            "private-tag dictionary. This anonymizer ships the KB CSV at {path}."
        ).format(path=TCIA_PRIVATE_TAG_KB_ASSET_RELPATH)
        link_label = _("TCIA latest release")
        link_url = TCIA_PRIVATE_TAG_KB_PAGE_URL
        link_tooltip = _("View on wiki.cancerimagingarchive.net")
    return DeidOptionExplanation(
        title=_(deid_method_meaning(code)),
        summary=_(summary_en),
        when_it_runs=when,
        notes=_(notes_en) if notes_en else "",
        source_line=source_line,
        link_label=link_label,
        link_url=link_url,
        link_tooltip=link_tooltip,
    )


assert set(_COPY) == set(DeidMethodCode)
assert set(_ABBREVIATIONS) == set(DeidMethodCode)
