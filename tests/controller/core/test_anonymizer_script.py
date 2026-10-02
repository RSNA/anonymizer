"""Tests for anonymizer script editor controller helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.anonymizer_script import (
    PAGE_SIZE,
    ScriptRule,
    ScriptViewMode,
    add_rule_from_dictionary,
    always_literal_text,
    commit_script_edit,
    demote_rule,
    display_operation,
    filter_rules,
    format_operand,
    has_missing_dictionary_tags,
    is_remove_operation,
    load_script_rules,
    normalize_operation,
    operand_id_for_operation,
    operand_id_from_syntax,
    page_slice,
    promote_rule,
    search_dicom_dictionary,
    search_missing_dictionary_tags,
    search_removed_rules,
    stage_script_edit,
    validate_document,
    validate_operation,
    write_script_rules,
)
from anonymizer.controller.process_ctp_lookup import private_anonymizer_script_path


def _mini_script(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                "<script>",
                ' <e en="T" t="00080016" n="SOPClassUID"></e>',
                ' <e en="T" t="00080018" n="SOPInstanceUID">@uid</e>',
                ' <e en="T" t="00080001" n="LengthToEndRetired">@remove()</e>',
                ' <e en="T" t="00100020" n="PatientID">@ptid</e>',
                ' <e en="T" t="00101010" n="PatientAge">@round(this,5)</e>',
                ' <r en="T" t="privategroups">Remove private groups</r>',
                "</script>",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_load_write_round_trip_preserves_remove_and_r(tmp_path: Path) -> None:
    src = _mini_script(tmp_path / "in.script")
    doc = load_script_rules(src)
    assert len(doc.rules) == 5
    assert any(is_remove_operation(r.operation) for r in doc.rules)
    assert len(doc.r_rules) == 1
    assert doc.r_rules[0].tag == "privategroups"

    out = tmp_path / "out.script"
    write_script_rules(out, doc)
    again = load_script_rules(out)
    assert [(r.tag, r.name, r.operation) for r in again.rules] == [
        (r.tag, r.name, r.operation) for r in doc.rules
    ]
    assert again.r_rules[0].tag == "privategroups"


def test_active_filter_excludes_remove(tmp_path: Path) -> None:
    doc = load_script_rules(_mini_script(tmp_path / "a.script"))
    active = filter_rules(doc, view=ScriptViewMode.ACTIVE)
    removed = filter_rules(doc, view=ScriptViewMode.REMOVED)
    assert all(not is_remove_operation(r.operation) for r in active)
    assert all(is_remove_operation(r.operation) for r in removed)
    assert len(active) + len(removed) == len(doc.rules)


def test_promote_and_demote(tmp_path: Path) -> None:
    doc = load_script_rules(_mini_script(tmp_path / "b.script"))
    promote_rule(doc, "00080001", "")
    assert not is_remove_operation(doc.get_rule("00080001").operation)
    demote_rule(doc, "00080001")
    assert is_remove_operation(doc.get_rule("00080001").operation)


def test_promote_rejects_already_active(tmp_path: Path) -> None:
    doc = load_script_rules(_mini_script(tmp_path / "c.script"))
    with pytest.raises(ValueError, match="already Active"):
        promote_rule(doc, "00080018", "@uid")


def test_validate_and_format_operands() -> None:
    assert validate_operation("") is None
    assert validate_operation("@keep") is None
    assert normalize_operation("@keep") == ""
    assert validate_operation("@remove()") is None
    assert validate_operation("@lookup(this,ptid)") is None
    assert validate_operation("@round(this,5)") is None
    assert validate_operation("YES") is None  # CTP bare fixed literal
    assert validate_operation("@always()YES") is None
    assert validate_operation("@always()") is not None
    assert validate_operation("@always()@date()") is not None
    assert validate_operation("@incrementdate(this,42)") is None
    assert validate_operation("@incrementdate(this,-10)") is None
    assert validate_operation("@rebasedate(this,19600101)") is None
    assert validate_operation("@rebasedate") is None  # bare form defaults origin at runtime
    assert validate_operation("@rebasedate(this,1960)") is not None
    assert validate_operation("@bogus") is not None
    assert format_operand("uid") == "@uid"
    assert format_operand("round", round_width=5) == "@round(this,5)"
    assert format_operand("always", always_text="YES") == "@always()YES"
    assert format_operand("incrementdate", increment_days=42) == "@incrementdate(this,42)"
    assert format_operand("incrementdate", increment_days=-7) == "@incrementdate(this,-7)"
    assert format_operand("rebasedate", rebase_origin="19600101") == "@rebasedate(this,19600101)"
    with pytest.raises(ValueError, match="empty"):
        format_operand("always", always_text="")
    with pytest.raises(ValueError, match="YYYYMMDD"):
        format_operand("rebasedate", rebase_origin="1960")
    assert operand_id_for_operation("@round(this,5)") == "round"
    assert operand_id_for_operation("") == "keep"
    assert operand_id_for_operation("YES") == "always"
    assert operand_id_for_operation("@always()YES") == "always"
    assert operand_id_for_operation("@always()") is None
    assert operand_id_for_operation("@incrementdate(this,42)") == "incrementdate"
    assert operand_id_for_operation("@rebasedate(this,19600101)") == "rebasedate"
    assert operand_id_for_operation("@rebasedate") == "rebasedate"
    assert always_literal_text("YES") == "YES"
    assert always_literal_text("@always()REMOVED") == "REMOVED"
    assert always_literal_text("@always()") is None
    assert always_literal_text("@uid") is None
    assert display_operation("") == "@keep"
    assert display_operation("@keep") == "@keep"
    assert display_operation("@uid") == "@uid"
    assert display_operation("YES") == "YES"
    assert display_operation("@always()YES") == "@always()YES"
    assert operand_id_from_syntax("@keep") == "keep"
    assert operand_id_from_syntax("@round(this,n)") == "round"
    assert operand_id_from_syntax("@always()") == "always"
    assert operand_id_from_syntax("@incrementdate(this,n)") == "incrementdate"
    assert operand_id_from_syntax("@rebasedate(this,origin)") == "rebasedate"
    from anonymizer.controller.anonymizer_script import (
        incrementdate_days,
        is_date_shift_operation,
        rebasedate_origin,
    )

    assert incrementdate_days("@incrementdate(this,42)") == 42
    assert rebasedate_origin("@rebasedate(this,19600101)") == "19600101"
    assert rebasedate_origin("@rebasedate") == "19600101"
    assert is_date_shift_operation("@hashdate")
    assert is_date_shift_operation("@incrementdate(this,1)")
    assert is_date_shift_operation("@rebasedate(this,19600101)")
    assert is_date_shift_operation("@lookup(this,dateoffset)")
    assert not is_date_shift_operation("@keep")


def test_tag_dictionary_meta_and_dicom_version() -> None:
    from anonymizer.controller.anonymizer_script import (
        dicom_applicable_standard_text,
        dicom_standard_version,
        format_tag_description_line,
        tag_dictionary_meta,
    )

    meta = tag_dictionary_meta("00100010")
    assert meta is not None
    assert meta.description == "Patient's Name"
    assert meta.vr == "PN"
    assert meta.retired is False
    assert format_tag_description_line(meta) == "Patient's Name"
    assert format_tag_description_line(meta, retired_label="Retired") == "Patient's Name"

    study = tag_dictionary_meta("0008,0020")
    assert study is not None
    assert study.description == "Study Date"
    assert study.vr == "DA"

    retired = tag_dictionary_meta("00080001")
    assert retired is not None
    assert retired.retired is True
    assert "Retired" in format_tag_description_line(retired, retired_label="Retired")
    assert "Length to End" in format_tag_description_line(retired)

    assert tag_dictionary_meta("not-a-tag") is None
    version = dicom_standard_version()
    assert version  # e.g. 2024c
    assert any(c.isdigit() for c in version)
    label = dicom_applicable_standard_text()
    assert label.startswith("DICOM 3.0 (")
    assert version in label
    assert label.endswith(")")


def test_operand_tag_incompatibility_gates() -> None:
    from anonymizer.controller.anonymizer_script import (
        format_dicom_tag,
        operand_tag_incompatibility,
        operands_for_tag,
    )

    assert format_dicom_tag("00080020") == "0008,0020"
    assert format_dicom_tag("0008,0020") == "0008,0020"

    assert operand_tag_incompatibility("ptid", tag="00080020", name="StudyDate") is not None
    assert operand_tag_incompatibility("hashdate", tag="00080018", name="SOPInstanceUID") is not None
    assert operand_tag_incompatibility("uid", tag="00080020", name="StudyDate") is not None
    assert operand_tag_incompatibility("round", tag="00080020", name="StudyDate") is not None
    assert operand_tag_incompatibility("hashdate", tag="00080020", name="StudyDate") is None
    assert operand_tag_incompatibility("uid", tag="00080018", name="SOPInstanceUID") is None
    assert operand_tag_incompatibility("ptid", tag="00100020", name="PatientID") is None
    assert operand_tag_incompatibility("keep", tag="00080020", name="StudyDate") is None
    assert operand_tag_incompatibility("always", tag="00080018", name="SOPInstanceUID") is None

    for date_op in ("lookup_dateoffset", "incrementdate", "rebasedate"):
        assert operand_tag_incompatibility(date_op, tag="00080020", name="StudyDate") is None
        assert operand_tag_incompatibility(date_op, tag="00080018", name="SOPInstanceUID") is not None
        assert operand_tag_incompatibility(date_op, tag="00100010", name="PatientName") is not None

    date_ids = {s.id for s in operands_for_tag(tag="00080020", name="StudyDate")}
    assert "hashdate" in date_ids and "incrementdate" in date_ids
    assert "lookup_dateoffset" in date_ids and "rebasedate" in date_ids
    assert "uid" not in date_ids and "ptid" not in date_ids and "round" not in date_ids
    assert "keep" in date_ids and "remove" in date_ids

    uid_ids = {s.id for s in operands_for_tag(tag="00080018", name="SOPInstanceUID")}
    assert "uid" in uid_ids and "hashdate" not in uid_ids and "ptid" not in uid_ids
    assert "lookup_dateoffset" not in uid_ids and "incrementdate" not in uid_ids


def test_incrementdate_bulk_updates_all_date_shift_fields() -> None:
    from anonymizer.controller.anonymizer_script import (
        ScriptDocument,
        ScriptRule,
        apply_incrementdate_to_rules,
        format_incrementdate_affected_lines,
        rules_for_incrementdate_bulk,
    )

    doc = ScriptDocument(
        rules=[
            ScriptRule("00080020", "StudyDate", "T", "@hashdate"),
            ScriptRule("00080021", "SeriesDate", "T", "@hashdate"),
            ScriptRule("00100010", "PatientName", "T", "@empty"),
            ScriptRule("0008002A", "AcquisitionDateTime", "T", "@lookup(this,dateoffset)"),
            ScriptRule("00080023", "ContentDate", "T", "@rebasedate(this,19600101)"),
            ScriptRule("00080050", "AccessionNumber", "T", "@acc"),
        ]
    )
    affected = rules_for_incrementdate_bulk(doc, selected_tag="00080020")
    assert [r.tag for r in affected] == ["00080020", "00080021", "00080023", "0008002A"]
    listing = format_incrementdate_affected_lines(affected)
    assert "0008,0020" in listing and "@hashdate" in listing
    assert "0008,002A" in listing
    assert "0008,0023" in listing and "@rebasedate" in listing

    updated = apply_incrementdate_to_rules(doc, 42, selected_tag="00080020")
    assert set(updated) == {"00080020", "00080021", "0008002A", "00080023"}
    assert doc.get_rule("00080020").operation == "@incrementdate(this,42)"
    assert doc.get_rule("00080021").operation == "@incrementdate(this,42)"
    assert doc.get_rule("0008002A").operation == "@incrementdate(this,42)"
    assert doc.get_rule("00080023").operation == "@incrementdate(this,42)"
    assert doc.get_rule("00100010").operation == "@empty"

    # Selecting a non-shifted date-like keep still includes existing shifters + selection.
    doc2 = ScriptDocument(
        rules=[
            ScriptRule("00080020", "StudyDate", "T", "@hashdate"),
            ScriptRule("00080023", "ContentDate", "T", ""),
        ]
    )
    tags = [r.tag for r in rules_for_incrementdate_bulk(doc2, selected_tag="00080023")]
    assert tags == ["00080020", "00080023"]


def test_search_removed_and_dictionary_capped(tmp_path: Path) -> None:
    doc = load_script_rules(_mini_script(tmp_path / "d.script"))
    hits = search_removed_rules(doc, "Length", limit=50)
    assert len(hits) == 1
    assert hits[0].tag == "00080001"

    dict_hits = search_dicom_dictionary("PatientName", limit=5)
    assert 1 <= len(dict_hits) <= 5
    assert all(len(h.tag) == 8 for h in dict_hits)
    assert all(h.keyword.strip() for h in dict_hits)
    # Unnamed retired tags (blank pydicom keyword → 300A0782) must not appear.
    assert all(h.tag != "300A0782" for h in search_dicom_dictionary("300A0782", limit=20))
    assert all(h.keyword.strip() for h in search_dicom_dictionary("", limit=200))

    assert has_missing_dictionary_tags(doc) is True
    missing = search_missing_dictionary_tags(doc, "PatientName", limit=5)
    assert missing
    assert all(doc.get_rule(h.tag) is None for h in missing)
    assert PAGE_SIZE == 300


def test_add_from_dictionary_and_validate_document(tmp_path: Path) -> None:
    doc = load_script_rules(_mini_script(tmp_path / "e.script"))
    add_rule_from_dictionary(doc, tag="00081030", name="StudyDescription", operation="")
    assert doc.get_rule("00081030") is not None
    assert validate_document(doc) == []
    with pytest.raises(ValueError, match="already"):
        add_rule_from_dictionary(doc, tag="00081030", name="StudyDescription", operation="")


def test_page_slice() -> None:
    items = [ScriptRule(tag=f"{i:08X}", name=str(i), en="T", operation="") for i in range(10)]
    page, index, count = page_slice(items, 0, page_size=3)
    assert len(page) == 3
    assert index == 0
    assert count == 4


def test_stage_script_edit(controller, tmp_path: Path) -> None:
    src = _mini_script(tmp_path / "stage_in.script")
    doc = load_script_rules(src)
    promote_rule(doc, "00080001", "@empty()")
    dest = stage_script_edit(controller.model, doc)
    assert dest == private_anonymizer_script_path(controller.model)
    assert dest.is_file()
    assert controller.model.anonymizer_script_path == dest
    reloaded = load_script_rules(dest)
    assert reloaded.get_rule("00080001").operation == "@empty()"


def test_commit_script_edit_reloads_tag_keep(controller) -> None:
    from anonymizer.controller.process_ctp_lookup import _DEFAULT_SCRIPT_PATH

    src = Path(controller.model.anonymizer_script_path)
    if not src.is_file():
        src = _DEFAULT_SCRIPT_PATH
    doc = load_script_rules(src)
    patient = doc.get_rule("00100020")
    assert patient is not None
    if is_remove_operation(patient.operation):
        promote_rule(doc, "00100020", "@ptid")
    demote_rule(doc, "00100020")

    dest = commit_script_edit(controller, doc)
    assert dest.is_file()
    assert "00100020" not in controller.anonymizer.model._tag_keep
    assert controller.model.anonymizer_script_path == dest
