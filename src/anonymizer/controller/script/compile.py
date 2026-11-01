"""Compile the anonymizer script from de-identification options.

Public API
----------
compile_script(options, base_script_path) -> ScriptDocument
    Compile the anonymizer script for the given options from a base .script file.

project_script_operations(project_dir) -> dict[str, str]
    Tag→operand map from the project's compiled *-anonymizer.script (for NER).

PATIENT_CHARACTERISTICS_TAGS
DEVICE_IDENTITY_TAGS
INSTITUTION_IDENTITY_TAGS
PRODUCT_DEVICE_IDENTITY_EXTRA_TAGS
KEEP_DEVICE_TAGS
CLEAN_STRUCTURED_KEEP_TAGS
TCIA_RESEARCH_OPERANDS
    Tag→operand map for Retain TCIA Research (answer-key tags still remove/empty
    after other retain options, plus product device manufacturer/model/software
    and Clinical Trial Sponsor Name as @safe(), Patient Age as @keep); used by
    compile and option inference.

CLINICAL_TRIAL_SPONSOR_NAME_TAG
    (0012,0010) — TCIA Research @safe() so Clean Descriptors does not blank
    grant/sponsor codes.
"""
import json
import logging
from functools import lru_cache
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
    product_device_identity_extra_tags,
)
from anonymizer.utils.dicom import DeidMethodCode

logger = logging.getLogger(__name__)

_TCIA_RESEARCH_OPERANDS_PATH = Path(__file__).with_name("tcia_research_operands.json")

# Lazy-stable tuples for tests and inference (full catalog sets).
PATIENT_CHARACTERISTICS_TAGS = patient_characteristics_tags()
DEVICE_IDENTITY_TAGS = device_identity_tags()
INSTITUTION_IDENTITY_TAGS = institution_identity_tags()
PRODUCT_DEVICE_IDENTITY_EXTRA_TAGS = product_device_identity_extra_tags()

# Inference samples: E.1-1 device tags Basic strips and only Device Identity
# restores (not the TCIA Research manufacturer/model/software extras).
KEEP_DEVICE_TAGS = frozenset(
    {
        "00181000",  # DeviceSerialNumber
        "00081010",  # StationName
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

# Clinical Trial Sponsor Name — Basic D/@empty; MIDI-B text_retained; NER
# false-IDs grant codes (e.g. NIH_RO1-CA…) unless excluded from Clean Descriptors.
CLINICAL_TRIAL_SPONSOR_NAME_TAG = "00120010"

@lru_cache(maxsize=1)
def _load_tcia_research_operands() -> dict[str, str]:
    """
    Load Retain TCIA Research tag→operand map from the committed catalog.

    Built from the MIDI-B Validation answer key (see
    prototyping.midi_b.build_tcia_research_operands). Always merges product
    device-identity extras and Clinical Trial Sponsor Name as @safe(), and
    Patient Age as @keep.

    Returns:
        Uppercase eight-hex tag → script operand.
    """
    raw = json.loads(_TCIA_RESEARCH_OPERANDS_PATH.read_text(encoding="utf-8"))
    operands = raw.get("operands") or {}
    result = {
        str(tag).upper(): str(operation)
        for tag, operation in operands.items()
        if str(tag).strip() and str(operation).strip()
    }
    for tag in PRODUCT_DEVICE_IDENTITY_EXTRA_TAGS:
        result[tag] = "@safe()"
    result[CLINICAL_TRIAL_SPONSOR_NAME_TAG] = "@safe()"
    result[patient_age_tag()] = "@keep"
    return result


# Answer-key public tags that stay @remove/@empty after other retain options,
# plus product device extras and Clinical Trial Sponsor Name as @safe(), and
# Patient Age as @keep. Applied last: rewrites when still @remove/@empty or
# @round (so TCIA can replace Basic age banding with @keep).
TCIA_RESEARCH_OPERANDS: dict[str, str] = _load_tcia_research_operands()


def _is_remove_or_empty(operation: str | None) -> bool:
    """True when the script operation removes the attribute or empties its value."""
    op = normalize_script_operation(operation)
    return is_remove_operation(op) or op.startswith("@empty")


def _tcia_may_rewrite(operation: str | None) -> bool:
    """True when Retain TCIA Research may replace this script operation."""
    op = normalize_script_operation(operation)
    return _is_remove_or_empty(op) or op.startswith("@round")


def compile_script(
    options: frozenset[DeidMethodCode],
    base_script_path: Path,
) -> ScriptDocument:
    """
    Compile the project anonymizer script for a set of de-identification options.

    Starts from base_script_path, then applies each selected option's script
    changes. Retain Safe Private and most cleaning options have no script
    changes here (later tasks). Clean Structured Content keeps Encapsulated
    PDF / SR text tags at ingest so Report View and AI Batch can scrub them.
    Retain TCIA Research sets listed tags to their catalog operand (@keep or
    @safe()) when they are still @remove, @empty, or @round after other
    selected options (so Patient Age @keep replaces Basic five-year banding).

    Args:
        options: Selected de-identification options (Basic Profile is forced in).
        base_script_path: .script file to load before option changes (usually the
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

    if DeidMethodCode.TCIA_RESEARCH in selected:
        for tag, operation in TCIA_RESEARCH_OPERANDS.items():
            rule = document.get_rule(tag)
            if rule is None:
                continue
            if _tcia_may_rewrite(rule.operation):
                rule.operation = operation

    return document


def project_script_operations(project_dir: Path | None) -> dict[str, str]:
    """
    Load tag→operand map from the project's compiled anonymizer script.

    Used by Clean Descriptors / Metadata Detect so @safe() tags are not
    sent to NER. Looks for ``*-anonymizer.script`` under project_dir.

    Args:
        project_dir: Project storage directory (may be None).

    Returns:
        Uppercase eight-hex tag → normalized operation; empty when missing.
    """
    if project_dir is None:
        return {}
    root = Path(project_dir)
    if not root.is_dir():
        return {}
    scripts = sorted(root.glob("*-anonymizer.script"))
    if not scripts:
        return {}
    try:
        return script_operations_by_tag(load_script_rules(scripts[0]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load project script ops from %s: %s", scripts[0], exc)
        return {}


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
