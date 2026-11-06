"""Unit tests for shared pre-NER radiology filters."""

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import (
    MetadataNerItem,
    PreparedMetadataSegment,
    caret_to_space_for_ner,
    collect_anonymized_values,
    date_time_pattern_entities,
    descriptor_phi_pattern_entities,
    drop_measurement_digit_id_entities,
    is_compact_dicom_datetime,
    is_dicom_uid_text,
    mask_text_for_ner,
    prepare_metadata_ner_segments,
    remap_ner_entities_to_original,
    wrap_field_for_ner,
)


def test_collect_anonymized_values_from_dataset() -> None:
    ds = Dataset()
    ds.PatientID = "994250-000003"
    ds.AccessionNumber = "ACC-9"
    values = collect_anonymized_values(ds, extra=["extra"])
    assert "994250-000003" in values
    assert "ACC-9" in values
    assert "extra" in values


def test_mask_text_for_ner_masks_anon_uid_date_whitelist() -> None:
    body = "XR CHEST AP PORTABLE for Douglas Davidson id 994250-000003 uid 1.2.840.10008.5.1.4.1.1.1 date 20190816"
    result = mask_text_for_ner(
        body,
        whitelist=["PORTABLE", "AP"],
        anon_values={"994250-000003"},
        log_context="test",
    )
    assert len(result.text) == len(body)
    assert "Douglas Davidson" in result.text
    assert "994250-000003" not in result.text
    assert "1.2.840.10008.5.1.4.1.1.1" not in result.text
    assert "20190816" not in result.text
    assert "PORTABLE" not in result.text
    reasons = {h.reason for h in result.hits}
    assert "anonymized" in reasons
    assert "uid" in reasons
    assert "date" in reasons
    assert "whitelist" in reasons


def test_mask_text_for_ner_masks_clock_time_keeps_date() -> None:
    """Only the date component reaches the model — clock times are masked."""
    body = "Software 06.00.00 2010/04/16 09:50:45 and 9:05 PM done"
    result = mask_text_for_ner(body, log_context="test")
    assert len(result.text) == len(body)
    assert "2010/04/16" in result.text
    assert "09:50:45" not in result.text
    assert "9:05 PM" not in result.text
    assert {h.text for h in result.hits if h.reason == "time"} == {"09:50:45", "9:05 PM"}


def test_mask_text_for_ner_can_leave_uid_date_time_visible() -> None:
    """Metadata path opts out of UID/date/time masks so Clean Descriptors can scrub."""
    body = "PET-CT SERIES 20101203 uid 1.2.840.10008.1.2 at 09:50:45"
    result = mask_text_for_ner(
        body,
        mask_uids=False,
        mask_dates=False,
        mask_times=False,
        log_context="test",
    )
    assert result.text == body
    assert result.hits == ()


def test_date_time_pattern_entities_claims_compact_da_and_clock() -> None:
    """OpenMed gap-fill: bare YYYYMMDD and colon times become DATE on original text."""
    body = "PET-CT SERIES 20101203 at 09:50:45"
    ents = date_time_pattern_entities(body)
    by_raw = {e.raw_label: body[e.start : e.end] for e in ents}
    assert by_raw["compact_da"] == "20101203"
    assert by_raw["colon_tm"] == "09:50:45"
    assert all(e.label == "DATE" for e in ents)
    dotted = date_time_pattern_entities("DOB: 04.25.1937")
    assert [(e.raw_label, "DOB: 04.25.1937"[e.start : e.end]) for e in dotted] == [
        ("punctuated_date", "04.25.1937")
    ]
    assert date_time_pattern_entities("06.00.00") == []
    assert date_time_pattern_entities("1.2.840.10008.5.1.4.1.1.1") == []


def test_descriptor_phi_pattern_entities_ids_sites_doctor() -> None:
    """Post-NER gap-fill: long ID, SSN-like, at/by site, Dr. Name; keep at CT."""
    body = "Ordered for 8371727310 by PH; PET at FGH; Dr. Brennan; SSN 310-50-9582; at CT"
    ents = descriptor_phi_pattern_entities(body)
    frags = {(e.raw_label, body[e.start : e.end]) for e in ents}
    assert ("long_digit_id", "8371727310") in frags
    assert ("at_by_site", "PH") in frags
    assert ("at_by_site", "FGH") in frags
    assert ("dr_name", "Dr. Brennan") in frags
    assert ("ssn_like", "310-50-9582") in frags
    assert not any(frag == "CT" for _, frag in frags)
    # Bare digit runs are ID, not PHONE (PHONE requires separators).
    assert not any(raw == "phone" for raw, _ in frags)


def test_descriptor_phi_pattern_skips_whole_cell_pure_numeric() -> None:
    """Frame-duration style whole-cell numbers are not claimed as long-digit IDs."""
    assert descriptor_phi_pattern_entities("1800000") == []
    assert descriptor_phi_pattern_entities("0") == []
    assert descriptor_phi_pattern_entities("53.2000007629") == []
    assert descriptor_phi_pattern_entities("1140000.0") == []
    prose = "duration 1800000 ms"
    ents = descriptor_phi_pattern_entities(prose)
    assert [prose[e.start : e.end] for e in ents] == ["1800000"]


def test_descriptor_phi_pattern_at_site_name() -> None:
    """Multi-word Title Case facility after at/to is LOCATION."""
    body = "LUNG CA ACCRIN 6668 at Harris Community Clinic"
    ents = descriptor_phi_pattern_entities(body)
    frags = {(e.raw_label, body[e.start : e.end]) for e in ents}
    assert ("at_site_name", "Harris Community Clinic") in frags
    admitted = "Admitted to Palmer-Greene Memorial on 20170803"
    ents2 = descriptor_phi_pattern_entities(admitted)
    frags2 = {(e.raw_label, admitted[e.start : e.end]) for e in ents2}
    assert ("at_site_name", "Palmer-Greene Memorial") in frags2


def test_drop_measurement_digit_id_entities_float_fragments() -> None:
    """Digit-only ID spans inside floats / letter-free cells are dropped."""
    body = "53.2000007629"
    # Fractional run after the decimal point.
    ents = [
        Entity(label="ID", start=3, end=13, score=0.9, raw_label="ID"),
    ]
    assert drop_measurement_digit_id_entities(body, ents) == []

    freq = "638749910.0"
    ents = [
        Entity(label="ID", start=0, end=9, score=0.9, raw_label="ID"),
    ]
    assert drop_measurement_digit_id_entities(freq, ents) == []

    prose = "ordered for 8371727310 at PH"
    ents = [
        Entity(label="ID", start=12, end=22, score=0.9, raw_label="ID"),
    ]
    kept = drop_measurement_digit_id_entities(prose, ents)
    assert len(kept) == 1 and kept[0].start == 12

    # OpenMed trial / anatomy false positives.
    hist = "LUNG CA ACCRIN 6668 at Harris Community Clinic"
    ents = [
        Entity(label="ID", start=0, end=7, score=0.3, raw_label="user_name"),
        Entity(label="ID", start=8, end=19, score=0.4, raw_label="health_plan"),
    ]
    assert drop_measurement_digit_id_entities(hist, ents) == []

    # Hyphenated SSN-like IDs must stay (digit tokens only — not clinical).
    ssn_body = "Dynamic-3dfgre: PE1 for 404-99-3023"
    ssn_ents = [
        Entity(label="ID", start=24, end=35, score=1.0, raw_label="ssn_like"),
    ]
    kept_ssn = drop_measurement_digit_id_entities(ssn_body, ssn_ents)
    assert len(kept_ssn) == 1 and ssn_body[kept_ssn[0].start : kept_ssn[0].end] == ("404-99-3023")


def test_date_time_pattern_entities_keeps_decimal_measurement_fraction() -> None:
    """Fractional digits in 0.096000 / 0.000000 are not compact TM DATE."""
    measured = "measured,, 0.096000 cm-1,"
    none_val = "NONE, 0.000000 cm-1,"
    assert date_time_pattern_entities(measured) == []
    assert date_time_pattern_entities(none_val) == []
    # Signed Slice Location fractions are not compact DA.
    assert date_time_pattern_entities("-42.20077515") == []
    assert date_time_pattern_entities("42.20077515") == []
    # Whole-cell frame duration is not compact TM.
    assert date_time_pattern_entities("180000") == []
    # Impossible MMDD is not compact DA.
    assert date_time_pattern_entities("20077515") == []
    # Bare compact TM in prose still claimed.
    bare = date_time_pattern_entities("Acquisition 091530")
    assert [(e.raw_label, "Acquisition 091530"[e.start : e.end]) for e in bare] == [("compact_tm", "091530")]
    # Valid whole-cell DA still claimed (Series Number style PHI).
    da = date_time_pattern_entities("20101203")
    assert [(e.raw_label, "20101203"[e.start : e.end]) for e in da] == [("compact_da", "20101203")]


def test_mask_text_for_ner_does_not_blank_decimal_fraction_as_time() -> None:
    """Report-body time mask must not wipe 0.096000 fractional digits."""
    body = "attenuation 0.096000 cm-1 and time 091530"
    result = mask_text_for_ner(body, mask_uids=False, mask_dates=False, mask_times=True)
    assert "0.096000" in result.text
    assert "091530" not in result.text


def test_prepare_metadata_leaves_embedded_date_uid_for_ner() -> None:
    """Embedded DA/UID stay in ner_text; whole-cell date/UID rows still skipped."""
    items = [
        MetadataNerItem(
            text="PET-CT SERIES 20101203",
            field_name="Series Description",
            vr="LO",
        ),
        MetadataNerItem(
            text="ref 1.2.840.10008.5.1.4.1.1.1 done",
            field_name="Image Comments",
            vr="LT",
        ),
        MetadataNerItem(text="20101203", field_name="Study Date", vr="DA", is_date=True),
        MetadataNerItem(text="1.2.840.10008.1.2", field_name="SOP Class UID", vr="UI"),
    ]
    prepared = prepare_metadata_ner_segments(items, whitelist=[], log_context="test")
    assert len(prepared) == 2
    by_field = {seg.field_name: seg for seg in prepared}
    series = by_field["Series Description"]
    assert "20101203" in series.ner_text[series.value_start : series.value_end]
    comments = by_field["Image Comments"]
    assert "1.2.840.10008.5.1.4.1.1.1" in comments.ner_text[comments.value_start : comments.value_end]


def test_prepare_metadata_ner_segments_wraps_and_skips() -> None:
    items = [
        MetadataNerItem(
            text="XR CHEST AP PORTABLE for Douglas Davidson",
            field_name="Series Description",
            vr="LO",
        ),
        MetadataNerItem(text="1.2.840.10008.1.2", field_name="SOP Class UID", vr="UI"),
        MetadataNerItem(text="20190816", field_name="Study Date", vr="DA", is_date=True),
        MetadataNerItem(text="ANON-1", field_name="Patient ID", vr="LO"),
        MetadataNerItem(
            text="Basic Application Confidentiality Profile",
            field_name="Deidentification Method",
            tag="00120063",
            is_anonymizer_field=True,
        ),
        MetadataNerItem(text="AP", field_name="View", vr="CS"),
    ]
    prepared = prepare_metadata_ner_segments(
        items,
        anon_values={"ANON-1"},
        log_context="test",
    )
    assert len(prepared) == 1
    seg = prepared[0]
    assert seg.original_text.startswith("XR CHEST")
    assert seg.ner_text.startswith("Series Description: ")
    assert seg.ner_text.endswith(".")
    value = seg.ner_text[seg.value_start : seg.value_end]
    assert len(value) == len(seg.original_text)
    assert "Douglas Davidson" in value
    assert " AP " in f" {value} "


def test_prepare_skips_safe_script_operation() -> None:
    """@safe() Device Serial / Manufacturer Model never enter NER wrap."""
    items = [
        MetadataNerItem(
            text="G4EGU8PGUYWPI",
            field_name="Device Serial Number",
            tag="00181000",
            vr="LO",
            script_operation="@safe()",
        ),
        MetadataNerItem(
            text="Sagittal for Sandra Lindsey",
            field_name="Series Description",
            tag="0008103E",
            vr="LO",
            script_operation="@keep",
        ),
    ]
    prepared = prepare_metadata_ner_segments(items, whitelist=[], log_context="test")
    assert len(prepared) == 1
    assert prepared[0].original_text == "Sagittal for Sandra Lindsey"


def test_prepare_keeps_is_ds_including_impure() -> None:
    """IS/DS (including impure with embedded text) are prepared for NER."""
    items = [
        MetadataNerItem(text="2", field_name="Series Number", vr="IS"),
        MetadataNerItem(text="20101203", field_name="Series Number", vr="IS"),
        MetadataNerItem(text="360000", field_name="Actual Frame Duration", vr="IS"),
        MetadataNerItem(text="AP", field_name="View Position", vr="CS"),
        MetadataNerItem(text="1.5", field_name="Slice Thickness", vr="DS"),
        MetadataNerItem(text="1234.5", field_name="Rescale Slope", vr="DS"),
        MetadataNerItem(
            text="[164., -113., 101.0]",
            field_name="Image Position (Patient)",
            vr="DS",
        ),
        MetadataNerItem(
            text="[310, 310]",
            field_name="Pixel Aspect Ratio",
            vr="IS",
        ),
        MetadataNerItem(
            text="350\\421",
            field_name="Field of View Dimension(s)",
            vr="IS",
        ),
        MetadataNerItem(
            text="62.9 Michelle",
            field_name="Rescale Slope",
            vr="DS",
        ),
    ]
    prepared = prepare_metadata_ner_segments(items, whitelist=[], log_context="test")
    by_text = {seg.original_text: seg for seg in prepared}
    assert "20101203" in by_text
    assert "360000" in by_text
    assert "2" in by_text
    assert "1.5" in by_text
    assert "1234.5" in by_text
    assert "[164., -113., 101.0]" in by_text
    assert "[310, 310]" in by_text
    assert "350\\421" in by_text
    # CS digits_only empties letter-only codes.
    assert "AP" not in by_text
    # Impure DS keeps letters visible for NER (no digits_only glue).
    assert "62.9 Michelle" in by_text
    assert by_text["62.9 Michelle"].ner_text.startswith("Rescale Slope: ")


def test_prepare_keeps_underscore_protocol_token() -> None:
    """All-caps protocol tokens with digits/underscores are sent to NER."""
    items = [
        MetadataNerItem(
            text="1ACRIN_6664_DR_ZIMMERMAN",
            field_name="Protocol Name",
            vr="LO",
        ),
        MetadataNerItem(text="!!!", field_name="Junk", vr="LO"),
    ]
    prepared = prepare_metadata_ner_segments(items, whitelist=[], log_context="test")
    assert len(prepared) == 1
    assert prepared[0].original_text == "1ACRIN_6664_DR_ZIMMERMAN"
    assert prepared[0].ner_text == "Protocol Name: 1ACRIN_6664_DR_ZIMMERMAN."


def test_prepare_metadata_ner_segments_masks_whitelist_before_ner() -> None:
    items = [
        MetadataNerItem(text="US Biopsy Axilla", field_name="Series Description", vr="LO"),
        MetadataNerItem(text="US Axilla", field_name="Study Description", vr="LO"),
        MetadataNerItem(
            text="Long code meaning",
            field_name="Code Value",
            vr="LO",
            tag_path="ProcedureCodeSequence[0].CodeValue",
        ),
    ]
    prepared = prepare_metadata_ner_segments(
        items,
        whitelist=["US", "AXILLA"],
        anon_values=frozenset(),
        log_context="test",
    )
    # Whitelist-only cell is skipped; code field is skipped; keeper is masked.
    assert len(prepared) == 1
    seg = prepared[0]
    value = seg.ner_text[seg.value_start : seg.value_end]
    assert "Axilla" not in value
    assert "US " not in value
    assert "Biopsy" in value
    assert len(value) == len(seg.original_text)


def test_remap_ner_entities_to_original() -> None:
    items = [
        MetadataNerItem(text="Douglas Davidson", field_name="Patient Name", vr="PN"),
    ]
    prepared = prepare_metadata_ner_segments(items, whitelist=[], anon_values=frozenset())
    assert len(prepared) == 1
    seg = prepared[0]
    # Spans relative to ner_text
    ents = [
        Entity(
            label="FIRST_NAME",
            start=seg.value_start,
            end=seg.value_end,
            score=0.9,
            raw_label="first_name",
        ),
        Entity(label="FIRST_NAME", start=0, end=3, score=0.1, raw_label="noise"),  # in prefix
    ]
    mapped = remap_ner_entities_to_original(ents, seg)
    assert len(mapped) == 1
    assert mapped[0].start == 0
    assert mapped[0].end == len(seg.original_text)


def test_predicates() -> None:
    assert is_dicom_uid_text("1.2.840.10008.1.2")
    assert not is_dicom_uid_text("Douglas Davidson")
    assert is_compact_dicom_datetime("20190816")
    assert is_compact_dicom_datetime("085957.000")
    assert not is_compact_dicom_datetime("2020")


def test_wrap_field_is_uniform() -> None:
    ner, start, end = wrap_field_for_ner("StudyDescription", "MAMMO for Jane Doe")
    assert ner == "StudyDescription: MAMMO for Jane Doe."
    assert ner[start:end] == "MAMMO for Jane Doe"
    ner2, start2, end2 = wrap_field_for_ner("PatientName", "SMITH^JOHN")
    assert ner2 == "PatientName: SMITH^JOHN."
    assert ner2[start2:end2] == "SMITH^JOHN"


def test_caret_to_space_for_ner_same_length() -> None:
    raw = "LOPEZ^JOANN"
    spaced = caret_to_space_for_ner(raw)
    assert spaced == "LOPEZ JOANN"
    assert len(spaced) == len(raw)


def test_remap_after_caret_space_preserves_offsets() -> None:
    """NER spans on caret-spaced value remap onto the caret-bearing original."""
    original = "LOPEZ^JOANN"
    spaced = caret_to_space_for_ner(original)
    ner_text, vstart, vend = wrap_field_for_ner("Referring Physician's Name", spaced)
    prepared = PreparedMetadataSegment(
        original_text=original,
        ner_text=ner_text,
        value_start=vstart,
        value_end=vend,
        field_name="Referring Physician's Name",
    )
    # Model tags both name parts on the spaced value.
    ents = [
        Entity(label="LAST_NAME", start=vstart, end=vstart + 5),
        Entity(label="FIRST_NAME", start=vstart + 6, end=vstart + 11),
    ]
    mapped = remap_ner_entities_to_original(ents, prepared)
    assert [(e.label, original[e.start : e.end]) for e in mapped] == [
        ("LAST_NAME", "LOPEZ"),
        ("FIRST_NAME", "JOANN"),
    ]


def test_prepare_metadata_ner_segments_replaces_pn_caret_before_ner() -> None:
    """PersonName carets become spaces in ner_text; original keeps carets for remap."""
    items = [
        MetadataNerItem(
            text="LOPEZ^JOANN",
            field_name="Referring Physician's Name",
            vr="PN",
            tag_path="ReferringPhysicianName",
        ),
    ]
    prepared = prepare_metadata_ner_segments(items, whitelist=[], anon_values=frozenset())
    assert len(prepared) == 1
    seg = prepared[0]
    assert seg.original_text == "LOPEZ^JOANN"
    value = seg.ner_text[seg.value_start : seg.value_end]
    assert value == "LOPEZ JOANN"
    assert "^" not in value
    assert "^" in seg.original_text
