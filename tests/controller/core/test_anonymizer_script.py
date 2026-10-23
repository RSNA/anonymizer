"""Tests for anonymizer script editor controller helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.dates import (
    incrementdate_days,
    is_date_delta_operation,
    rebasedate_origin,
)
from anonymizer.controller.script.date_rules import rules_for_incrementdate_bulk
from anonymizer.controller.script.document import (
    ScriptDocument,
    ScriptRule,
    load_script_rules,
    validate_document,
    write_script_rules,
)
from anonymizer.controller.script.operands import (
    always_literal_text,
    format_operand,
    is_remove_operation,
    operand_id_for_operation,
    operand_id_from_syntax,
    validate_operation,
)
from anonymizer.model.project import BASIC_OPTIONS, RETAIN_OPTIONS
from anonymizer.utils.dicom_dictionary import (
    dicom_applicable_standard_text,
    dicom_standard_version,
    format_dicom_tag,
    format_tag_description_line,
    search_dicom_dictionary,
    tag_dictionary_meta,
)
from anonymizer.view.settings.script_editor import (
    PAGE_SIZE,
    ScriptViewMode,
    add_rule_from_dictionary,
    apply_incrementdate_to_rules,
    confidentiality_options_changed,
    demote_rule,
    embedded_phi_batch_explainer,
    filter_rules,
    format_incrementdate_affected_lines,
    has_missing_dictionary_tags,
    operand_tag_incompatibility,
    operands_for_tag,
    options_switch_confirm_message,
    page_slice,
    promote_rule,
    search_missing_dictionary_tags,
    search_removed_rules,
)
from tests.paths import DEFAULT_ANONYMIZER_SCRIPT


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
        encoding="utf-8")
    return path


def test_load_write_round_trip_preserves_remove_and_r(tmp_path: Path) -> None:
    src = _mini_script(tmp_path / "in.script")
    doc = load_script_rules(src)
    assert len(doc.rules) == 5
    assert doc.get_rule("00080016").operation == "@keep"
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
    promote_rule(doc, "00080001", "@keep")
    assert doc.get_rule("00080001").operation == "@keep"
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
    assert validate_operation("@safe()") is None
    assert operand_id_for_operation("@safe()") == "safe"
    assert format_operand("keep") == "@keep"
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
    assert operand_id_for_operation("@keep") == "keep"
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
    assert operand_id_from_syntax("@keep") == "keep"
    assert operand_id_from_syntax("@round(this,n)") == "round"
    assert operand_id_from_syntax("@always()") == "always"
    assert operand_id_from_syntax("@incrementdate(this,n)") == "incrementdate"
    assert operand_id_from_syntax("@rebasedate(this,origin)") == "rebasedate"

    assert incrementdate_days("@incrementdate(this,42)") == 42
    assert rebasedate_origin("@rebasedate(this,19600101)") == "19600101"
    assert rebasedate_origin("@rebasedate") == "19600101"
    assert is_date_delta_operation("@hashdate")
    assert is_date_delta_operation("@incrementdate(this,1)")
    assert is_date_delta_operation("@rebasedate(this,19600101)")
    assert is_date_delta_operation("@lookup(this,dateoffset)")
    assert not is_date_delta_operation("@keep")


def test_tag_dictionary_meta_and_dicom_version() -> None:
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


def test_incrementdate_bulk_updates_all_date_delta_fields() -> None:
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
            ScriptRule("00080023", "ContentDate", "T", "@keep"),
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
    add_rule_from_dictionary(doc, tag="00081030", name="StudyDescription", operation="@keep")
    assert doc.get_rule("00081030").operation == "@keep"
    assert validate_document(doc) == []
    with pytest.raises(ValueError, match="already"):
        add_rule_from_dictionary(doc, tag="00081030", name="StudyDescription", operation="@keep")


def test_page_slice() -> None:
    items = [ScriptRule(tag=f"{i:08X}", name=str(i), en="T", operation="@keep") for i in range(10)]
    page, index, count = page_slice(items, 0, page_size=3)
    assert len(page) == 3
    assert index == 0
    assert count == 4


def test_write_project_script_path_and_reload(controller, tmp_path: Path) -> None:
    src = _mini_script(tmp_path / "stage_in.script")
    doc = load_script_rules(src)
    promote_rule(doc, "00080001", "@empty()")
    controller.model.anonymizer_script_path = (
        Path(controller.model.storage_dir)
        / f"{controller.model.site_id}-anonymizer.script"
    )
    dest = controller.model.anonymizer_script_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_script_rules(dest, doc)
    assert dest.is_file()
    reloaded = load_script_rules(dest)
    assert reloaded.get_rule("00080001").operation == "@empty()"

    patient = doc.get_rule("00100020")
    if patient is not None and is_remove_operation(patient.operation):
        promote_rule(doc, "00100020", "@ptid")
    if doc.get_rule("00100020") is not None:
        demote_rule(doc, "00100020")
    write_script_rules(dest, doc)
    controller.anonymizer.reload_script(dest)
    assert "00100020" not in controller.anonymizer.model._tag_keep


def test_packaged_script_paths() -> None:
    default = DEFAULT_ANONYMIZER_SCRIPT
    assert default.name == "default-anonymizer.script"
    assert default.is_file()
    # Install-dir relative path used by product code after main chdir / test conftest.
    relative = Path("assets/scripts/default-anonymizer.script")
    assert relative.is_file()
    assert relative.resolve() == default.resolve()


def test_confidentiality_options_changed() -> None:
    assert confidentiality_options_changed(
        selected=RETAIN_OPTIONS,
        installed=BASIC_OPTIONS)
    assert not confidentiality_options_changed(
        selected=RETAIN_OPTIONS,
        installed=RETAIN_OPTIONS)
    strict_batch = embedded_phi_batch_explainer(BASIC_OPTIONS)
    clinical_batch = embedded_phi_batch_explainer(RETAIN_OPTIONS)
    assert "OCR on burnt-in image pixels" in strict_batch
    assert "OCR on burnt-in image pixels" in clinical_batch
    assert "already removed" in strict_batch
    assert "kept private" in clinical_batch


def test_options_switch_confirm_message() -> None:
    message = options_switch_confirm_message()
    assert "Custom script edits will be lost" in message
    assert "not re-processed" in message
    assert "SR" in message and "PDF" in message

