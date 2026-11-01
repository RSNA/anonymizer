"""compile_script overlays, presets, and the one-date-strategy check."""

from anonymizer.controller.dates import is_date_delta_operation
from anonymizer.controller.script.compile import (
    CLEAN_STRUCTURED_KEEP_TAGS,
    CLINICAL_TRIAL_SPONSOR_NAME_TAG,
    PRODUCT_DEVICE_IDENTITY_EXTRA_TAGS,
    TCIA_RESEARCH_OPERANDS,
    compile_script,
    normalize_script_operation,
)
from anonymizer.controller.script.operands import is_remove_operation
from anonymizer.controller.script.retain_option_tags import patient_age_tag
from anonymizer.controller.script.date_rules import (
    mismatched_date_rules,
    study_date_operation,
)
from anonymizer.controller.script.document import ScriptDocument, ScriptRule
from anonymizer.model.project import ProjectModel
from anonymizer.view.settings.deidentification_options_dialog import BASIC_OPTIONS, RETAIN_OPTIONS
from anonymizer.utils.dicom import DeidMethodCode

_DEFAULT = ProjectModel.default_anonymizer_script_path()


def _ops(document: ScriptDocument) -> dict[str, str]:
    """Rule operations by uppercase tag."""
    return {rule.tag.upper(): rule.operation for rule in document.rules}


def test_basic_compile_matches_default_script() -> None:
    """BASIC_OPTIONS compiles to the packaged default rules."""
    ops = _ops(compile_script(BASIC_OPTIONS, _DEFAULT))
    assert ops["00080020"] == "@hashdate"
    assert ops["00080080"] == "@remove()"
    assert is_date_delta_operation(ops["00080020"])


def test_retain_compile_keeps_default_dates_and_characteristics() -> None:
    """RETAIN_OPTIONS overlays patient characteristics; institution stays removed."""
    ops = _ops(compile_script(RETAIN_OPTIONS, _DEFAULT))
    assert ops["00080020"] == "@hashdate"
    assert ops["00100040"] == "@keep"
    assert ops["00080080"] == "@remove()"


def test_retain_uids_overlay_keeps_uid_rules() -> None:
    """RETAIN_UIDS rewrites every @uid rule to keep."""
    ops = _ops(compile_script(BASIC_OPTIONS | {DeidMethodCode.RETAIN_UIDS}, _DEFAULT))
    assert not any("@uid" in operation for operation in ops.values())
    assert ops["0020000D"] == "@keep"


def test_institution_identity_overlay_keeps_institution_tags() -> None:
    """INSTITUTION_IDENTITY keeps institution tags on the default base."""
    ops = _ops(compile_script(BASIC_OPTIONS | {DeidMethodCode.INSTITUTION_IDENTITY}, _DEFAULT))
    assert ops["00080080"] == "@keep"
    assert ops["00081040"] == "@keep"


def test_device_identity_overlay_keeps_serial_station_and_manufacturer() -> None:
    """DEVICE_IDENTITY safe-keeps tags the default script removes (including Manufacturer)."""
    basic = _ops(compile_script(BASIC_OPTIONS, _DEFAULT))
    ops = _ops(compile_script(BASIC_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY}, _DEFAULT))
    assert basic["00080070"].startswith("@remove")
    assert ops["00080070"] == "@safe()"
    assert ops["00081090"] == "@safe()"
    assert ops["00181000"] == "@safe()"
    assert ops["00081010"] == "@safe()"
    assert ops["00181020"] == "@safe()"


def test_full_dates_overlay_keeps_dates() -> None:
    """FULL_DATES leaves date rules unshifted."""
    ops = _ops(compile_script(BASIC_OPTIONS | {DeidMethodCode.FULL_DATES}, _DEFAULT))
    assert ops["00080020"] == "@keep"
    assert not any(is_date_delta_operation(operation) for operation in ops.values())


def test_clean_structured_keeps_report_document_tags() -> None:
    """Clean Structured Content keeps Encapsulated PDF / SR text tags Basic removes."""
    basic = _ops(compile_script(BASIC_OPTIONS, _DEFAULT))
    ops = _ops(
        compile_script(BASIC_OPTIONS | {DeidMethodCode.CLEAN_STRUCTURED_CONTENT}, _DEFAULT)
    )
    for tag in CLEAN_STRUCTURED_KEEP_TAGS:
        assert basic[tag].startswith("@remove") or basic[tag].startswith("@empty"), tag
        assert ops[tag] == "@keep", tag


def test_tcia_research_applies_operand_map() -> None:
    """TCIA Research sets catalog tags to catalog operands when Basic still removes/empties them."""
    basic = _ops(compile_script(BASIC_OPTIONS, _DEFAULT))
    ops = _ops(compile_script(BASIC_OPTIONS | {DeidMethodCode.TCIA_RESEARCH}, _DEFAULT))
    assert len(TCIA_RESEARCH_OPERANDS) >= 50
    for tag, expected in TCIA_RESEARCH_OPERANDS.items():
        if tag not in basic:
            continue
        base_op = normalize_script_operation(basic[tag])
        if not (
            is_remove_operation(base_op) or base_op.startswith("@empty")
        ):
            # Catalog entry stale relative to Basic (e.g. U now @uid) — compile skips.
            continue
        assert ops[tag] == expected, tag
    assert ops["00540013"] == "@keep"
    assert ops["00540300"] == "@keep"
    # Answer-key whole-value <text_removed> / <date_shifted> tags stay Basic (not TCIA keep).
    assert "00100030" not in TCIA_RESEARCH_OPERANDS
    assert "00200010" not in TCIA_RESEARCH_OPERANDS
    assert "00080090" not in TCIA_RESEARCH_OPERANDS
    assert "00080106" not in TCIA_RESEARCH_OPERANDS
    assert basic["00100030"].startswith("@empty")
    assert ops["00100030"] == basic["00100030"]
    assert basic["00080106"].startswith("@empty")
    assert ops["00080106"] == basic["00080106"]


def test_tcia_research_safe_keeps_device_extras_without_device_identity() -> None:
    """TCIA Research @safe()s manufacturer/model/software; serial/station stay removed."""
    basic = _ops(compile_script(BASIC_OPTIONS, _DEFAULT))
    ops = _ops(compile_script(BASIC_OPTIONS | {DeidMethodCode.TCIA_RESEARCH}, _DEFAULT))
    for tag in PRODUCT_DEVICE_IDENTITY_EXTRA_TAGS:
        assert tag in TCIA_RESEARCH_OPERANDS, tag
        assert TCIA_RESEARCH_OPERANDS[tag] == "@safe()", tag
        assert basic[tag].startswith("@remove"), tag
        assert ops[tag] == "@safe()", tag
    assert basic["00181000"].startswith("@remove")
    assert ops["00181000"] == basic["00181000"]
    assert basic["00081010"].startswith("@remove")
    assert ops["00081010"] == basic["00081010"]


def test_tcia_research_safe_keeps_clinical_trial_sponsor_name() -> None:
    """TCIA Research @safe()s Clinical Trial Sponsor Name (Basic @empty)."""
    basic = _ops(compile_script(BASIC_OPTIONS, _DEFAULT))
    ops = _ops(compile_script(BASIC_OPTIONS | {DeidMethodCode.TCIA_RESEARCH}, _DEFAULT))
    tag = CLINICAL_TRIAL_SPONSOR_NAME_TAG
    assert TCIA_RESEARCH_OPERANDS[tag] == "@safe()"
    assert basic[tag].startswith("@empty")
    assert ops[tag] == "@safe()"


def test_tcia_research_overrides_age_round_to_keep() -> None:
    """TCIA Research replaces Patient Age @round with @keep from the catalog."""
    age = patient_age_tag()
    chars = _ops(
        compile_script(BASIC_OPTIONS | {DeidMethodCode.PATIENT_CHARACTERISTICS}, _DEFAULT)
    )
    both = _ops(
        compile_script(
            BASIC_OPTIONS
            | {DeidMethodCode.PATIENT_CHARACTERISTICS, DeidMethodCode.TCIA_RESEARCH},
            _DEFAULT,
        )
    )
    assert chars[age].startswith("@round")
    assert age in TCIA_RESEARCH_OPERANDS
    assert TCIA_RESEARCH_OPERANDS[age] == "@keep"
    assert both[age] == "@keep"


def test_tcia_research_does_not_override_device_safe() -> None:
    """Device Identity @safe() wins; TCIA does not rewrite those tags further."""
    device = _ops(
        compile_script(BASIC_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY}, _DEFAULT)
    )
    both = _ops(
        compile_script(
            BASIC_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY, DeidMethodCode.TCIA_RESEARCH},
            _DEFAULT,
        )
    )
    for tag in ("00181000", "00081010", "00080070"):
        if tag not in device:
            continue
        assert device[tag].startswith("@safe"), tag
        assert both[tag] == device[tag], tag


def test_mismatched_date_rules_detected() -> None:
    """A date rule that differs from StudyDate is reported."""
    document = ScriptDocument(
        rules=[
            ScriptRule(tag="00080020", name="StudyDate", en="T", operation="@hashdate"),
            ScriptRule(
                tag="00080021",
                name="SeriesDate",
                en="T",
                operation="@incrementdate(this,7)",
            ),
            ScriptRule(tag="00100010", name="PatientName", en="T", operation="@empty()"),
        ]
    )
    assert study_date_operation(document) == "@hashdate"
    assert [rule.tag for rule in mismatched_date_rules(document)] == ["00080021"]


def test_compiled_presets_have_one_date_strategy() -> None:
    """Packaged presets compile with no mismatched date rules."""
    assert mismatched_date_rules(compile_script(BASIC_OPTIONS, _DEFAULT)) == []
    assert mismatched_date_rules(compile_script(RETAIN_OPTIONS, _DEFAULT)) == []
