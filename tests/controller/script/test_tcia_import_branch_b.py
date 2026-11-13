"""Branch B TCIA stamps: lookup keys, year/truncate/hashname, IncDate scripts green."""

from pathlib import Path

import pytest

from anonymizer.controller.ctp_lookup import LookupPropertiesError, preview_ctp_lookup
from anonymizer.controller.script.ctp_normalize import normalize_ctp_document
from anonymizer.controller.script.document import (
    ScriptDocument,
    ScriptRule,
    load_script_rules,
    validate_document,
)
from anonymizer.controller.script.operands import (
    hashname_text,
    study_year_text,
    truncate_text,
    validate_operation,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tcia"
_INCDATE_HOLDOUTS = _FIXTURES / "incdate_holdouts.script"
_LOOKUP_EXCERPT = _FIXTURES / "lookup_excerpt.properties"
_ANDDIAG_MINI = _FIXTURES / "anddiag_mini.script"
_TRUNCATE = _FIXTURES / "truncate_study_year.script"


def _rule(tag: str, operation: str) -> ScriptRule:
    return ScriptRule(tag=tag, name=tag, en="T", operation=operation)


def test_parse_tcia_lookup_cname_ddate(tmp_path: Path) -> None:
    """cname/sname/ddate parse into lookup rows; ddate becomes YYYYMMDD basedate."""
    preview = preview_ctp_lookup(_LOOKUP_EXCERPT)
    by_id = {row.patient_id: row for row in preview.rows}
    assert by_id["MRN-1"].collection_name == "IncDate-Test"
    assert by_id["MRN-1"].site_name == "KES"
    assert by_id["MRN-1"].base_date == "20150115"
    assert by_id["MRN-2"].base_date == "20150116"


def test_parse_rejects_bad_ddate(tmp_path: Path) -> None:
    """Invalid ddate fails the properties file."""
    path = tmp_path / "bad.properties"
    path.write_text("ptid/MRN1=A\nddate/MRN1=not-a-date\n", encoding="utf-8")
    with pytest.raises(LookupPropertiesError, match="ddate"):
        preview_ctp_lookup(path)


def test_stamp_helpers() -> None:
    """Year, truncate, and hashname helpers are stable."""
    assert study_year_text("20240315") == "2024"
    assert truncate_text("2024EXTRA", 4) == "2024"
    assert len(hashname_text("Doe^John", 4)) == 4
    assert hashname_text("Doe^John", 4) == hashname_text("Doe^John", 4)


def test_validate_new_stamp_operands() -> None:
    """Branch B catalog forms validate."""
    assert validate_operation("@lookup(this,cname)") is None
    assert validate_operation("@lookup(this,siteid)") is None
    assert validate_operation("@lookup(this,ddate)") is None
    assert validate_operation("@modifydate(StudyDate,*,1,1)") is None
    assert validate_operation("@truncate(this,4)") is None
    assert validate_operation("REV-@hashname(this,4)") is None
    assert validate_operation("@dateinterval(StudyDate,ddate,PatientID)") is None


def test_normalize_always_lookup_and_modifydate() -> None:
    """@always()@lookup / @modifydate rewrite to product stamp forms."""
    document = ScriptDocument(
        rules=[
            _rule("00131010", "@always()@lookup(PatientID,cname)"),
            _rule("00131050", "@always()@modifydate(StudyDate,*,1,1)"),
            _rule("00120052", "@always()@dateinterval(StudyDate,ddate,PatientID)"),
        ]
    )
    normalize_ctp_document(document)
    assert document.get_rule("00131010").operation == "@lookup(this,cname)"
    assert document.get_rule("00131050").operation == "@modifydate(StudyDate,*,1,1)"
    assert document.get_rule("00120052").operation == "@dateinterval(StudyDate,ddate,PatientID)"
    assert validate_document(document) == []


def test_incdate_holdouts_validate_after_branch_b() -> None:
    """Merge gate: IncDate holdout fixture validates after Branch B normalize."""
    document = load_script_rules(_INCDATE_HOLDOUTS)
    normalize_ctp_document(document)
    assert validate_document(document) == []


def test_anddiag_mini_and_truncate_validate() -> None:
    """Merge gate: AndDiag mini (with LTET) and TruncateStudyYear validate."""
    anddiag = load_script_rules(_ANDDIAG_MINI)
    anddiag.params.setdefault("LTET", "DIAGNOSIS")
    normalize_ctp_document(anddiag)
    assert validate_document(anddiag) == []

    truncate = load_script_rules(_TRUNCATE)
    normalize_ctp_document(truncate)
    assert validate_document(truncate) == []
