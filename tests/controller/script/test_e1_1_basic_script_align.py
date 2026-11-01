"""Packaged default script aligns to Table E.1-1 Basic Profile."""

from pathlib import Path

from anonymizer.controller.script.compile import normalize_script_operation
from anonymizer.controller.script.document import load_script_rules
from anonymizer.model.project import ProjectModel
from prototyping.script.align_default_script_e1_1 import (
    load_basic_profile,
    target_operand,
)


def test_default_script_covers_every_e1_1_basic_tag() -> None:
    """Every E.1-1 Basic attribute exists in the packaged default script."""
    profile = load_basic_profile()
    document = load_script_rules(ProjectModel.default_anonymizer_script_path())
    ops = {rule.tag.upper(): rule.operation for rule in document.rules}
    missing = sorted(tag for tag in profile if tag not in ops)
    assert missing == [], f"missing E.1-1 tags: {missing[:20]}"


def test_default_script_operands_match_e1_1_mapping() -> None:
    """Each E.1-1 tag uses the aligned operand (mapping A + remaps + deferrals)."""
    profile = load_basic_profile()
    document = load_script_rules(ProjectModel.default_anonymizer_script_path())
    ops = {
        rule.tag.upper(): normalize_script_operation(rule.operation)
        for rule in document.rules
    }
    mismatches: list[str] = []
    for tag, info in profile.items():
        current = ops[tag]
        expected = normalize_script_operation(
            target_operand(tag=tag, basic=info["basic"], current=current)
        )
        if current != expected:
            mismatches.append(f"{tag} basic={info['basic']} got={current} want={expected}")
    assert mismatches == [], "\n".join(mismatches[:30])


def test_birth_date_and_referring_physician_are_empty_under_basic() -> None:
    """Pure Z identity tags blank rather than remove."""
    document = load_script_rules(ProjectModel.default_anonymizer_script_path())
    ops = {
        rule.tag.upper(): normalize_script_operation(rule.operation)
        for rule in document.rules
    }
    assert ops["00100030"] == "@empty()"
    assert ops["00080090"] == "@empty()"


def test_descriptor_deferrals_stay_keep() -> None:
    """Clean Descriptors free-text tags remain @keep under Basic."""
    document = load_script_rules(ProjectModel.default_anonymizer_script_path())
    ops = {
        rule.tag.upper(): normalize_script_operation(rule.operation)
        for rule in document.rules
    }
    assert ops["00081030"] == "@keep"
    assert ops["0008103E"] == "@keep"
    assert ops["00189937"] == "@keep"


def test_aligner_is_idempotent(tmp_path: Path) -> None:
    """Running the aligner twice does not change operands."""
    from prototyping.script.align_default_script_e1_1 import align_default_script

    src = ProjectModel.default_anonymizer_script_path()
    copy = tmp_path / "default-anonymizer.script"
    copy.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    first = align_default_script(script_path=copy)
    text_after_first = copy.read_text(encoding="utf-8")
    second = align_default_script(script_path=copy)
    assert copy.read_text(encoding="utf-8") == text_after_first
    assert second["changed"] == 0
    assert second["added"] == 0
    assert first["added"] == 0
