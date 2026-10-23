"""StudyDate strategy helpers on a script document.

A project carries exactly one date strategy, defined by the StudyDate rule.

Public API
----------
STUDY_DATE_TAG
    DICOM tag for Study Date (00080020).

study_date_operation(document) -> str
    Operation text on the StudyDate rule.

mismatched_date_rules(document) -> list[ScriptRule]
    Date-shift rules whose operand differs from StudyDate.

apply_study_date_operation_to_rules(document) -> list[str]
    Set every date-delta rule to the StudyDate operation.

rules_for_incrementdate_bulk(document, selected_tag=None) -> list[ScriptRule]
    Rules that must share one DATEINC when @incrementdate is chosen.
"""
from anonymizer.controller.dates import is_date_delta_operation
from anonymizer.controller.script.document import ScriptDocument, ScriptRule

STUDY_DATE_TAG = "00080020"


def study_date_operation(document: ScriptDocument) -> str:
    """
    Operation on the StudyDate rule of document.

    Args:
        document: Script document to inspect.

    Returns:
        The StudyDate operation text, or @keep when no such rule exists.
    """
    rule = document.get_rule(STUDY_DATE_TAG)
    if rule is None:
        return "@keep"
    return str(rule.operation or "").strip() or "@keep"


def mismatched_date_rules(document: ScriptDocument) -> list[ScriptRule]:
    """
    Date-shift rules whose operand differs from the StudyDate operand.

    Args:
        document: Script document to check.

    Returns:
        Rules with a date-delta operation different from StudyDate's.
    """
    expected = study_date_operation(document)
    mismatched: list[ScriptRule] = []
    for rule in document.rules:
        if rule.tag.upper() == STUDY_DATE_TAG:
            continue
        op = str(rule.operation or "").strip() or "@keep"
        if is_date_delta_operation(op) and op != expected:
            mismatched.append(rule)
    return mismatched


def apply_study_date_operation_to_rules(document: ScriptDocument) -> list[str]:
    """
    Set every date-delta rule to the StudyDate rule's operation.

    Args:
        document: Script document to mutate.

    Returns:
        Uppercase tags whose operation was rewritten.
    """
    operation = study_date_operation(document)
    updated: list[str] = []
    for rule in rules_for_incrementdate_bulk(document):
        current = str(rule.operation or "").strip() or "@keep"
        if current != operation:
            rule.operation = operation
            updated.append(rule.tag.upper())
    return updated


def rules_for_incrementdate_bulk(
    document: ScriptDocument, *, selected_tag: str | None = None
) -> list[ScriptRule]:
    """
    Rules that must share one DATEINC when @incrementdate is chosen.

    Includes every existing date-delta rule plus the selected rule when it is
    not already among them.

    Args:
        document: Script document.
        selected_tag: Optional tag being edited.

    Returns:
        Rules sorted by tag.
    """
    by_tag: dict[str, ScriptRule] = {}
    for rule in document.rules:
        if is_date_delta_operation(rule.operation):
            by_tag[rule.tag.upper()] = rule
    if selected_tag:
        selected = document.get_rule(selected_tag)
        if selected is not None:
            by_tag[selected.tag.upper()] = selected
    return sorted(by_tag.values(), key=lambda r: r.tag.upper())
