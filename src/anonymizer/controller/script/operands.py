"""Script operand catalog and operation text helpers.

Public API
----------
OperandId
    Catalog id for one CTP / product script operand.

OperandSpec
    One supported script operand template.

OPERANDS
    Full operand catalog for the editor and validators.

operand_syntax(spec) -> str
    Script-style token shown in the editor.

operand_spec_by_id(operand_id) -> OperandSpec | None
    Lookup catalog entry by id.

operand_id_from_syntax(syntax) -> OperandId | None
    Map editor syntax token to catalog id.

always_literal_text(operation) -> str | None
    Fixed replacement text for @always()… or a bare non-@ literal.

is_remove_operation(operation) -> bool
    True when the operation removes the tag.

is_retain_value_operation(operation) -> bool
    True when the operation leaves the value in place (@keep or @safe).

format_operand(operand_id, ...) -> str
    Build stored operation text for an operand id.

operand_id_for_operation(operation) -> OperandId | None
    Map stored operation text to a catalog id.

validate_operation(operation) -> str | None
    Error message if invalid, else None.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_REMOVE_MARKER = "@remove"
_ROUND_RE = re.compile(r"^@round\(\s*this\s*,\s*(\d+)\s*\)$", re.IGNORECASE)
_INCREMENTDATE_RE = re.compile(r"^@incrementdate\(\s*this\s*,\s*(-?\d+)\s*\)$", re.IGNORECASE)
_REBASEDATE_RE = re.compile(r"^@rebasedate\(\s*this\s*,\s*(\d{8})\s*\)$", re.IGNORECASE)
_DEFAULT_REBASE_ORIGIN = "19600101"
_ALWAYS_RE = re.compile(r"^@always\(\)\s*(.*)$", re.IGNORECASE | re.DOTALL)


class OperandId(StrEnum):
    """Catalog id for one CTP / product script operand."""

    KEEP = "keep"
    SAFE = "safe"
    REMOVE = "remove"
    EMPTY = "empty"
    UID = "uid"
    PTID = "ptid"
    ACC = "acc"
    HASHDATE = "hashdate"
    LOOKUP_PTID = "lookup_ptid"
    LOOKUP_DATEOFFSET = "lookup_dateoffset"
    INCREMENTDATE = "incrementdate"
    REBASEDATE = "rebasedate"
    ROUND = "round"
    ALWAYS = "always"
    PROCESS = "process"


@dataclass(frozen=True)
class OperandSpec:
    """One supported script operand template."""

    id: OperandId
    label_key: str  # gettext msgid / English short label (docs / legacy)
    template: str  # stored operation text; use {n} for round width
    help_key: str  # gettext msgid: how this operand works (editor help panel)
    needs_param: bool = False
    param_title_key: str = ""  # gettext msgid: dialog title when prompting for a parameter
    param_help_key: str = ""  # gettext msgid: units/meaning when prompting for a parameter


# Catalog aligned with AnonymizerController._anonymize_element.
OPERANDS: tuple[OperandSpec, ...] = (
    OperandSpec(
        OperandId.KEEP,
        "Keep",
        "@keep",
        "Leave the value unchanged. In the script this is written as @keep. "
        "Kept free-text may still be scanned by Embedded PHI / report NER. Use "
        "@safe() for retained technical values that must not be NER-scrubbed.",
    ),
    OperandSpec(
        OperandId.SAFE,
        "Safe keep",
        "@safe()",
        "Product extension (not a CTP operand): leave the value unchanged and "
        "exclude it from Embedded PHI / PseudoPHI bulk NER. Use for equipment "
        "and other technical strings that must be retained but are not free-text "
        "PHI (for example ManufacturerModelName).",
    ),
    OperandSpec(
        OperandId.REMOVE,
        "Remove",
        "@remove()",
        "Delete the tag from the anonymized dataset. The element will not appear "
        "in the output file. Prefer Remove for PHI you do not need for analysis.",
    ),
    OperandSpec(
        OperandId.EMPTY,
        "Empty",
        "@empty()",
        "Keep the tag present but set its value to an empty string. Useful when "
        "a receiving system expects the attribute to exist without a value.",
    ),
    OperandSpec(
        OperandId.UID,
        "UID",
        "@uid",
        "Replace UIDs with stable anonymized UIDs. The same original UID always "
        "maps to the same anonymized UID within the project, preserving "
        "referential integrity across studies and series.",
    ),
    OperandSpec(
        OperandId.PTID,
        "Patient ID",
        "@ptid",
        "Replace the value with the project's anonymized Patient ID for this "
        "patient. Use on Patient ID and related identity fields that should "
        "follow the project's patient mapping.",
    ),
    OperandSpec(
        OperandId.ACC,
        "Accession",
        "@acc",
        "Replace the value with the anonymized Accession Number for this study "
        "(when one is assigned). Empty source values stay empty.",
    ),
    OperandSpec(
        OperandId.HASHDATE,
        "Hash date",
        "@hashdate",
        "Shift dates using a stable, patient-specific offset derived from the "
        "PHI Patient ID. Relative intervals between dates are preserved while "
        "absolute calendar dates are de-identified. When any date-delta operand "
        "runs, LongitudinalTemporalInformationModified is set to MODIFIED.",
    ),
    OperandSpec(
        OperandId.LOOKUP_PTID,
        "Lookup patient ID",
        "@lookup(this,ptid)",
        "Replace the value with the anonymized Patient ID from the project's "
        "patient lookup table (CTP .properties). If no table is loaded yet, "
        "Apply opens the lookup-table dialog. Use Replace Lookup Table "
        "on an existing @lookup rule to swap the file.",
    ),
    OperandSpec(
        OperandId.LOOKUP_DATEOFFSET,
        "Lookup date offset",
        "@lookup(this,dateoffset)",
        "Apply the per-patient date offset from the project's lookup table to "
        "this date value. Requires dateoffset entries in the table. If none are "
        "loaded yet, Apply opens the lookup-table dialog.",
    ),
    OperandSpec(
        OperandId.INCREMENTDATE,
        "Increment date",
        "@incrementdate(this,{n})",
        "Shift a date or datetime by a fixed number of days (CTP @incrementdate). "
        "The same offset is applied to every patient — use for a trial-wide DATEINC. "
        "Intervals between a patient's studies are preserved. Prefer @hashdate or "
        "lookup dateoffset when each patient needs a different offset.",
        needs_param=True,
        param_title_key="Increment date — day offset (DATEINC)",
        param_help_key=(
            "This sets a trial-wide DATEINC: the same day offset is applied to every patient.\n\n"
            "To keep intervals consistent across a study, every date-delta field listed below "
            "will be set to the same @incrementdate(this,n).\n\n"
            "Enter the day offset as a whole number (may be negative).\n"
            "Positive values move dates later; negative values move them earlier.\n"
            "Example with offset 42: 20200101 → 20200212."
        ),
    ),
    OperandSpec(
        OperandId.REBASEDATE,
        "Rebase date (TCIA)",
        "@rebasedate(this,{origin})",
        "TCIA / NCTN-style epoch rebase: anonymized_date = ORIGIN + (real_date − basedate). "
        "Requires basedate/<PatientID>=YYYYMMDD in the lookup table. The ORIGIN date is the "
        "operand parameter (default 19600101). Also writes LongitudinalTemporalOffsetFromEvent "
        "and Event Type REGISTRATION from StudyDate. If basedates are not loaded yet, "
        "Apply opens the lookup-table dialog first.",
        needs_param=True,
        param_title_key="Rebase date — epoch origin (YYYYMMDD)",
        param_help_key=(
            "Enter the epoch ORIGIN as YYYYMMDD (eight digits).\n\n"
            "Anonymized date = ORIGIN + (real date − basedate from the lookup table).\n"
            "Typical TCIA/NCTN origin is 19600101."
        ),
    ),
    OperandSpec(
        OperandId.ROUND,
        "Round age",
        "@round(this,{n})",
        "Round a DICOM age string down to the nearest multiple of a band width "
        "in years. Used for Patient Age (AS) so ages are coarsened for privacy "
        "while remaining roughly useful for analysis.",
        needs_param=True,
        param_title_key="Round age — band width (years)",
        param_help_key=(
            "Enter the age band width in whole years (integer ≥ 1).\n\n"
            "Ages are rounded down to the nearest multiple of this width.\n"
            "Example with width 5: age 23 → 20Y, age 29 → 25Y."
        ),
    ),
    OperandSpec(
        OperandId.ALWAYS,
        "Fixed value",
        "@always(){text}",
        "Set the tag to a fixed literal value. Written as @always()YES (CTP style). "
        "If the element is missing from the dataset, it is created. Bare literals "
        "such as YES in older scripts are the same operand. Use for de-identification "
        "stamps (for example PatientIdentityRemoved = YES).",
        needs_param=True,
        param_title_key="Fixed value — replacement text",
        param_help_key=(
            "Enter the fixed replacement text (for example YES or REMOVED).\n\n"
            "The value is written into the anonymized DICOM element. "
            "If the element is absent, @always() creates it."
        ),
    ),
    OperandSpec(
        OperandId.PROCESS,
        "Process sequence",
        "@process()",
        "CTP sequence operand: keep the sequence element and recursively apply "
        "script rules to items inside it (do not delete the SQ wrapper). "
        "Used for sequences TCIA marks as process (e.g. Content Sequence, "
        "Referenced Image Sequence).",
    ),
)

_OPERAND_BY_ID = {spec.id: spec for spec in OPERANDS}


def operand_syntax(spec: OperandSpec) -> str:
    """Script-style token shown in the editor (e.g. @keep, @round(this,n))."""
    if spec.id == OperandId.KEEP:
        return "@keep"
    if spec.id == OperandId.ALWAYS:
        return "@always()"
    if spec.needs_param:
        return spec.template.replace("{n}", "n").replace("{origin}", "origin")
    return spec.template


def operand_spec_by_id(operand_id: OperandId) -> OperandSpec | None:
    """
    Lookup catalog entry by id.

    Args:
        operand_id: Catalog id.

    Returns:
        Matching spec, or None.
    """
    return _OPERAND_BY_ID.get(operand_id)


def operand_id_from_syntax(syntax: str) -> OperandId | None:
    """
    Map editor syntax token to catalog id.

    Args:
        syntax: Token from operand_syntax.

    Returns:
        Matching id, or None.
    """
    for spec in OPERANDS:
        if operand_syntax(spec) == syntax:
            return spec.id
    return None


def always_literal_text(operation: str | None) -> str | None:
    """
    Return fixed replacement text for @always()… or a bare non-@ literal.

    Returns None when the operation is not a fixed-value form, when
    @always() has an empty remainder, or when the remainder starts with
    @ (chained CTP functions — unsupported in this pass).

    Args:
        operation: Script operation text.

    Returns:
        Literal text, or None.
    """
    text = str(operation or "").strip()
    if not text or text == "@keep":
        return None
    match = _ALWAYS_RE.match(text)
    if match is not None:
        remainder = str(match.group(1) or "")
        if not remainder or remainder.startswith("@"):
            return None
        return remainder
    if text.startswith("@"):
        return None
    return text


def is_remove_operation(operation: str | None) -> bool:
    """
    True when the operation removes the tag.

    Args:
        operation: Script operation text.

    Returns:
        True when @remove appears in the text.
    """
    return _REMOVE_MARKER in str(operation or "")


def is_retain_value_operation(operation: str | None) -> bool:
    """
    True when the operation leaves the value in place.

    Covers @keep (including empty operand normalized to keep) and @safe()
    (retain without NER scrubbing).

    Args:
        operation: Script operation text.

    Returns:
        True for keep / safe retain operands.
    """
    op = str(operation or "").strip()
    if not op or op == "@keep":
        return True
    return "@safe" in op


def format_operand(
    operand_id: OperandId,
    *,
    round_width: int | None = None,
    always_text: str | None = None,
    increment_days: int | None = None,
    rebase_origin: str | None = None,
) -> str:
    """
    Build stored operation text for operand_id.

    Args:
        operand_id: Catalog id.
        round_width: Band width for round age.
        always_text: Literal for fixed value.
        increment_days: Day offset for increment date.
        rebase_origin: ORIGIN YYYYMMDD for rebase date.

    Returns:
        Operation text to store on a rule.

    Raises:
        ValueError: Unknown id or invalid parameter.
    """
    spec = _OPERAND_BY_ID.get(operand_id)
    if spec is None:
        raise ValueError(f"Unknown operand id: {operand_id}")
    if operand_id == OperandId.KEEP:
        return "@keep"
    if operand_id == OperandId.ALWAYS:
        text = str(always_text if always_text is not None else "").strip()
        if not text:
            raise ValueError("Fixed value text must not be empty")
        if text.startswith("@"):
            raise ValueError("Fixed value must be literal text, not another @ operand")
        return f"@always(){text}"
    if operand_id == OperandId.INCREMENTDATE:
        if increment_days is None:
            raise ValueError("Increment date requires a day offset")
        return f"@incrementdate(this,{int(increment_days)})"
    if operand_id == OperandId.REBASEDATE:
        origin = str(rebase_origin if rebase_origin is not None else _DEFAULT_REBASE_ORIGIN).strip()
        if len(origin) != 8 or not origin.isdigit():
            raise ValueError("Rebase origin must be YYYYMMDD (eight digits)")
        try:
            datetime.strptime(origin, "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"Rebase origin is not a valid date: {origin}") from exc
        return f"@rebasedate(this,{origin})"
    if not spec.needs_param:
        return spec.template
    width = int(round_width or 0)
    if width < 1:
        raise ValueError("Round age width must be an integer >= 1")
    return spec.template.format(n=width)


def operand_id_for_operation(operation: str | None) -> OperandId | None:
    """
    Map stored operation text to a catalog id, or None if unrecognized.

    Args:
        operation: Script operation text.

    Returns:
        Catalog id, or None.
    """
    text = str(operation or "").strip()
    if text == "" or text == "@keep":
        return OperandId.KEEP
    if is_remove_operation(text):
        return OperandId.REMOVE
    for spec in OPERANDS:
        if spec.needs_param:
            continue
        if text == spec.template:
            return spec.id
    if _ROUND_RE.match(text):
        return OperandId.ROUND
    if _INCREMENTDATE_RE.match(text):
        return OperandId.INCREMENTDATE
    if _REBASEDATE_RE.match(text) or text.lower() == "@rebasedate":
        return OperandId.REBASEDATE
    if always_literal_text(text) is not None:
        return OperandId.ALWAYS
    return None


def validate_operation(operation: str | None) -> str | None:
    """
    Return an error message if invalid, else None.

    Known catalog operands are accepted, including @always()text and bare
    non-@ literals (CTP fixed values such as YES).

    Args:
        operation: Script operation text.

    Returns:
        Error message, or None when valid.
    """
    text = str(operation or "").strip()
    if text == "":
        text = "@keep"
    if text.lower() == "@always()":
        return "Unsupported operand: @always() requires a fixed value (e.g. @always()YES)"
    if operand_id_for_operation(text) is not None:
        return None
    return f"Unsupported operand: {text!r}"
