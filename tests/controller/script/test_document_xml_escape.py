"""Tests for XML escaping in script document serialization."""

from pathlib import Path

from anonymizer.controller.script.document import (
    ScriptDocument,
    ScriptRRule,
    ScriptRule,
    load_script_rules,
    write_script_rules,
)
from anonymizer.controller.script.operands import OperandId, format_operand


def test_write_script_rules_escapes_xml_characters_in_operations_and_r_rules(tmp_path: Path) -> None:
    """Fixed-value operands and <r> text containing &, <, > round-trip through XML."""
    always_amp = format_operand(OperandId.ALWAYS, always_text="CT & MR")
    always_lt = format_operand(OperandId.ALWAYS, always_text="<18")
    doc = ScriptDocument(
        rules=[
            ScriptRule(tag="00081030", name="StudyDescription", en="T", operation=always_amp),
            ScriptRule(tag="0008103E", name="SeriesDescription", en="T", operation=always_lt),
            ScriptRule(tag="00120062", name="PatientIdentityRemoved", en="T", operation="R&D"),
        ],
        r_rules=[
            ScriptRRule(tag="privategroups", en="T", text="Remove private groups & curves <all>"),
        ],
    )
    dest = tmp_path / "escaped.script"
    write_script_rules(dest, doc)

    reloaded = load_script_rules(dest)
    assert reloaded.get_rule("00081030").operation == "@always()CT & MR"
    assert reloaded.get_rule("0008103E").operation == "@always()<18"
    assert reloaded.get_rule("00120062").operation == "R&D"
    assert reloaded.r_rules[0].text == "Remove private groups & curves <all>"
