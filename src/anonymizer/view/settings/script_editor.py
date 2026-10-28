"""Script-document editing helpers for the anonymizer script settings dialog.

Public API
----------
ScriptViewMode, PAGE_SIZE
    List view modes and paging.

filter_rules, search_removed_rules, page_slice
    List filtering and paging.

promote_rule, demote_rule, add_rule_from_dictionary
    Rule edits for the editor.

search_missing_dictionary_tags, has_missing_dictionary_tags
    Add-from-dictionary helpers.

apply_incrementdate_to_rules, format_incrementdate_affected_lines
    DATEINC bulk presentation.

options_switch_confirm_message, embedded_phi_batch_explainer
    Settings copy.

available_operands, operands_for_tag, operand_tag_incompatibility
    Operand pickers for the editor.
"""
import re
from enum import Enum

from anonymizer.controller.script.date_rules import (
    rules_for_incrementdate_bulk,
)
from anonymizer.controller.script.document import (
    ScriptDocument,
    ScriptRule,
)
from anonymizer.controller.script.operands import (
    OPERANDS,
    OperandId,
    OperandSpec,
    format_operand,
    is_remove_operation,
    operand_id_for_operation,
    operand_spec_by_id,
    operand_syntax,
    validate_operation,
)
from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.utils.dicom_dictionary import (
    DictHit,
    format_dicom_tag,
    search_dicom_dictionary,
    tag_dictionary_vr,
)

PAGE_SIZE = 300
_TAG_HEX_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
_DATE_VRS = frozenset({"DA", "DT"})
_UID_VRS = frozenset({"UI"})
_AGE_VRS = frozenset({"AS"})
_DATE_DELTA_OPERAND_IDS = frozenset({
    OperandId.HASHDATE,
    OperandId.LOOKUP_DATEOFFSET,
    OperandId.INCREMENTDATE,
    OperandId.REBASEDATE,
})
_PATIENT_ID_OPERAND_IDS = frozenset({OperandId.PTID, OperandId.LOOKUP_PTID})
_UNRESTRICTED_OPERAND_IDS = frozenset({
    OperandId.KEEP,
    OperandId.SAFE,
    OperandId.REMOVE,
    OperandId.EMPTY,
    OperandId.ALWAYS,
    OperandId.PROCESS,
})


class ScriptViewMode(str, Enum):
    """Which script rules the editor list shows."""

    ACTIVE = "active"
    REMOVED = "removed"
    ALL = "all"


def options_switch_confirm_message() -> str:
    """
    English confirmation body when applying new de-identification options.

    Caller wraps with _ for translation.

    Returns:
        Confirmation message covering script replacement and consequences.
    """
    return (
        "Apply these de-identification options? This replaces your project "
        "anonymizer script with a script compiled from the selected options. "
        "Custom script edits will be lost.\n\n"
        "What does not change:\n"
        "• Already anonymized data is not re-processed.\n\n"
        "Selecting Clean Structured Content or Clean Descriptors enables SR "
        "and PDF modalities if they are not already selected. Enabling SR or "
        "PDF modalities enables Clean Structured Content when it is off."
    )


def embedded_phi_batch_explainer(options: frozenset[DeidMethodCode]) -> str:
    """
    English batch-dialog sentence (caller wraps with _). Pixels vs ingest text.

    Args:
        options: Project de-identification options.

    Returns:
        Sentence describing what ingest kept, before the OCR step.
    """
    if DeidMethodCode.SAFE_PRIVATE in options:
        return (
            "Retain Safe Private kept private and clinical tags at ingest. "
            "This step is OCR on burnt-in image pixels."
        )
    return (
        "Basic Profile already removed most private and clinical text at ingest. "
        "This step is OCR on burnt-in image pixels."
    )


def operand_tag_incompatibility(
    operand_id: OperandId,
    *,
    tag: str,
    name: str = "",
) -> str | None:
    """
    Return a short warning if operand_id is incompatible with tag.

    Args:
        operand_id: Catalog id.
        tag: Eight-hex DICOM tag.
        name: Attribute name for messages.

    Returns:
        Warning text, or None when compatible.
    """
    if operand_id in _UNRESTRICTED_OPERAND_IDS:
        return None

    vr = (tag_dictionary_vr(tag) or "").upper()
    if " " in vr:
        vr = vr.split()[0]
    label = (name or tag).strip() or tag
    spec = operand_spec_by_id(operand_id)
    syntax = operand_syntax(spec) if spec is not None else f"@{operand_id}"
    op = operand_id

    if op in _DATE_DELTA_OPERAND_IDS:
        if vr and vr not in _DATE_VRS:
            return (
                f"{syntax} is for date/datetime tags (VR DA or DT). "
                f"{label} has VR {vr}."
            )
        if not vr and "uid" in label.lower():
            return f"{syntax} is for date/datetime tags, not UID fields such as {label}."
        return None

    if op == OperandId.UID:
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

    if op == OperandId.ACC:
        if vr in _DATE_VRS or vr in _UID_VRS:
            return (
                f"{syntax} is for accession numbers. "
                f"{label} has VR {vr}."
            )
        return None

    if op == OperandId.ROUND:
        if vr and vr not in _AGE_VRS:
            return f"{syntax} is for age strings (VR AS). {label} has VR {vr}."
        return None

    return None


def available_operands(*, language_code: str | None = None) -> tuple[OperandSpec, ...]:
    """
    Catalog operands for the script editor.

    Args:
        language_code: Reserved for localized catalogs.

    Returns:
        Operand specs.
    """
    _ = language_code
    return OPERANDS


def operands_for_tag(
    *, tag: str, name: str = "", language_code: str | None = None
) -> tuple[OperandSpec, ...]:
    """
    Catalog operands allowed for tag (VR / name gates).

    Args:
        tag: Eight-hex DICOM tag.
        name: Attribute name.
        language_code: Reserved for localized catalogs.

    Returns:
        Compatible operand specs.
    """
    return tuple(
        spec
        for spec in available_operands(language_code=language_code)
        if operand_tag_incompatibility(spec.id, tag=tag, name=name) is None
    )


def filter_rules(
    document: ScriptDocument,
    *,
    view: ScriptViewMode = ScriptViewMode.ACTIVE,
    query: str = "",
    operand_id: OperandId | None = None) -> list[ScriptRule]:
    """
    Filter script rules for the editor list.

    Args:
        document: Script document.
        view: Active, removed, or all rules.
        query: Optional substring over tag/name/operation.
        operand_id: Optional operand filter.

    Returns:
        Matching rules in document order.
    """
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
    limit: int = 50) -> list[ScriptRule]:
    """
    Search removed rules for the restore picker.

    Args:
        document: Script document.
        query: Optional substring filter.
        limit: Maximum hits.

    Returns:
        Up to limit removed rules.
    """
    limit = max(1, int(limit))
    return filter_rules(document, view=ScriptViewMode.REMOVED, query=query)[:limit]


def promote_rule(document: ScriptDocument, tag: str, operation: str = "@keep") -> ScriptRule:
    """
    Promote an existing @remove rule to an Active operand.

    Args:
        document: Script document to mutate.
        tag: Tag to promote.
        operation: Non-remove operation to apply.

    Returns:
        The updated rule.

    Raises:
        KeyError: When the tag is not in the script.
        ValueError: When the operation is invalid or still remove.
    """
    op = str(operation or "").strip() or "@keep"
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
    """
    Demote a rule to @remove().

    Args:
        document: Script document to mutate.
        tag: Tag to demote.

    Returns:
        The updated rule.

    Raises:
        KeyError: When the tag is not in the script.
    """
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
    operation: str = "@keep") -> ScriptRule:
    """
    Insert a new Active rule for a tag not already present in the script.

    Args:
        document: Script document to mutate.
        tag: Eight-hex DICOM tag.
        name: Attribute name for the rule.
        operation: Non-remove operation to store.

    Returns:
        The new rule.

    Raises:
        ValueError: When the tag/operation is invalid or already present.
    """
    tag_u = str(tag).upper()
    if not _TAG_HEX_RE.match(tag_u):
        raise ValueError(f"Invalid DICOM tag hex: {tag!r}")
    if document.get_rule(tag_u) is not None:
        raise ValueError(f"Tag already in script: {tag_u}")
    op = str(operation or "").strip() or "@keep"
    err = validate_operation(op)
    if err is not None:
        raise ValueError(err)
    if is_remove_operation(op):
        raise ValueError("New Active rule cannot start as Remove")
    rule = ScriptRule(tag=tag_u, name=name or tag_u, en="T", operation=op)
    document.rules.append(rule)
    return rule


def script_tag_set(document: ScriptDocument) -> set[str]:
    """
    Uppercase tags present in the script.

    Args:
        document: Script document.

    Returns:
        Set of 8-hex tags.
    """
    return {rule.tag.upper() for rule in document.rules}


def has_missing_dictionary_tags(document: ScriptDocument) -> bool:
    """
    True when at least one pydicom dictionary tag is absent from the script.

    Args:
        document: Script document.

    Returns:
        True when any dictionary tag is missing.
    """
    return bool(search_missing_dictionary_tags(document, "", limit=1))


def search_missing_dictionary_tags(
    document: ScriptDocument,
    query: str,
    *,
    limit: int = 50) -> list[DictHit]:
    """
    Search/browse dictionary tags that are not yet present in the script.

    Args:
        document: Script document.
        query: Keyword/tag substring.
        limit: Maximum hits.

    Returns:
        Dictionary hits not already in the script.
    """
    return search_dicom_dictionary(query, limit=limit, exclude_tags=script_tag_set(document))


def apply_incrementdate_to_rules(
    document: ScriptDocument,
    days: int,
    *,
    selected_tag: str | None = None) -> list[str]:
    """
    Set bulk DATEINC rules to @incrementdate(this,days).

    Args:
        document: Script document to mutate.
        days: Day offset to write.
        selected_tag: Optional tag to include even if not already a date-delta.

    Returns:
        Uppercase tags whose operation was written.
    """
    operation = format_operand(OperandId.INCREMENTDATE, increment_days=days)
    updated: list[str] = []
    for rule in rules_for_incrementdate_bulk(document, selected_tag=selected_tag):
        rule.operation = operation
        updated.append(rule.tag.upper())
    return updated


def format_incrementdate_affected_lines(rules: list[ScriptRule]) -> str:
    """
    Tag/name/current-operand lines for fields that will receive shared DATEINC.

    Args:
        rules: Rules that will be updated.

    Returns:
        Multi-line display string for the confirm dialog.
    """
    lines: list[str] = []
    for rule in rules:
        name = (rule.name or rule.tag).strip()
        current = str(rule.operation or "").strip() or "@keep"
        lines.append(f"{format_dicom_tag(rule.tag)}  {name}  ({current})")
    return "\n".join(lines)


def page_slice(
    items: list[ScriptRule], page: int, *, page_size: int = PAGE_SIZE
) -> tuple[list[ScriptRule], int, int]:
    """
    Return one page of rules.

    Args:
        items: Filtered rule list.
        page: Requested page index.
        page_size: Rows per page.

    Returns:
        (page_items, page_index_clamped, page_count).
    """
    page_size = max(1, int(page_size))
    total = len(items)
    page_count = max(1, (total + page_size - 1) // page_size) if total else 1
    page_index = max(0, min(int(page), page_count - 1))
    start = page_index * page_size
    end = start + page_size
    return items[start:end], page_index, page_count
