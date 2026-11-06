"""De-identification option inference, change detection, and modality side-effects.

Public API
----------
confidentiality_options_changed(*, selected, installed) -> bool
    True when selected options differ from those stored on the project.

infer_options_from_script(document) -> frozenset[DeidMethodCode]
    Infer de-identification options from a script's rules (prefill).

apply_option_modality_effects(model, options) -> None
    Ensure SR/PDF modalities when Clean Structured Content / Descriptors are on.

assign_confidentiality_options(model, options) -> frozenset[DeidMethodCode]
    Store options on a project model, always including Basic, and apply modality side-effects.

resolve_deidentification_choices(value) -> frozenset[DeidMethodCode]
    Option names or codes (Basic, Retain, or one option) to a set, always including Basic.

REPORT_MODALITIES_FOR_CLEAN_STRUCTURED
    Modality codes (SR, PDF) that need Clean Structured Content at ingest.

newly_enabled_report_modalities(previous, selected) -> frozenset[str]
    Newly selected SR/PDF codes (not Secondary Capture).

enable_clean_structured_for_report_modalities(options, *, previous_modalities, selected_modalities)
    -> frozenset[DeidMethodCode] | None
    Options with Clean Structured Content added when SR/PDF newly enabled; else None.

clean_structured_auto_enable_message() -> str
    English info text when modalities auto-enable Clean Structured Content.
"""

from collections.abc import Sequence

from anonymizer.controller.dates import is_date_delta_operation
from anonymizer.controller.script.compile import (
    INSTITUTION_IDENTITY_TAGS,
    KEEP_DEVICE_TAGS,
    PATIENT_CHARACTERISTICS_TAGS,
    TCIA_RESEARCH_OPERANDS,
    normalize_script_operation,
)
from anonymizer.controller.script.date_rules import STUDY_DATE_TAG
from anonymizer.controller.script.document import ScriptDocument, load_script_rules
from anonymizer.controller.script.operands import (
    is_remove_operation,
    is_retain_value_operation,
)
from anonymizer.controller.script.option_explanations import (
    BASIC_OPTIONS,
    RETAIN_OPTIONS,
    option_abbreviation,
)
from anonymizer.controller.script.paths import packaged_default_script_path
from anonymizer.controller.script.retain_option_tags import patient_age_tag
from anonymizer.model.project import ProjectModel
from anonymizer.model.settings_validate import (
    SettingsValidationError,
    validate_confidentiality_options,
)
from anonymizer.utils.dicom import DeidMethodCode, deid_method_meaning
from anonymizer.utils.modalities import Modality, get_modality_catalog

# SR / Encapsulated PDF — not SC (pixel Secondary Capture).
REPORT_MODALITIES_FOR_CLEAN_STRUCTURED = frozenset(
    {
        Modality.SR.value,
        Modality.PDF.value,
    }
)


def confidentiality_options_changed(
    *,
    selected: frozenset[DeidMethodCode],
    installed: frozenset[DeidMethodCode],
) -> bool:
    """
    Whether applying options must recompile the project script.

    Args:
        selected: Options chosen in the dialog.
        installed: Options stored on the project.

    Returns:
        True when the two option sets differ.
    """
    return frozenset(selected) != frozenset(installed)


def infer_options_from_script(document: ScriptDocument) -> frozenset[DeidMethodCode]:
    """
    Infer de-identification options from a script's rules (prefill).

    Compares category operations against the packaged default script.

    Args:
        document: Script document to inspect.

    Returns:
        Inferred option codes, always including the Basic Profile.
    """
    base_doc = load_script_rules(packaged_default_script_path())
    base_ops = {
        r.tag.upper(): normalize_script_operation(r.operation) for r in base_doc.rules
    }
    ops = {
        r.tag.upper(): normalize_script_operation(r.operation) for r in document.rules
    }

    options: set[DeidMethodCode] = {DeidMethodCode.BASIC}

    study_op = ops.get(STUDY_DATE_TAG, "@keep")
    base_study = base_ops.get(STUDY_DATE_TAG, "@keep")
    if not any(is_date_delta_operation(op) for op in ops.values()):
        if STUDY_DATE_TAG in ops and study_op == "@keep":
            options.add(DeidMethodCode.FULL_DATES)
    elif (
        "@incrementdate" in study_op
        or "@rebasedate" in study_op.lower()
        or "dateoffset" in study_op
        or ("@hashdate" in study_op and study_op != base_study)
    ):
        options.add(DeidMethodCode.MODIFIED_DATES)

    device_kept = [
        t for t in KEEP_DEVICE_TAGS if t in ops and is_retain_value_operation(ops[t])
    ]
    if device_kept and any(is_remove_operation(base_ops.get(t, "")) for t in device_kept):
        options.add(DeidMethodCode.DEVICE_IDENTITY)

    institution = [t for t in INSTITUTION_IDENTITY_TAGS if t in ops]
    if institution and all(ops[t] == "@keep" for t in institution) and any(
        base_ops.get(t, "@keep") != "@keep" for t in institution
    ):
        options.add(DeidMethodCode.INSTITUTION_IDENTITY)

    age = patient_age_tag()
    char_tags = [t for t in PATIENT_CHARACTERISTICS_TAGS if t != age and t in ops]
    if char_tags and all(ops[t] == "@keep" for t in char_tags) and any(
        is_remove_operation(base_ops.get(t, "")) for t in char_tags
    ):
        options.add(DeidMethodCode.PATIENT_CHARACTERISTICS)

    tcia_hits = [
        tag
        for tag, expected in TCIA_RESEARCH_OPERANDS.items()
        if tag in ops
        and ops[tag] == normalize_script_operation(expected)
        and normalize_script_operation(base_ops.get(tag, "")) != ops[tag]
    ]
    if len(tcia_hits) >= 3:
        options.add(DeidMethodCode.TCIA_RESEARCH)

    if ops and not any("@uid" in op for op in ops.values()):
        options.add(DeidMethodCode.RETAIN_UIDS)
    return frozenset(options)


def apply_option_modality_effects(
    model: ProjectModel,
    options: frozenset[DeidMethodCode],
) -> None:
    """
    Apply in-memory modality side-effects for de-identification options.

    Clean Structured Content and Clean Descriptors enable SR and PDF modalities
    when those codes exist in the modality catalog.

    Args:
        model: Project model to update (modalities / storage classes).
        options: Effective de-identification options.
    """
    if not options & {
        DeidMethodCode.CLEAN_STRUCTURED_CONTENT,
        DeidMethodCode.CLEAN_DESCRIPTORS,
    }:
        return
    catalog = get_modality_catalog()
    modalities = list(model.modalities)
    for modality_code in (Modality.SR, Modality.PDF):
        if modality_code in catalog and modality_code.value not in modalities:
            modalities.append(modality_code.value)
    model.modalities = modalities
    model.ensure_storage_classes_from_modalities()


_NAMED_OPTION_SETS: dict[str, frozenset[DeidMethodCode]] = {
    "basic": BASIC_OPTIONS,
    "basic profile": BASIC_OPTIONS,
    "retain": RETAIN_OPTIONS,
    "retain options": RETAIN_OPTIONS,
}


def assign_confidentiality_options(
    model: ProjectModel,
    options: frozenset[DeidMethodCode],
) -> frozenset[DeidMethodCode]:
    """
    Store de-identification options on a project model.

    Always includes the Basic Application Confidentiality Profile, then applies
    the modality side-effects of the stored set. Does not write the project script.

    Args:
        model: Project model to update.
        options: Selected de-identification options.

    Returns:
        The stored option set.
    """
    stored = frozenset(DeidMethodCode(int(code)) for code in options) | {DeidMethodCode.BASIC}
    model.confidentiality_options = stored
    apply_option_modality_effects(model, stored)
    return stored


def _option_name_index() -> dict[str, DeidMethodCode]:
    """Map plain-language option labels to their codes."""
    index: dict[str, DeidMethodCode] = {}
    for code in DeidMethodCode:
        meaning = deid_method_meaning(code).casefold()
        index[meaning] = code
        if meaning.endswith(" option"):
            index[meaning[: -len(" option")]] = code
        index[option_abbreviation(code).casefold()] = code
    return index


def _codes_for_choice(item: object) -> set[DeidMethodCode]:
    """
    Resolve one de-identification choice to option codes.

    Args:
        item: An option code, a plain name, Basic, or Retain.

    Returns:
        Codes named by that one choice.

    Raises:
        SettingsValidationError: When the choice is not a known option.
    """
    if isinstance(item, bool) or item is None:
        raise SettingsValidationError(
            f"confidentiality_options entries must be option names or codes (got {item!r})"
        )
    if isinstance(item, int) or (isinstance(item, str) and item.strip().lstrip("-").isdigit()):
        try:
            return {DeidMethodCode(int(item))}
        except (TypeError, ValueError) as exc:
            allowed = sorted(int(code) for code in DeidMethodCode)
            raise SettingsValidationError(
                f"confidentiality_options codes must be in {allowed} (got {item!r})"
            ) from exc
    text = str(item).strip()
    folded = " ".join(text.casefold().split())
    named = _NAMED_OPTION_SETS.get(folded)
    if named is not None:
        return set(named)
    code = _option_name_index().get(folded)
    if code is None:
        raise SettingsValidationError(
            f"Unknown de-identification option {item!r}. "
            "Use Basic, Retain, an option name such as Retain TCIA Research Attributes, "
            "or a known option code."
        )
    return {code}


def resolve_deidentification_choices(value: object) -> frozenset[DeidMethodCode]:
    """
    Normalize a de-identification choice to option codes.

    Args:
        value: List of option codes, plain names, Basic, or Retain.
            None is treated as Basic only.

    Returns:
        Option codes, always including Basic.

    Raises:
        SettingsValidationError: When an entry is not a known option.
    """
    if value is None:
        return frozenset({DeidMethodCode.BASIC})
    try:
        items = list(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise SettingsValidationError(
            f"confidentiality_options must be a list of option names or codes (got {value!r})"
        ) from exc
    codes: set[DeidMethodCode] = set()
    for item in items:
        codes.update(_codes_for_choice(item))
    codes.add(DeidMethodCode.BASIC)
    validated = validate_confidentiality_options(sorted(int(code) for code in codes))
    return frozenset(DeidMethodCode(code) for code in validated)


def newly_enabled_report_modalities(
    previous: Sequence[str],
    selected: Sequence[str],
) -> frozenset[str]:
    """
    SR/PDF codes present in selected but not in previous.

    Args:
        previous: Modalities before the edit.
        selected: Modalities after the edit.

    Returns:
        Newly enabled report modality codes (uppercase).
    """
    prev = {str(code).strip().upper() for code in previous if str(code).strip()}
    sel = {str(code).strip().upper() for code in selected if str(code).strip()}
    return frozenset(code for code in (sel - prev) if code in REPORT_MODALITIES_FOR_CLEAN_STRUCTURED)


def enable_clean_structured_for_report_modalities(
    options: frozenset[DeidMethodCode],
    *,
    previous_modalities: Sequence[str],
    selected_modalities: Sequence[str],
) -> frozenset[DeidMethodCode] | None:
    """
    Add Clean Structured Content when SR or PDF is newly selected.

    Args:
        options: Current de-identification options.
        previous_modalities: Modalities before the edit.
        selected_modalities: Modalities after the edit.

    Returns:
        Updated options including Clean Structured Content, or None when no change.
    """
    if not newly_enabled_report_modalities(previous_modalities, selected_modalities):
        return None
    if DeidMethodCode.CLEAN_STRUCTURED_CONTENT in options:
        return None
    return frozenset(options) | {
        DeidMethodCode.BASIC,
        DeidMethodCode.CLEAN_STRUCTURED_CONTENT,
    }


def clean_structured_auto_enable_message() -> str:
    """
    English info text when modalities auto-enable Clean Structured Content.

    Returns:
        Message for the settings dialog (caller wraps with gettext _).
    """
    return (
        "Structured Report (SR) and Encapsulated PDF need Clean Structured "
        "Content so report text is kept at import for review and scrubbing.\n\n"
        "Clean Structured Content has been enabled."
    )
