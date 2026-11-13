"""Branch A TCIA import safety: exact remove, literal @ reject, IncDate holdouts."""

from pathlib import Path

from anonymizer.controller.script.ctp_normalize import (
    normalize_ctp_document,
    unresolved_param_names,
)
from anonymizer.controller.script.document import (
    ScriptDocument,
    ScriptRule,
    load_script_rules,
    validate_document,
)
from anonymizer.controller.script.operands import (
    always_literal_text,
    is_remove_operation,
    validate_operation,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tcia"
_INCDATE_HOLDOUTS = _FIXTURES / "incdate_holdouts.script"

# After Branch A normalize, only these operand families may still fail validate.
_BRANCH_A_HOLDOUT_MARKERS = (
    "cname",
    "modifydate",
    "hashname",
)


def _rule(tag: str, operation: str) -> ScriptRule:
    return ScriptRule(tag=tag, name=tag, en="T", operation=operation)


def test_is_remove_operation_exact_only() -> None:
    """@remove / @remove() only — nested @remove inside @if is not Remove."""
    assert is_remove_operation("@remove()")
    assert is_remove_operation("@remove")
    assert is_remove_operation("@Remove()")
    assert not is_remove_operation(
        "@if(this,isblank){@remove()}{@dateinterval(this,ddate,PatientID,@NORMDATE)}"
    )
    assert not is_remove_operation("@always()@remove()")
    assert not is_remove_operation("@keep")


def test_validate_rejects_literal_containing_at() -> None:
    """Bare literals that embed @ operands are rejected."""
    bad = "REV-@hashname(this,4)"
    assert always_literal_text(bad) is None
    err = validate_operation(bad)
    assert err is not None
    assert "hashname" in err or "@" in err


def test_normalize_lookup_patientid_ptid() -> None:
    """@lookup(PatientID,ptid) becomes @lookup(this,ptid)."""
    document = ScriptDocument(rules=[_rule("00100010", "@lookup(PatientID,ptid)")])
    normalize_ctp_document(document)
    assert document.get_rule("00100010").operation == "@lookup(this,ptid)"
    assert validate_document(document) == []


def test_normalize_always_param_and_append() -> None:
    """@always()@param and @always()@append rewrite to @always()text."""
    document = ScriptDocument(
        rules=[
            _rule("00131012", "@always()@param(@SITENAME)"),
            _rule(
                "00120063",
                "@always()@append(){Per DICOM PS 3.15 AnnexE. Details in 0012,0064}",
            ),
        ],
        params={"SITENAME": "SITETCIA"},
    )
    warnings = normalize_ctp_document(document)
    assert document.get_rule("00131012").operation == "@always()SITETCIA"
    assert document.get_rule("00120063").operation.startswith("@always()Per DICOM")
    assert validate_document(document) == []
    assert warnings == [] or isinstance(warnings, list)


def test_unresolved_param_names_when_p_missing() -> None:
    """Missing <p> leaves @always()@param for Import to prompt."""
    document = ScriptDocument(
        rules=[_rule("00120053", "@always()@param(@LTET)")],
        params={},
    )
    normalize_ctp_document(document)
    assert unresolved_param_names(document) == ["LTET"]
    assert document.get_rule("00120053").operation == "@always()@param(@LTET)"


def test_dedupe_rules_last_wins() -> None:
    """Duplicate tags keep the last rule and warn."""
    document = ScriptDocument(
        rules=[
            _rule("0008114A", "@keep"),
            _rule("0008114A", "@empty()"),
        ]
    )
    warnings = normalize_ctp_document(document)
    assert len(document.rules) == 1
    assert document.get_rule("0008114A").operation == "@empty()"
    assert any("Duplicate" in w for w in warnings)


def test_incdate_holdouts_after_branch_a_normalize() -> None:
    """
    IncDate excerpt after Branch A: only cname / modifydate / hashname fail.

    Merge gate for tcia-script-import-safety.
    """
    document = load_script_rules(_INCDATE_HOLDOUTS)
    normalize_ctp_document(document)

    assert document.get_rule("00080016").operation == "@keep"
    assert document.get_rule("00080018").operation == "@uid"
    assert document.get_rule("00080020").operation == "@incrementdate(this,-1000)"
    assert document.get_rule("00100010").operation == "@lookup(this,ptid)"
    assert document.get_rule("00131012").operation == "@always()SITETCIA"
    assert document.get_rule("00131013").operation == "@always()99999999"
    assert document.get_rule("00120063").operation.startswith("@always()Per DICOM")
    assert document.get_rule("0008114A").operation == "@empty()"

    errors = validate_document(document)
    assert errors, "expected remaining Branch B holdouts"
    joined = "\n".join(errors).lower()
    for marker in _BRANCH_A_HOLDOUT_MARKERS:
        assert marker in joined, f"expected holdout marker {marker!r} in {errors}"

    for err in errors:
        lower = err.lower()
        assert any(marker in lower for marker in _BRANCH_A_HOLDOUT_MARKERS), err
        assert "lookup(patientid,ptid)" not in lower
        assert "@param" not in lower
        assert "@append" not in lower
        assert "duplicate tag" not in lower


def test_packaged_default_still_validates() -> None:
    """Exact-remove change must not break the packaged default script."""
    from anonymizer.model.project import ProjectModel

    document = load_script_rules(ProjectModel.default_anonymizer_script_path())
    assert validate_document(document) == []
