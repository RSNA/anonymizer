"""Unit tests for shared pre-NER radiology filters."""

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import (
    MetadataNerItem,
    collect_anonymized_values,
    is_compact_dicom_datetime,
    is_dicom_uid_text,
    looks_like_prose_carrier,
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
    body = (
        "XR CHEST AP PORTABLE for Douglas Davidson "
        "id 994250-000003 uid 1.2.840.10008.5.1.4.1.1.1 date 20190816"
    )
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
        MetadataNerItem(text="DERIVED", field_name="Image Type", vr="CS"),
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
    # No whitelist passed here — "AP" stays for OpenMed.
    assert " AP " in f" {value} "


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
    assert looks_like_prose_carrier("XR CHEST AP PORTABLE for Douglas")
    assert looks_like_prose_carrier("Davidson^Douglas")
    assert not looks_like_prose_carrier("100000")
    assert not looks_like_prose_carrier("MONOCHROME1")


def test_wrap_field_is_uniform() -> None:
    ner, start, end = wrap_field_for_ner("StudyDescription", "MAMMO for Jane Doe")
    assert ner == "StudyDescription: MAMMO for Jane Doe."
    assert ner[start:end] == "MAMMO for Jane Doe"
    ner2, start2, end2 = wrap_field_for_ner("PatientName", "SMITH^JOHN")
    assert ner2 == "PatientName: SMITH^JOHN."
    assert ner2[start2:end2] == "SMITH^JOHN"
