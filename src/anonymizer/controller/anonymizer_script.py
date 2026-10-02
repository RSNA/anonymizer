"""Anonymizer script load/edit/validate/commit (CTP-compatible XML)."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from anonymizer.controller.process_ctp_lookup import private_anonymizer_script_path

if TYPE_CHECKING:
    from anonymizer.controller.project import ProjectController
    from anonymizer.model.project import ProjectModel

logger = logging.getLogger(__name__)

_REMOVE_MARKER = "@remove"
_ROUND_RE = re.compile(r"^@round\(\s*this\s*,\s*(\d+)\s*\)$", re.IGNORECASE)
_INCREMENTDATE_RE = re.compile(r"^@incrementdate\(\s*this\s*,\s*(-?\d+)\s*\)$", re.IGNORECASE)
_REBASEDATE_RE = re.compile(r"^@rebasedate\(\s*this\s*,\s*(\d{8})\s*\)$", re.IGNORECASE)
_DEFAULT_REBASE_ORIGIN = "19600101"
_ALWAYS_RE = re.compile(r"^@always\(\)\s*(.*)$", re.IGNORECASE | re.DOTALL)
_TAG_HEX_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
_DATE_SHIFT_OPERAND_IDS = frozenset({"hashdate", "lookup_dateoffset", "incrementdate", "rebasedate"})
_PATIENT_ID_OPERAND_IDS = frozenset({"ptid", "lookup_ptid"})
_DATE_VRS = frozenset({"DA", "DT"})
_UID_VRS = frozenset({"UI"})
_AGE_VRS = frozenset({"AS"})
# Universal operands — never gated.
_UNRESTRICTED_OPERAND_IDS = frozenset({"keep", "remove", "empty", "always"})

PAGE_SIZE = 300


class ScriptViewMode(str, Enum):
    ACTIVE = "active"
    REMOVED = "removed"
    ALL = "all"


@dataclass(frozen=True)
class OperandSpec:
    """One supported script operand template."""

    id: str
    label_key: str  # gettext msgid / English short label (docs / legacy)
    template: str  # stored operation text; use {n} for round width
    help_key: str  # gettext msgid: how this operand works (editor help panel)
    needs_param: bool = False
    param_title_key: str = ""  # gettext msgid: dialog title when prompting for a parameter
    param_help_key: str = ""  # gettext msgid: units/meaning when prompting for a parameter


# Catalog aligned with AnonymizerController._anonymize_element.
OPERANDS: tuple[OperandSpec, ...] = (
    OperandSpec(
        "keep",
        "Keep",
        "",
        "Leave the value unchanged. In the script this is written as @keep "
        "(or an empty operation). Use this for tags that are not PHI and must "
        "stay exactly as received.",
    ),
    OperandSpec(
        "remove",
        "Remove",
        "@remove()",
        "Delete the tag from the anonymized dataset. The element will not appear "
        "in the output file. Prefer Remove for PHI you do not need for analysis.",
    ),
    OperandSpec(
        "empty",
        "Empty",
        "@empty()",
        "Keep the tag present but set its value to an empty string. Useful when "
        "a receiving system expects the attribute to exist without a value.",
    ),
    OperandSpec(
        "uid",
        "UID",
        "@uid",
        "Replace UIDs with stable anonymized UIDs. The same original UID always "
        "maps to the same anonymized UID within the project, preserving "
        "referential integrity across studies and series.",
    ),
    OperandSpec(
        "ptid",
        "Patient ID",
        "@ptid",
        "Replace the value with the project's anonymized Patient ID for this "
        "patient. Use on Patient ID and related identity fields that should "
        "follow the project's patient mapping.",
    ),
    OperandSpec(
        "acc",
        "Accession",
        "@acc",
        "Replace the value with the anonymized Accession Number for this study "
        "(when one is assigned). Empty source values stay empty.",
    ),
    OperandSpec(
        "hashdate",
        "Hash date",
        "@hashdate",
        "Shift dates using a stable, patient-specific offset derived from the "
        "PHI Patient ID. Relative intervals between dates are preserved while "
        "absolute calendar dates are de-identified. When any date-shift operand "
        "runs, LongitudinalTemporalInformationModified is set to MODIFIED.",
    ),
    OperandSpec(
        "lookup_ptid",
        "Lookup patient ID",
        "@lookup(this,ptid)",
        "Replace the value with the anonymized Patient ID from the project's "
        "patient lookup table (CTP .properties). If no table is loaded yet, "
        "Apply opens the lookup-table dialog. Use Replace Lookup Table "
        "on an existing @lookup rule to swap the file.",
    ),
    OperandSpec(
        "lookup_dateoffset",
        "Lookup date offset",
        "@lookup(this,dateoffset)",
        "Apply the per-patient date offset from the project's lookup table to "
        "this date value. Requires dateoffset entries in the table. If none are "
        "loaded yet, Apply opens the lookup-table dialog.",
    ),
    OperandSpec(
        "incrementdate",
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
            "To keep intervals consistent across a study, every date-shift field listed below "
            "will be set to the same @incrementdate(this,n).\n\n"
            "Enter the day offset as a whole number (may be negative).\n"
            "Positive values move dates later; negative values move them earlier.\n"
            "Example with offset 42: 20200101 → 20200212."
        ),
    ),
    OperandSpec(
        "rebasedate",
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
        "round",
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
        "always",
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
)

_OPERAND_BY_ID = {spec.id: spec for spec in OPERANDS}


def operand_syntax(spec: OperandSpec) -> str:
    """Script-style token shown in the editor (e.g. ``@keep``, ``@round(this,n)``)."""
    if spec.id == "keep":
        return "@keep"
    if spec.id == "always":
        return "@always()"
    if spec.needs_param:
        return spec.template.replace("{n}", "n").replace("{origin}", "origin")
    return spec.template


def display_operation(operation: str | None) -> str:
    """How an operation appears in the script list (always script syntax)."""
    text = normalize_operation(operation)
    if text == "":
        return "@keep"
    return text


def operand_spec_by_id(operand_id: str) -> OperandSpec | None:
    return _OPERAND_BY_ID.get(operand_id)


def operand_id_from_syntax(syntax: str) -> str | None:
    for spec in OPERANDS:
        if operand_syntax(spec) == syntax:
            return spec.id
    return None


def always_literal_text(operation: str | None) -> str | None:
    """Return fixed replacement text for ``@always()…`` or a bare non-``@`` literal.

    Returns ``None`` when the operation is not a fixed-value form, when
    ``@always()`` has an empty remainder, or when the remainder starts with
    ``@`` (chained CTP functions — unsupported in this pass).
    """
    text = normalize_operation(operation)
    if not text:
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


def is_date_shift_operation(operation: str | None) -> bool:
    """True when the operation shifts DA/DT values (triggers MODIFIED stamp)."""
    op_id = operand_id_for_operation(operation)
    return op_id in _DATE_SHIFT_OPERAND_IDS


def _normalize_tag_hex(tag: str) -> str | None:
    """Return 8-hex uppercase tag, or None if not a valid DICOM tag string."""
    text = str(tag or "").strip().upper().replace(",", "").replace(" ", "")
    if len(text) != 8 or any(c not in "0123456789ABCDEF" for c in text):
        return None
    return text


@dataclass(frozen=True)
class TagDictionaryMeta:
    """Part 6 dictionary fields for one public tag (from pydicom)."""

    tag: str
    description: str
    vr: str
    vm: str
    retired: bool
    keyword: str


def tag_dictionary_meta(tag: str) -> TagDictionaryMeta | None:
    """Look up Part 6 Name/VR/VM/retired/keyword for ``tag``, or None if unknown."""
    from pydicom.datadict import DicomDictionary

    hex_tag = _normalize_tag_hex(tag)
    if hex_tag is None:
        return None
    entry = DicomDictionary.get(int(hex_tag, 16))
    if entry is None or len(entry) < 5:
        return None
    vr = str(entry[0] or "")
    if " " in vr:
        vr = vr.split()[0]
    retired_raw = str(entry[3] or "").strip().lower()
    retired = retired_raw in {"retired", "y", "yes", "true", "1"}
    return TagDictionaryMeta(
        tag=hex_tag,
        description=str(entry[2] or "").strip(),
        vr=vr.upper(),
        vm=str(entry[1] or "").strip(),
        retired=retired,
        keyword=str(entry[4] or "").strip(),
    )


def format_tag_description_line(meta: TagDictionaryMeta, *, retired_label: str = "Retired") -> str:
    """One-line blurb: Part 6 Name, with retired suffix when applicable (no VM)."""
    name = (meta.description or "").strip()
    if meta.retired:
        label = str(retired_label or "Retired").strip() or "Retired"
        return f"{name} · {label}" if name else label
    return name


def dicom_standard_version() -> str:
    """DICOM Standard dated issue used for pydicom's public dictionary (e.g. ``2024c``)."""
    try:
        from pydicom._version import __dicom_version__
    except Exception:
        return ""
    return str(__dicom_version__ or "").strip()


def dicom_applicable_standard_text() -> str:
    """Display string for the script editor: major.minor family + pydicom dated issue.

    DICOM PS3 is version 3.0; pydicom's ``__dicom_version__`` is the NEMA dated
    edition of the dictionary (year + issue letter, e.g. ``2024c``).
    """
    edition = dicom_standard_version()
    if not edition:
        return ""
    return f"DICOM 3.0 ({edition})"


def tag_dictionary_vr(tag: str) -> str | None:
    """Return the DICOM dictionary VR for ``tag`` (8-hex), or None if unknown."""
    meta = tag_dictionary_meta(tag)
    return meta.vr if meta is not None and meta.vr else None


def format_dicom_tag(tag: str) -> str:
    """Format an 8-hex tag as DICOM ``GGGG,EEEE``; otherwise return stripped input."""
    hex_tag = _normalize_tag_hex(tag)
    if hex_tag is not None:
        return f"{hex_tag[:4]},{hex_tag[4:]}"
    return str(tag or "").strip()


def display_tag_vr(tag: str) -> str:
    """VR string for UI columns (first token of multi-VR entries)."""
    return tag_dictionary_vr(tag) or ""


def operand_tag_incompatibility(
    operand_id: str,
    *,
    tag: str,
    name: str = "",
) -> str | None:
    """Return a short warning if ``operand_id`` is a clear mismatch for this tag.

    Only a few hard gates — keep / remove / empty / always are never blocked.
    """
    op = str(operand_id or "").strip().lower()
    if not op or op in _UNRESTRICTED_OPERAND_IDS:
        return None

    vr = (tag_dictionary_vr(tag) or "").upper()
    # Multi-VR entries like "US or SS" — take the first token.
    if " " in vr:
        vr = vr.split()[0]
    label = (name or tag).strip() or tag
    spec = operand_spec_by_id(op)
    syntax = operand_syntax(spec) if spec is not None else f"@{op}"

    if op in _DATE_SHIFT_OPERAND_IDS:
        if vr and vr not in _DATE_VRS:
            return (
                f"{syntax} is for date/datetime tags (VR DA or DT). "
                f"{label} has VR {vr}."
            )
        if not vr and "uid" in label.lower():
            return f"{syntax} is for date/datetime tags, not UID fields such as {label}."
        return None

    if op == "uid":
        if vr and vr not in _UID_VRS:
            return f"{syntax} is for UID tags (VR UI). {label} has VR {vr}."
        if not vr and ("date" in label.lower() or "time" in label.lower()):
            return f"{syntax} is for UID tags, not date/time fields such as {label}."
        return None

    if op in _PATIENT_ID_OPERAND_IDS:
        if vr in _DATE_VRS or vr in _UID_VRS:
            return (
                f"{syntax} replaces patient identity values. "
                f"{label} has VR {vr} and is not a patient ID field."
            )
        return None

    if op == "acc":
        if vr in _DATE_VRS or vr in _UID_VRS:
            return (
                f"{syntax} is for accession numbers. "
                f"{label} has VR {vr}."
            )
        return None

    if op == "round":
        if vr and vr not in _AGE_VRS:
            return f"{syntax} is for age strings (VR AS). {label} has VR {vr}."
        return None

    return None


def operands_for_tag(*, tag: str, name: str = "") -> tuple[OperandSpec, ...]:
    """Catalog operands allowed for ``tag`` (VR / name gates only)."""
    return tuple(
        spec
        for spec in OPERANDS
        if operand_tag_incompatibility(spec.id, tag=tag, name=name) is None
    )


def incrementdate_days(operation: str | None) -> int | None:
    """Parse day offset from ``@incrementdate(this,N)``, or None if not that form."""
    text = normalize_operation(operation)
    match = _INCREMENTDATE_RE.match(text)
    if match is None:
        return None
    return int(match.group(1))


def rebasedate_origin(operation: str | None) -> str | None:
    """Parse ORIGIN YYYYMMDD from ``@rebasedate(this,YYYYMMDD)``, or default for bare ``@rebasedate``."""
    text = normalize_operation(operation)
    match = _REBASEDATE_RE.match(text)
    if match is not None:
        return match.group(1)
    if text.lower() == "@rebasedate":
        return _DEFAULT_REBASE_ORIGIN
    return None


@dataclass
class ScriptRule:
    tag: str
    name: str
    en: str
    operation: str


@dataclass
class ScriptRRule:
    """Preserved ``<r>`` elements (not edited by the UI)."""

    tag: str
    en: str
    text: str


@dataclass
class ScriptDocument:
    rules: list[ScriptRule] = field(default_factory=list)
    r_rules: list[ScriptRRule] = field(default_factory=list)
    source_path: Path | None = None

    def rule_index(self, tag: str) -> int | None:
        key = tag.upper()
        for index, rule in enumerate(self.rules):
            if rule.tag.upper() == key:
                return index
        return None

    def get_rule(self, tag: str) -> ScriptRule | None:
        index = self.rule_index(tag)
        return None if index is None else self.rules[index]


def rules_for_incrementdate_bulk(
    document: ScriptDocument, *, selected_tag: str | None = None
) -> list[ScriptRule]:
    """Rules that must share one DATEINC when ``@incrementdate`` is chosen.

    Includes every existing date-shift rule (``@hashdate``, lookup dateoffset,
    ``@incrementdate``, ``@rebasedate``) plus the selected rule when it is not
    already among them — so switching StudyDate from ``@hashdate`` also updates
    every other shifted date field.
    """
    by_tag: dict[str, ScriptRule] = {}
    for rule in document.rules:
        if is_date_shift_operation(rule.operation):
            by_tag[rule.tag.upper()] = rule
    if selected_tag:
        selected = document.get_rule(selected_tag)
        if selected is not None:
            by_tag[selected.tag.upper()] = selected
    return sorted(by_tag.values(), key=lambda r: r.tag.upper())


def apply_incrementdate_to_rules(
    document: ScriptDocument,
    days: int,
    *,
    selected_tag: str | None = None,
) -> list[str]:
    """Set bulk DATEINC rules to ``@incrementdate(this,days)``. Returns tags written."""
    operation = format_operand("incrementdate", increment_days=days)
    updated: list[str] = []
    for rule in rules_for_incrementdate_bulk(document, selected_tag=selected_tag):
        rule.operation = operation
        updated.append(rule.tag.upper())
    return updated


def format_incrementdate_affected_lines(rules: list[ScriptRule]) -> str:
    """Tag/name/current-operand lines for fields that will receive the shared DATEINC."""
    lines: list[str] = []
    for rule in rules:
        name = (rule.name or rule.tag).strip()
        current = display_operation(rule.operation)
        lines.append(f"{format_dicom_tag(rule.tag)}  {name}  ({current})")
    return "\n".join(lines)


@dataclass(frozen=True)
class DictHit:
    tag: str
    keyword: str
    vr: str
    description: str = ""


def is_remove_operation(operation: str | None) -> bool:
    return _REMOVE_MARKER in str(operation or "")


def normalize_operation(operation: str | None) -> str:
    """Normalize Keep variants to empty string (matches default script style)."""
    text = str(operation or "").strip()
    if text == "@keep":
        return ""
    return text


def format_operand(
    operand_id: str,
    *,
    round_width: int | None = None,
    always_text: str | None = None,
    increment_days: int | None = None,
    rebase_origin: str | None = None,
) -> str:
    spec = _OPERAND_BY_ID.get(operand_id)
    if spec is None:
        raise ValueError(f"Unknown operand id: {operand_id}")
    if operand_id == "always":
        text = str(always_text if always_text is not None else "").strip()
        if not text:
            raise ValueError("Fixed value text must not be empty")
        if text.startswith("@"):
            raise ValueError("Fixed value must be literal text, not another @ operand")
        return f"@always(){text}"
    if operand_id == "incrementdate":
        if increment_days is None:
            raise ValueError("Increment date requires a day offset")
        return f"@incrementdate(this,{int(increment_days)})"
    if operand_id == "rebasedate":
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


def operand_id_for_operation(operation: str | None) -> str | None:
    """Map stored operation text to a catalog id, or None if unrecognized."""
    text = normalize_operation(operation)
    if text == "":
        return "keep"
    if is_remove_operation(text):
        return "remove"
    for spec in OPERANDS:
        if spec.needs_param:
            continue
        if text == spec.template:
            return spec.id
    if _ROUND_RE.match(text):
        return "round"
    if _INCREMENTDATE_RE.match(text):
        return "incrementdate"
    if _REBASEDATE_RE.match(text) or text.lower() == "@rebasedate":
        return "rebasedate"
    if always_literal_text(text) is not None:
        return "always"
    return None


def validate_operation(operation: str | None) -> str | None:
    """Return an error message if invalid, else None.

    Known catalog operands are accepted, including ``@always()text`` and bare
    non-``@`` literals (CTP fixed values such as ``YES``). Empty ``@always()``
    and unknown ``@…`` operands are rejected. Chained forms after ``@always()``
    (e.g. ``@always()@date()``) are not supported in this pass.
    """
    text = normalize_operation(operation)
    if text.lower() == "@always()":
        return "Unsupported operand: @always() requires a fixed value (e.g. @always()YES)"
    if operand_id_for_operation(text) is not None:
        return None
    return f"Unsupported operand: {text!r}"


def load_script_rules(path: Path) -> ScriptDocument:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Script file not found: {path}")
    root = ET.parse(path).getroot()
    rules: list[ScriptRule] = []
    for element in root.findall("e"):
        tag = str(element.attrib.get("t", "") or "").upper()
        if not tag:
            continue
        rules.append(
            ScriptRule(
                tag=tag,
                name=str(element.attrib.get("n", "") or tag),
                en=str(element.attrib.get("en", "T") or "T"),
                operation=normalize_operation(element.text),
            )
        )
    r_rules: list[ScriptRRule] = []
    for element in root.findall("r"):
        r_rules.append(
            ScriptRRule(
                tag=str(element.attrib.get("t", "") or ""),
                en=str(element.attrib.get("en", "T") or "T"),
                text=str(element.text or ""),
            )
        )
    return ScriptDocument(rules=rules, r_rules=r_rules, source_path=path)


def write_script_rules(path: Path, document: ScriptDocument) -> None:
    """Write CTP-compatible script XML (full ``e`` list including ``@remove()``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<script>"]
    for rule in document.rules:
        op = normalize_operation(rule.operation)
        err = validate_operation(op)
        if err is not None:
            raise ValueError(f"{rule.tag}: {err}")
        name = rule.name or rule.tag
        en = rule.en or "T"
        lines.append(
            f' <e en="{_xml_attr(en)}" t="{_xml_attr(rule.tag.upper())}" n="{_xml_attr(name)}">{op}</e>'
        )
    for r_rule in document.r_rules:
        lines.append(
            f' <r en="{_xml_attr(r_rule.en or "T")}" t="{_xml_attr(r_rule.tag)}">{r_rule.text or ""}</r>'
        )
    lines.append("</script>")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _xml_attr(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def filter_rules(
    document: ScriptDocument,
    *,
    view: ScriptViewMode = ScriptViewMode.ACTIVE,
    query: str = "",
    operand_id: str | None = None,
) -> list[ScriptRule]:
    needle = str(query or "").strip().lower()
    results: list[ScriptRule] = []
    for rule in document.rules:
        removed = is_remove_operation(rule.operation)
        if view is ScriptViewMode.ACTIVE and removed:
            continue
        if view is ScriptViewMode.REMOVED and not removed:
            continue
        if operand_id is not None and operand_id_for_operation(rule.operation) != operand_id:
            continue
        if needle:
            hay = f"{rule.tag} {rule.name} {rule.operation}".lower()
            if needle not in hay:
                continue
        results.append(rule)
    return results


def search_removed_rules(
    document: ScriptDocument,
    query: str = "",
    *,
    limit: int = 50,
) -> list[ScriptRule]:
    limit = max(1, int(limit))
    return filter_rules(document, view=ScriptViewMode.REMOVED, query=query)[:limit]


def promote_rule(document: ScriptDocument, tag: str, operation: str = "") -> ScriptRule:
    """Promote an existing ``@remove`` rule to an Active operand."""
    op = normalize_operation(operation)
    err = validate_operation(op)
    if err is not None:
        raise ValueError(err)
    if is_remove_operation(op):
        raise ValueError("Promote requires a non-remove operand")
    existing = document.get_rule(tag)
    if existing is None:
        raise KeyError(f"Tag not in script: {tag}")
    if not is_remove_operation(existing.operation):
        raise ValueError(f"Tag {tag} is already Active")
    existing.operation = op
    return existing


def demote_rule(document: ScriptDocument, tag: str) -> ScriptRule:
    existing = document.get_rule(tag)
    if existing is None:
        raise KeyError(f"Tag not in script: {tag}")
    existing.operation = "@remove()"
    return existing


def add_rule_from_dictionary(
    document: ScriptDocument,
    *,
    tag: str,
    name: str,
    operation: str = "",
) -> ScriptRule:
    """Insert a new Active rule for a tag not already present in the script."""
    tag_u = str(tag).upper()
    if not _TAG_HEX_RE.match(tag_u):
        raise ValueError(f"Invalid DICOM tag hex: {tag!r}")
    if document.get_rule(tag_u) is not None:
        raise ValueError(f"Tag already in script: {tag_u}")
    op = normalize_operation(operation)
    err = validate_operation(op)
    if err is not None:
        raise ValueError(err)
    if is_remove_operation(op):
        raise ValueError("New Active rule cannot start as Remove")
    rule = ScriptRule(tag=tag_u, name=name or tag_u, en="T", operation=op)
    document.rules.append(rule)
    return rule


def search_dicom_dictionary(
    query: str,
    *,
    limit: int = 50,
    exclude_tags: set[str] | None = None,
) -> list[DictHit]:
    """Substring search over pydicom keyword dict (capped).

    Empty ``query`` lists the first ``limit`` tags (after exclusions) for browse UIs.
    Non-empty queries shorter than 2 characters return no hits.
    """
    from pydicom.datadict import DicomDictionary, keyword_dict

    needle = str(query or "").strip().lower()
    if needle and len(needle) < 2:
        return []
    limit = max(1, int(limit))
    excluded = {t.upper() for t in (exclude_tags or set())}
    hits: list[DictHit] = []
    # Prefer stable keyword order so empty browse is predictable.
    items = sorted(keyword_dict.items(), key=lambda kv: str(kv[0]).lower())
    for keyword, tag_int in items:
        name = str(keyword or "").strip()
        if not name:
            # pydicom can expose blank keywords for unnamed retired tags (e.g. 300A0782).
            continue
        tag = f"{int(tag_int):08X}"
        if tag in excluded:
            continue
        if needle and needle not in name.lower() and needle not in tag.lower():
            continue
        entry = DicomDictionary.get(tag_int)
        vr = ""
        description = ""
        if entry is not None and len(entry) >= 1:
            vr = str(entry[0] or "")
            if " " in vr:
                vr = vr.split()[0]
        if entry is not None and len(entry) >= 3:
            description = str(entry[2] or "").strip()
        hits.append(DictHit(tag=tag, keyword=name, vr=vr, description=description))
        if len(hits) >= limit:
            break
    return hits


def script_tag_set(document: ScriptDocument) -> set[str]:
    return {rule.tag.upper() for rule in document.rules}


def has_missing_dictionary_tags(document: ScriptDocument) -> bool:
    """True when at least one pydicom dictionary tag is absent from the script."""
    return bool(search_missing_dictionary_tags(document, "", limit=1))


def search_missing_dictionary_tags(
    document: ScriptDocument,
    query: str,
    *,
    limit: int = 50,
) -> list[DictHit]:
    """Search/browse dictionary tags that are not yet present in the script."""
    return search_dicom_dictionary(query, limit=limit, exclude_tags=script_tag_set(document))


def validate_document(document: ScriptDocument) -> list[str]:
    """Return all validation errors (empty if OK)."""
    errors: list[str] = []
    seen: set[str] = set()
    for rule in document.rules:
        tag = rule.tag.upper()
        if tag in seen:
            errors.append(f"Duplicate tag: {tag}")
        seen.add(tag)
        err = validate_operation(rule.operation)
        if err is not None:
            errors.append(f"{tag}: {err}")
    return errors


def commit_script_edit(project_controller: ProjectController, document: ScriptDocument) -> Path:
    """Write private script, update paths, reload AnonymizerModel, save ProjectModel."""
    errors = validate_document(document)
    if errors:
        raise ValueError("\n".join(errors[:20]))

    project_model = project_controller.model
    dest = private_anonymizer_script_path(project_model)
    write_script_rules(dest, document)

    project_model.anonymizer_script_path = dest
    project_controller.anonymizer.project_model.anonymizer_script_path = dest
    project_controller.anonymizer.model.reload_script(dest)
    project_controller.save_model()
    document.source_path = dest
    logger.info("Anonymizer script edit committed: %s (%d rules)", dest, len(document.rules))
    return dest


def stage_script_edit(project_model: ProjectModel, document: ScriptDocument) -> Path:
    """Write script under project private dir without reloading a live AnonymizerModel."""
    errors = validate_document(document)
    if errors:
        raise ValueError("\n".join(errors[:20]))
    private_dir = project_model.private_dir()
    private_dir.mkdir(parents=True, exist_ok=True)
    dest = private_anonymizer_script_path(project_model)
    write_script_rules(dest, document)
    project_model.anonymizer_script_path = dest
    document.source_path = dest
    logger.info("Anonymizer script staged for new project: %s", dest)
    return dest


def page_slice(
    items: list[ScriptRule], page: int, *, page_size: int = PAGE_SIZE
) -> tuple[list[ScriptRule], int, int]:
    """Return (page_items, page_index_clamped, page_count)."""
    page_size = max(1, int(page_size))
    total = len(items)
    page_count = max(1, (total + page_size - 1) // page_size) if total else 1
    page_index = max(0, min(int(page), page_count - 1))
    start = page_index * page_size
    end = start + page_size
    return items[start:end], page_index, page_count
