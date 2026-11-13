"""Custom CTP script validation and option inference (no project install API)."""

from pathlib import Path

import pytest

from anonymizer.controller.script.compile import compile_script
from anonymizer.controller.script.ctp_normalize import (
    format_validation_errors,
    normalize_ctp_document,
    unresolved_dateinc_tags,
)
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
from anonymizer.controller.script.options import infer_options_from_script
from anonymizer.model.project import ProjectModel
from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.view.settings.deidentification_options_dialog import BASIC_OPTIONS, RETAIN_OPTIONS

_DEFAULT = ProjectModel.default_anonymizer_script_path()


def _rule(tag: str, operation: str) -> ScriptRule:
    """Minimal script rule."""
    return ScriptRule(tag=tag, name=tag, en="T", operation=operation)


def _write_ctp_like_script(path: Path) -> Path:
    """Minimal CTP-like .script with aliases and <p> params."""
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<script>\n'
        ' <p t="DATEINC">-30</p>\n'
        ' <p t="UIDROOT">1.2.840.999</p>\n'
        ' <p t="SITEID">TST</p>\n'
        ' <e en="T" t="00080016" n="SOPClassUID">@keep()</e>\n'
        ' <e en="T" t="00080018" n="SOPInstanceUID">'
        "@hashuid(@UIDROOT,this)</e>\n"
        ' <e en="T" t="00080020" n="StudyDate">'
        "@incrementdate(this,@DATEINC)</e>\n"
        ' <e en="T" t="00100020" n="PatientID">'
        "@hashptid(@SITEID,this)</e>\n"
        ' <e en="T" t="00100030" n="PatientBirthDate">'
        "@hashdate(this,PatientID)</e>\n"
        ' <e en="T" t="00101010" n="PatientAge">@round(PatientAge,10)</e>\n'
        "</script>\n",
        encoding="utf-8",
    )
    return path


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


def test_load_script_params_from_p_elements(tmp_path: Path) -> None:
    """<p> DATEINC/UIDROOT/SITEID are retained on load."""
    path = _write_ctp_like_script(tmp_path / "ctp.script")
    doc = load_script_rules(path)
    assert doc.params["DATEINC"] == "-30"
    assert doc.params["UIDROOT"] == "1.2.840.999"
    assert doc.params["SITEID"] == "TST"


def test_normalize_ctp_aliases_and_validate(tmp_path: Path) -> None:
    """CTP aliases rewrite to product forms and then validate."""
    doc = load_script_rules(_write_ctp_like_script(tmp_path / "ctp.script"))
    assert doc.get_rule("00080016").operation == "@keep()"
    warnings = normalize_ctp_document(doc)
    assert doc.get_rule("00080016").operation == "@keep"
    assert doc.get_rule("00080018").operation == "@uid"
    assert doc.get_rule("00080020").operation == "@incrementdate(this,-30)"
    assert doc.get_rule("00100020").operation == "@ptid"
    assert doc.get_rule("00100030").operation == "@hashdate"
    assert doc.get_rule("00101010").operation == "@round(this,10)"
    assert unresolved_dateinc_tags(doc) == []
    assert any("hashuid" in w for w in warnings)
    assert any("hashptid" in w for w in warnings)
    assert validate_document(doc) == []


def test_normalize_dateinc_override_without_param() -> None:
    """DATEINC can be supplied explicitly when <p> is missing."""
    document = ScriptDocument(
        rules=[_rule("00080020", "@incrementdate(this,@DATEINC)")],
        params={},
    )
    assert unresolved_dateinc_tags(document) == ["00080020"]
    normalize_ctp_document(document, dateinc=-7)
    assert document.get_rule("00080020").operation == "@incrementdate(this,-7)"
    assert validate_document(document) == []


def test_hashdate_non_patient_id_seed_stays_unsupported() -> None:
    """@hashdate(this,StudyInstanceUID) is not rewritten."""
    document = ScriptDocument(
        rules=[_rule("00080020", "@hashdate(this,StudyInstanceUID)")],
    )
    normalize_ctp_document(document)
    assert document.get_rule("00080020").operation == "@hashdate(this,StudyInstanceUID)"
    errors = validate_document(document)
    assert errors
    assert "Unsupported operand" in errors[0]


def test_format_validation_errors_groups_by_operand() -> None:
    """Import/reload dialogs group identical unsupported operands."""
    errors = [
        "00080016: Unsupported operand: '@notARealOperand'",
        "00100010: Unsupported operand: '@notARealOperand'",
        "00100020: Unsupported operand: '@otherBad'",
        "Duplicate tag: 00100020",
    ]
    text = format_validation_errors(errors)
    assert "Unsupported operand '@notARealOperand' on 00080016, 00100010" in text
    assert "Unsupported operand '@otherBad' on 00100020" in text
    assert "Duplicate tag: 00100020" in text


def test_reload_script_rejects_invalid_on_disk_operand(controller, tmp_path: Path) -> None:
    """reload_script uses validate_document and refuses the keep table."""
    path = tmp_path / "bad-on-disk.script"
    path.write_text(
        '<?xml version="1.0"?>\n<script>\n'
        ' <e en="T" t="00100010" n="PatientName">@notARealOperand</e>\n'
        ' <e en="T" t="00100020" n="PatientID">@ptid</e>\n'
        "</script>\n",
        encoding="utf-8",
    )
    before = dict(controller.anonymizer.model._tag_keep)
    with pytest.raises(ValueError, match="Unsupported script"):
        controller.anonymizer.reload_script(path)
    assert controller.anonymizer.model._tag_keep == before


def test_write_roundtrip_preserves_params(tmp_path: Path) -> None:
    """Written scripts keep <p> parameters for round-trip."""
    src = _write_ctp_like_script(tmp_path / "in.script")
    doc = load_script_rules(src)
    normalize_ctp_document(doc)
    out = tmp_path / "out.script"
    write_script_rules(out, doc)
    again = load_script_rules(out)
    assert again.params["DATEINC"] == "-30"
    assert again.get_rule("00080016").operation == "@keep"
