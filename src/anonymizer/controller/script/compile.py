"""Compile the anonymizer script from de-identification options.

Public API
----------
compile_script(options, base_script_path) -> ScriptDocument
    Compile the anonymizer script for the given options from a base .script file.

PATIENT_CHARACTERISTICS_TAGS
DEVICE_IDENTITY_TAGS
INSTITUTION_IDENTITY_TAGS
KEEP_DEVICE_TAGS
    Tag lists used by compile overlays and option inference.
"""
from __future__ import annotations

import logging
from pathlib import Path

from anonymizer.controller.dates import is_date_delta_operation
from anonymizer.controller.script.date_rules import STUDY_DATE_TAG, study_date_operation
from anonymizer.controller.script.document import ScriptDocument, load_script_rules
from anonymizer.utils.dicom import DeidMethodCode

logger = logging.getLogger(__name__)

PATIENT_CHARACTERISTICS_TAGS = (
    "00100040",
    "00101010",
    "00101020",
    "00101030",
    "00102160",
    "001021A0",
)
DEVICE_IDENTITY_TAGS = (
    "00080070",
    "00081090",
    "00181000",
    "00081010",
    "00181020",
)
INSTITUTION_IDENTITY_TAGS = (
    "00080080",
    "00080081",
    "00080082",
    "00081040",
    "00081041",
)
KEEP_DEVICE_TAGS = frozenset({"00181000", "00081010"})


def compile_script(
    options: frozenset[DeidMethodCode],
    base_script_path: Path,
) -> ScriptDocument:
    """
    Compile the project anonymizer script for a set of de-identification options.

    Starts from base_script_path, then applies option overlays. Retain Safe
    Private and the cleaning options have no script overlay; they act at
    ingest or in later tasks.

    Args:
        options: Selected de-identification options (Basic Profile is forced in).
        base_script_path: .script file to load before overlays (usually the
            packaged default).

    Returns:
        The compiled script document.
    """
    selected = frozenset(DeidMethodCode(code) for code in options) | {DeidMethodCode.BASIC}
    document = load_script_rules(Path(base_script_path))
    base_ops = {rule.tag.upper(): rule.operation for rule in document.rules}

    def set_operation(tag: str, operation: str) -> None:
        """
        Set one existing rule's operation.

        Args:
            tag: Eight-hex-digit tag.
            operation: Operation text to store.
        """
        rule = document.get_rule(tag)
        if rule is not None:
            rule.operation = operation

    if DeidMethodCode.PATIENT_CHARACTERISTICS in selected:
        for tag in PATIENT_CHARACTERISTICS_TAGS:
            if document.get_rule(tag) is None:
                continue
            # Keep PatientAge band rounding from the default script.
            if tag == "00101010":
                continue
            set_operation(tag, "@keep")

    if DeidMethodCode.DEVICE_IDENTITY in selected:
        for tag in DEVICE_IDENTITY_TAGS:
            set_operation(tag, "@keep")

    if DeidMethodCode.INSTITUTION_IDENTITY in selected:
        for tag in INSTITUTION_IDENTITY_TAGS:
            set_operation(tag, "@keep")

    date_tags = {
        tag for tag, op in base_ops.items() if is_date_delta_operation(op)
    }
    if DeidMethodCode.FULL_DATES in selected:
        for tag in sorted(date_tags):
            if document.get_rule(tag) is not None:
                set_operation(tag, "@keep")
    elif DeidMethodCode.MODIFIED_DATES in selected:
        operand = study_date_operation(document)
        if not is_date_delta_operation(operand):
            operand = base_ops.get(STUDY_DATE_TAG, "@hashdate")
        for tag in sorted(date_tags):
            if document.get_rule(tag) is not None:
                set_operation(tag, operand)

    if DeidMethodCode.RETAIN_UIDS in selected:
        for rule in document.rules:
            if "@uid" in rule.operation:
                rule.operation = "@keep"
    return document
