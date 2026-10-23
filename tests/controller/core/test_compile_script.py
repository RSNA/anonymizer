"""compile_script overlays, presets, and the one-date-strategy check."""

from __future__ import annotations

from anonymizer.controller.dates import is_date_delta_operation
from anonymizer.controller.script.compile import compile_script
from anonymizer.controller.script.date_rules import (
    mismatched_date_rules,
    study_date_operation,
)
from anonymizer.controller.script.document import ScriptDocument, ScriptRule
from anonymizer.model.project import BASIC_OPTIONS, RETAIN_OPTIONS, ProjectModel
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
    """RETAIN_OPTIONS is default + overlays (hashdate StudyDate, keep sex)."""
    ops = _ops(compile_script(RETAIN_OPTIONS, _DEFAULT))
    assert ops["00080020"] == "@hashdate"
    assert ops["00100040"] != "@remove()"
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


def test_device_identity_overlay_keeps_serial_and_station() -> None:
    """DEVICE_IDENTITY keeps tags the default script removes."""
    ops = _ops(compile_script(BASIC_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY}, _DEFAULT))
    assert ops["00181000"] == "@keep"
    assert ops["00081010"] == "@keep"


def test_full_dates_overlay_keeps_dates() -> None:
    """FULL_DATES leaves date rules unshifted."""
    ops = _ops(compile_script(BASIC_OPTIONS | {DeidMethodCode.FULL_DATES}, _DEFAULT))
    assert ops["00080020"] == "@keep"
    assert not any(is_date_delta_operation(operation) for operation in ops.values())


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
