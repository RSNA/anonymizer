"""CTP script operand aliases → product forms for Import CTP Script.

Purpose
    Rewrite common CTP DICOM Anonymizer operation spellings into the product
    catalog before validate_document. Used on import only; runtime keeps the
    product operand forms.

Public API
----------
normalize_ctp_document(document, *, dateinc=None) -> list[str]
    Mutate rule operations to product forms; return human-readable warnings.

unresolved_dateinc_tags(document) -> list[str]
    Tags still using @incrementdate(this,@DATEINC) after normalize.

unresolved_param_names(document) -> list[str]
    <p> parameter names still referenced by @always()@param(@NAME).

format_validation_errors(errors, *, limit=20) -> str
    Group Unsupported operand messages for import/reload dialogs.
"""
from __future__ import annotations

import re
from collections import defaultdict

from anonymizer.controller.script.document import ScriptDocument, ScriptRule

_KEEP_PARENS_RE = re.compile(r"^@keep\(\s*\)$", re.IGNORECASE)
_HASHDATE_PATIENT_ID_RE = re.compile(
    r"^@hashdate\(\s*this\s*,\s*PatientID\s*\)$",
    re.IGNORECASE,
)
_HASHUID_RE = re.compile(r"^@hashuid\s*\(.*\)\s*$", re.IGNORECASE)
_HASHPTID_RE = re.compile(r"^@hashptid\s*\(.*\)\s*$", re.IGNORECASE)
_INCREMENT_DATEINC_RE = re.compile(
    r"^@incrementdate\(\s*this\s*,\s*@DATEINC\s*\)$",
    re.IGNORECASE,
)
_ROUND_ELEMENT_RE = re.compile(
    r"^@round\(\s*([^,]+)\s*,\s*(\d+)\s*\)$",
    re.IGNORECASE,
)
_LOOKUP_PATIENTID_PTID_RE = re.compile(
    r"^@lookup\(\s*PatientID\s*,\s*ptid\s*\)$",
    re.IGNORECASE,
)
_ALWAYS_PARAM_RE = re.compile(
    r"^@always\(\)\s*@param\(\s*@([A-Za-z0-9_]+)\s*\)\s*$",
    re.IGNORECASE,
)
_ALWAYS_APPEND_RE = re.compile(
    r"^@always\(\)\s*@append\(\)\s*\{(.*)\}\s*$",
    re.IGNORECASE | re.DOTALL,
)
_ALWAYS_LOOKUP_RE = re.compile(
    r"^@always\(\)\s*@lookup\(\s*PatientID\s*,\s*(cname|siteid|ddate)\s*\)$",
    re.IGNORECASE,
)
_ALWAYS_MODIFYDATE_YEAR_RE = re.compile(
    r"^@always\(\)\s*@modifydate\(\s*StudyDate\s*,\s*\*\s*,\s*1\s*,\s*1\s*\)$",
    re.IGNORECASE,
)
_ALWAYS_DATEINTERVAL_STUDY_DDATE_RE = re.compile(
    r"^@always\(\)\s*@dateinterval\(\s*StudyDate\s*,\s*ddate\s*,\s*PatientID\s*\)$",
    re.IGNORECASE,
)
_UNSUPPORTED_OPERAND_RE = re.compile(
    r"^([0-9A-Fa-f]{8}):\s*Unsupported operand:\s*(.+)$"
)


def normalize_ctp_document(
    document: ScriptDocument,
    *,
    dateinc: int | None = None,
) -> list[str]:
    """
    Rewrite CTP-style operations on document rules into product forms.

    Args:
        document: Script document to mutate in place.
        dateinc: Day offset when resolving @DATEINC; when None, use
            document.params['DATEINC'] if present and integer-valued.

    Returns:
        Warning strings for semantic substitutes (empty when none).
    """
    warnings: list[str] = []
    seen_warning: set[str] = set()

    def _warn(message: str) -> None:
        if message not in seen_warning:
            seen_warning.add(message)
            warnings.append(message)

    for message in _dedupe_rules_last_wins(document):
        _warn(message)

    resolved_dateinc = dateinc
    if resolved_dateinc is None:
        resolved_dateinc = _param_int(document.params.get("DATEINC"))

    for rule in document.rules:
        op = str(rule.operation or "").strip() or "@keep"
        new_op, warn = _normalize_operation(
            op,
            dateinc=resolved_dateinc,
            params=document.params,
        )
        if warn:
            _warn(warn)
        rule.operation = new_op
    return warnings


def unresolved_dateinc_tags(document: ScriptDocument) -> list[str]:
    """
    Tags whose operation is still @incrementdate(this,@DATEINC).

    Args:
        document: Script document after normalize_ctp_document.

    Returns:
        Uppercase tag strings in document order.
    """
    out: list[str] = []
    for rule in document.rules:
        op = str(rule.operation or "").strip()
        if _INCREMENT_DATEINC_RE.match(op):
            out.append(rule.tag.upper())
    return out


def unresolved_param_names(document: ScriptDocument) -> list[str]:
    """
    Parameter names still referenced by unresolved @always()@param(@NAME).

    Args:
        document: Script document (before or after a normalize pass).

    Returns:
        Unique parameter names in first-seen order.
    """
    out: list[str] = []
    seen: set[str] = set()
    for rule in document.rules:
        match = _ALWAYS_PARAM_RE.match(str(rule.operation or "").strip())
        if match is None:
            continue
        name = match.group(1)
        if name in seen:
            continue
        value = str(document.params.get(name, "") or "").strip()
        if value:
            continue
        seen.add(name)
        out.append(name)
    return out


def format_validation_errors(errors: list[str], *, limit: int = 20) -> str:
    """
    Format validation errors, grouping identical Unsupported operand texts.

    Args:
        errors: Messages from validate_document.
        limit: Maximum lines in the returned string.

    Returns:
        Multi-line string for dialogs.
    """
    if not errors:
        return ""
    by_operand: dict[str, list[str]] = defaultdict(list)
    other: list[str] = []
    for err in errors:
        match = _UNSUPPORTED_OPERAND_RE.match(err.strip())
        if match is None:
            other.append(err)
            continue
        tag, operand = match.group(1).upper(), match.group(2).strip()
        by_operand[operand].append(tag)

    lines: list[str] = []
    for operand, tags in by_operand.items():
        preview = ", ".join(tags[:8])
        more = f" (+{len(tags) - 8} more)" if len(tags) > 8 else ""
        lines.append(f"Unsupported operand {operand} on {preview}{more}")
    lines.extend(other)
    return "\n".join(lines[:limit])


def _dedupe_rules_last_wins(document: ScriptDocument) -> list[str]:
    """Keep the last rule per tag; return warnings for dropped duplicates."""
    counts: dict[str, int] = defaultdict(int)
    for rule in document.rules:
        counts[rule.tag.upper()] += 1
    dup_tags = {tag for tag, count in counts.items() if count > 1}
    if not dup_tags:
        return []

    kept: list[ScriptRule] = []
    seen: set[str] = set()
    for rule in reversed(document.rules):
        key = rule.tag.upper()
        if key in seen:
            continue
        seen.add(key)
        kept.append(rule)
    document.rules = list(reversed(kept))
    preview = ", ".join(sorted(dup_tags)[:8])
    more = f" (+{len(dup_tags) - 8} more)" if len(dup_tags) > 8 else ""
    return [f"Duplicate tags kept last rule only: {preview}{more}"]


def _normalize_operation(
    operation: str,
    *,
    dateinc: int | None,
    params: dict[str, str],
) -> tuple[str, str | None]:
    """Return (product operation, optional warning)."""
    text = str(operation or "").strip() or "@keep"

    if _KEEP_PARENS_RE.match(text):
        return "@keep", None

    if _HASHDATE_PATIENT_ID_RE.match(text):
        return "@hashdate", None

    if _HASHUID_RE.match(text):
        return (
            "@uid",
            "@hashuid was rewritten to @uid (project UID map, not CTP hash+root).",
        )

    if _HASHPTID_RE.match(text):
        return (
            "@ptid",
            "@hashptid was rewritten to @ptid (project patient-id map).",
        )

    if _LOOKUP_PATIENTID_PTID_RE.match(text):
        return "@lookup(this,ptid)", None

    if _INCREMENT_DATEINC_RE.match(text):
        if dateinc is None:
            return text, None
        return f"@incrementdate(this,{int(dateinc)})", None

    append_match = _ALWAYS_APPEND_RE.match(text)
    if append_match is not None:
        body = str(append_match.group(1) or "").strip()
        if not body:
            return text, None
        return f"@always(){body}", None

    param_match = _ALWAYS_PARAM_RE.match(text)
    if param_match is not None:
        name = param_match.group(1)
        value = str(params.get(name, "") or "").strip()
        if not value:
            return text, None
        return f"@always(){value}", None

    always_lookup = _ALWAYS_LOOKUP_RE.match(text)
    if always_lookup is not None:
        key = always_lookup.group(1).lower()
        return f"@lookup(this,{key})", None

    if _ALWAYS_MODIFYDATE_YEAR_RE.match(text):
        return "@modifydate(StudyDate,*,1,1)", None

    if _ALWAYS_DATEINTERVAL_STUDY_DDATE_RE.match(text):
        return "@dateinterval(StudyDate,ddate,PatientID)", None

    round_match = _ROUND_ELEMENT_RE.match(text)
    if round_match is not None:
        element = round_match.group(1).strip()
        width = round_match.group(2)
        if element.lower() != "this":
            return (
                f"@round(this,{width})",
                "@round uses this element only; product rounds age down (not CTP group center).",
            )
        return f"@round(this,{width})", None

    return text, None


def _param_int(raw: str | None) -> int | None:
    """Parse a script <p> value as int, or None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None
