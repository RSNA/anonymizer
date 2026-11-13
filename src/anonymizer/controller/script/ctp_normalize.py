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

format_validation_errors(errors, *, limit=20) -> str
    Group Unsupported operand messages for import/reload dialogs.
"""
from __future__ import annotations

import re
from collections import defaultdict

from anonymizer.controller.script.document import ScriptDocument

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
    resolved_dateinc = dateinc
    if resolved_dateinc is None:
        resolved_dateinc = _param_int(document.params.get("DATEINC"))

    warnings: list[str] = []
    seen_warning: set[str] = set()

    def _warn(message: str) -> None:
        if message not in seen_warning:
            seen_warning.add(message)
            warnings.append(message)

    for rule in document.rules:
        op = str(rule.operation or "").strip() or "@keep"
        new_op, warn = _normalize_operation(op, dateinc=resolved_dateinc)
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


def _normalize_operation(
    operation: str,
    *,
    dateinc: int | None,
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

    if _INCREMENT_DATEINC_RE.match(text):
        if dateinc is None:
            return text, None
        return f"@incrementdate(this,{int(dateinc)})", None

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
