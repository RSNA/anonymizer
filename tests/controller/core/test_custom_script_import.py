"""Custom CTP script validation and option inference (no project install API)."""

from pathlib import Path

import pytest

from anonymizer.controller.script.compile import compile_script
from anonymizer.controller.script.date_rules import (
    apply_study_date_operation_to_rules,
    mismatched_date_rules,
)
from anonymizer.controller.script.document import (
    ScriptDocument,
    ScriptRule,
    load_script_rules,
    validate_document,
    write_script_rules,
)
from anonymizer.model.project import BASIC_OPTIONS, RETAIN_OPTIONS, ProjectModel
from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.controller.script.options import infer_options_from_script

_DEFAULT = ProjectModel.default_anonymizer_script_path()


def _rule(tag: str, operation: str) -> ScriptRule:
    """Minimal script rule."""
    return ScriptRule(tag=tag, name=tag, en="T", operation=operation)


def test_infer_options_from_packaged_presets() -> None:
    """Compiled Basic preset infers as Basic; Retain keeps default hashdate StudyDate."""
    retain = infer_options_from_script(compile_script(RETAIN_OPTIONS, _DEFAULT))
    assert DeidMethodCode.BASIC in retain

    basic = infer_options_from_script(compile_script(BASIC_OPTIONS, _DEFAULT))
    assert basic == BASIC_OPTIONS


def test_apply_study_date_operation_fixes_mismatch() -> None:
    """The one-click fix rewrites every date rule to the StudyDate operation."""
    document = ScriptDocument(
        rules=[
            _rule("00080020", "@incrementdate(this,-30)"),
            _rule("00080021", "@hashdate"),
            _rule("00100010", "@empty()"),
        ]
    )
    assert [r.tag for r in mismatched_date_rules(document)] == ["00080021"]
    updated = apply_study_date_operation_to_rules(document)
    assert updated == ["00080021"]
    assert mismatched_date_rules(document) == []
    assert document.get_rule("00080021").operation == "@incrementdate(this,-30)"


def test_validate_document_rejects_unknown_operand(tmp_path: Path) -> None:
    """Unknown @ operands fail validation before write."""
    document = ScriptDocument(rules=[_rule("00100010", "@notARealOperand")])
    errors = validate_document(document)
    assert errors
    assert "00100010" in errors[0]
    out = tmp_path / "bad.script"
    with pytest.raises(ValueError):
        write_script_rules(out, document)


def test_load_blank_keep_as_at_keep(tmp_path: Path) -> None:
    """Blank element text loads as @keep."""
    path = tmp_path / "blank.script"
    path.write_text(
        '<?xml version="1.0"?>\n<script>\n'
        ' <e en="T" t="00080016" n="SOPClassUID"></e>\n'
        "</script>\n",
        encoding="utf-8",
    )
    doc = load_script_rules(path)
    assert doc.get_rule("00080016").operation == "@keep"
