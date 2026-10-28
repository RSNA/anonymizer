"""Compile the anonymizer script from de-identification options.

Public API
----------
compile_script(options, base_script_path) -> ScriptDocument
    Compile the anonymizer script for the given options from a base .script file.

PATIENT_CHARACTERISTICS_TAGS
DEVICE_IDENTITY_TAGS
INSTITUTION_IDENTITY_TAGS
KEEP_DEVICE_TAGS
CLEAN_STRUCTURED_KEEP_TAGS
    Tag lists used by compile overlays and option inference (from E.1-1 catalog).
"""
import logging
from pathlib import Path

from anonymizer.controller.dates import is_date_delta_operation
from anonymizer.controller.script.date_rules import STUDY_DATE_TAG, study_date_operation
from anonymizer.controller.script.document import ScriptDocument, load_script_rules
from anonymizer.controller.script.operands import is_remove_operation
from anonymizer.controller.script.retain_option_tags import (
    device_identity_tags,
    institution_identity_tags,
    patient_age_tag,
    patient_characteristics_tags,
)
from anonymizer.utils.dicom import DeidMethodCode

logger = logging.getLogger(__name__)

# Lazy-stable tuples for tests and inference (full catalog sets).
PATIENT_CHARACTERISTICS_TAGS = patient_characteristics_tags()
DEVICE_IDENTITY_TAGS = device_identity_tags()
INSTITUTION_IDENTITY_TAGS = institution_identity_tags()

# Inference samples: tags Basic strips and Device Identity restores.
KEEP_DEVICE_TAGS = frozenset(
    {
        "00080070",  # Manufacturer (product extra)
        "00081090",  # ManufacturerModelName (product extra)
        "00181000",  # DeviceSerialNumber
        "00081010",  # StationName
        "00181020",  # SoftwareVersions (product extra)
    }
)

# Basic removes these; Clean Structured Content keeps them for Report View /
# AI Batch scrub (then rewrite). Encapsulated PDF + SR text tree.
CLEAN_STRUCTURED_KEEP_TAGS = frozenset(
    {
        "0040A040",  # ValueType
        "0040A123",  # PersonName (SR PNAME content items)
        "0040A160",  # TextValue
        "0040A730",  # ContentSequence
        "00420011",  # EncapsulatedDocument
        "00420012",  # MIMETypeOfEncapsulatedDocument
        "00420015",  # EncapsulatedDocumentLength
    }
)


def compile_script(
    options: frozenset[DeidMethodCode],
    base_script_path: Path,
) -> ScriptDocument:
    """
    Compile the project anonymizer script for a set of de-identification options.

    Starts from base_script_path, then applies option overlays. Retain Safe
    Private and most cleaning options have no script overlay (later tasks).
    Clean Structured Content keeps Encapsulated PDF / SR text tags at ingest
    so Report View and AI Batch can scrub them.

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
    age_tag = patient_age_tag()

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
            if tag == age_tag:
                continue
            set_operation(tag, "@keep")

    if DeidMethodCode.DEVICE_IDENTITY in selected:
        # @safe(): retain value and exclude from Embedded PHI / PseudoPHI NER
        # (device strings like ManufacturerModelName must not be blanked).
        for tag in DEVICE_IDENTITY_TAGS:
            set_operation(tag, "@safe()")

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

    if DeidMethodCode.CLEAN_STRUCTURED_CONTENT in selected:
        for tag in CLEAN_STRUCTURED_KEEP_TAGS:
            set_operation(tag, "@keep")

    return document


def normalize_script_operation(operation: str | None) -> str:
    """Normalize empty script operands to @keep for comparisons."""
    return str(operation or "").strip() or "@keep"


def script_operations_by_tag(document: ScriptDocument) -> dict[str, str]:
    """Uppercase tag → normalized operation for a script document."""
    return {
        rule.tag.upper(): normalize_script_operation(rule.operation)
        for rule in document.rules
    }


def basic_strip_ok(operation: str) -> bool:
    """True when a Basic operand strips or protects identity (remove/empty/round/date)."""
    op = normalize_script_operation(operation)
    if is_remove_operation(op) or op.startswith("@empty"):
        return True
    if op.startswith("@round"):
        return True
    return bool(is_date_delta_operation(op))
