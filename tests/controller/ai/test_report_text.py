"""process_report_text: SR/PDF extract, detect, remove, write (Basic Text SR)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydicom import Dataset, dcmread
from pydicom.dataset import FileMetaDataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.embedded_phi.classify_series import (
    ENCAPSULATED_PDF_SOP_CLASS_UID,
    SeriesKind,
    classify_series,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity, replace_entities
from anonymizer.controller.ai.embedded_phi.pixel.ocr_transcript_sr import (
    cleansed_ocr_lines,
    write_ocr_report_sr,
)
from anonymizer.controller.ai.embedded_phi.report.process_report_text import (
    BASIC_TEXT_SR_SOP_CLASS_UID,
    _render_plain_text_pdf,
    build_basic_text_sr,
    detect_phi,
    encapsulated_pdf_bytes,
    entities_from_study_phi,
    extract_report_text,
    remove_phi,
    write_report_text,
)
from anonymizer.model.anonymizer import StudyPhiHeader

PHONE_TEXT = "Call (404) 555-0162 for results."


def _text_item(text: str) -> Dataset:
    item = Dataset()
    item.RelationshipType = "CONTAINS"
    item.ValueType = "TEXT"
    item.TextValue = text
    return item


def _make_sr(path: Path, texts: list[str], *, nested: str | None = None) -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = BASIC_TEXT_SR_SOP_CLASS_UID
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = BASIC_TEXT_SR_SOP_CLASS_UID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.PatientID = "ANON0001"
    ds.PatientName = "ANON0001"
    ds.Modality = "SR"
    ds.SeriesDescription = "Findings"
    items = [_text_item(t) for t in texts]
    if nested is not None:
        parent = items[0]
        parent.ContentSequence = DicomSequence([_text_item(nested)])
    ds.ContentSequence = DicomSequence(items)
    ds.save_as(path, enforce_file_format=True)
    return ds


@pytest.fixture
def sr_series(tmp_path: Path) -> Path:
    series = tmp_path / "series"
    series.mkdir()
    _make_sr(series / "a.dcm", [PHONE_TEXT, "No acute findings."], nested="Email jane.doe@hospital.org")
    return series


def _fake_detect(text: str, *, locale: str = "en_US"):
    del locale
    ents: list[Entity] = []
    for label, needle in (("PHONE", "(404) 555-0162"), ("EMAIL", "jane.doe@hospital.org")):
        if needle in text:
            start = text.index(needle)
            ents.append(Entity(label, start, start + len(needle), 0.9, label))
    return ents


def test_entities_from_study_phi_matches_patient_id_and_accession() -> None:
    ds = Dataset()
    ds.PatientID = "ANON-42"
    ds.AccessionNumber = "ACC-HASH"
    ds.PatientName = "ANON-42"
    ds.StudyDate = "20200115"
    header = StudyPhiHeader(
        patient_id="MRN998877",
        accession_number="DT2455",
        patient_name="DOE^JANE",
        study_date="20191201",
    )
    text = "Patient MRN998877 Acc DT2455 Name DOE^JANE DOB unrelated."
    ents = entities_from_study_phi(text, ds, header)
    frags = {text[e.start : e.end]: e for e in ents}
    assert "MRN998877" in frags
    assert frags["MRN998877"].replacement == "ANON-42"
    assert frags["MRN998877"].label == "PatientID"
    assert "DT2455" in frags
    assert frags["DT2455"].label == "AccessionNumber"
    assert frags["DT2455"].replacement == "ACC-HASH"
    assert "DOE^JANE" in frags
    assert frags["DOE^JANE"].label == "PatientName"


def test_remove_phi_metadata_always_writes_anon_values() -> None:
    text = "ID MRN998877 / Acc DT2455"
    ents = [
        Entity(
            "PatientID",
            text.index("MRN998877"),
            text.index("MRN998877") + len("MRN998877"),
            1.0,
            "METADATA_PatientID",
            "ANON-42",
        ),
        Entity(
            "AccessionNumber",
            text.index("DT2455"),
            text.index("DT2455") + len("DT2455"),
            1.0,
            "METADATA_AccessionNumber",
            "ACC-HASH",
        ),
    ]
    for synthetic in (False, True):
        replaced = remove_phi(text, ents, synthetic=synthetic)
        assert "ANON-42" in replaced
        assert "ACC-HASH" in replaced
        assert "MRN998877" not in replaced
        assert "DT2455" not in replaced


def test_detect_phi_metadata_precedes_ner(tmp_path: Path) -> None:
    path = tmp_path / "meta.dcm"
    body = "Patient ID MRN998877 called (404) 555-0162."
    _make_sr(path, [body])
    ds = dcmread(path)
    ds.PatientID = "ANON-42"
    header = StudyPhiHeader(patient_id="MRN998877")

    def _fake_detect_overlap(text: str, *, locale: str = "en_US") -> list[Entity]:
        # NER would also tag the PatientID string as generic ID — metadata must win.
        del locale
        start = text.index("MRN998877")
        return [
            Entity("ID", start, start + len("MRN998877"), 0.9, "ID"),
            Entity("PHONE", text.index("(404)"), text.index("(404)") + len("(404) 555-0162"), 0.9, "PHONE"),
        ]

    with patch(
        "anonymizer.controller.ai.embedded_phi.report.process_report_text.detect_entities",
        side_effect=_fake_detect_overlap,
    ):
        text, ents = detect_phi(ds, phi_header=header)
    assert "MRN998877" in text  # detect does not rewrite
    by_frag = {text[e.start : e.end]: e for e in ents}
    assert by_frag["MRN998877"].label == "PatientID"
    assert by_frag["MRN998877"].replacement == "ANON-42"
    assert by_frag["(404) 555-0162"].label == "PHONE"
    assert sum(1 for e in ents if e.start == by_frag["MRN998877"].start) == 1


def test_extract_sr_text_joins_nested_slots(sr_series: Path) -> None:
    ds = dcmread(sr_series / "a.dcm")
    text = extract_report_text(ds)
    assert PHONE_TEXT in text
    assert "jane.doe@hospital.org" in text
    assert "No acute findings." in text


def test_extract_sr_text_without_value_type() -> None:
    """Ingest may @remove ValueType while keeping TextValue — extract must still work."""
    ds = Dataset()
    ds.Modality = "SR"
    ds.SOPClassUID = BASIC_TEXT_SR_SOP_CLASS_UID
    item = Dataset()
    item.RelationshipType = "CONTAINS"
    item.TextValue = "Device Observer Name Alpha-15104"
    ds.ContentSequence = DicomSequence([item])
    text = extract_report_text(ds)
    assert "Alpha-15104" in text


def test_extract_sr_dedupes_repeated_short_values_keeps_table() -> None:
    """Dose SRs repeat device/protocol TEXT per event; Comment table stays once."""
    ds = Dataset()
    ds.Modality = "SR"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.88.67"
    slots = [
        "SIEMENS",
        "Fluorospot Compact S1",
        "15104",
        "Ortho Standard",
        "SIEMENS",
        "Fluorospot Compact S1",
        "15104",
        "Ortho Standard",
        "OGP| dGy*cm^2| kV\r\nOrtho Standard| 0.319| 72.7\r\n\r\nOrtho Standard| 0.174| 70.9",
    ]
    ds.ContentSequence = DicomSequence([_text_item(t) for t in slots])
    text = extract_report_text(ds)
    assert text.count("SIEMENS") == 1
    assert text.count("15104") == 1
    assert text.count("Ortho Standard") >= 1  # once as short + rows inside table
    assert "OGP| dGy*cm^2| kV" in text
    assert "0.319" in text
    assert "\r" not in text
    # No blank lines inside the table.
    assert "\n\n" not in text


def test_replace_entities_respects_subset() -> None:
    text = "Call (404) 555-0162 and mail a.b@example.org"
    ents = [Entity("EMAIL", text.index("a.b@"), len(text), 0.9, "EMAIL")]
    out, _ = replace_entities(text, ents, mode="blank")
    assert out == "Call (404) 555-0162 and mail"


def test_detect_remove_write_sr_roundtrip(sr_series: Path) -> None:
    path = sr_series / "a.dcm"
    ds = dcmread(path)
    with patch(
        "anonymizer.controller.ai.embedded_phi.report.process_report_text.detect_entities",
        side_effect=_fake_detect,
    ):
        text, entities = detect_phi(ds)
    assert any(e.label == "PHONE" for e in entities)
    assert any(e.label == "EMAIL" for e in entities)

    # Exclude email: remove phone only.
    phone_ents = [e for e in entities if e.label == "PHONE"]
    cleaned = remove_phi(text, phone_ents, synthetic=False)
    assert "555-0162" not in cleaned
    assert "jane.doe@hospital.org" in cleaned

    sr = write_report_text(ds, cleaned)
    assert sr.Modality == "SR"
    assert sr.SOPClassUID == BASIC_TEXT_SR_SOP_CLASS_UID
    assert "555-0162" not in ds.ContentSequence[0].TextValue
    assert ds.ContentSequence[0].ContentSequence[0].TextValue  # email slot kept
    ds.save_as(path, enforce_file_format=True)
    on_disk = dcmread(path)
    assert "555-0162" not in on_disk.ContentSequence[0].TextValue


def test_pdf_detect_remove_write_keeps_text_layer(tmp_path: Path) -> None:
    seed_pdf = _render_plain_text_pdf(f"Patient call {PHONE_TEXT}")
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = ENCAPSULATED_PDF_SOP_CLASS_UID
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = ENCAPSULATED_PDF_SOP_CLASS_UID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.PatientID = "ANON0001"
    ds.Modality = "DOC"
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    ds.EncapsulatedDocument = seed_pdf + (b"\x00" if len(seed_pdf) % 2 else b"")

    assert "555-0162" in extract_report_text(ds)

    with patch(
        "anonymizer.controller.ai.embedded_phi.report.process_report_text.detect_entities",
        side_effect=_fake_detect,
    ):
        text, entities = detect_phi(ds)
    assert any(e.label == "PHONE" for e in entities)
    cleaned = remove_phi(text, entities, synthetic=False)
    sr = write_report_text(ds, cleaned)
    assert sr.SOPClassUID == BASIC_TEXT_SR_SOP_CLASS_UID
    after_bytes = encapsulated_pdf_bytes(ds)
    assert after_bytes and after_bytes.startswith(b"%PDF")
    after = extract_report_text(ds)
    assert "555-0162" not in after
    assert after.strip()  # still extractable text


def test_detect_phi_image_only_pdf_empty(tmp_path: Path) -> None:
    # Minimal PDF with no text operators (empty content stream page).
    empty_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>endobj\n"
        b"4 0 obj<< /Length 0 >>stream\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000214 00000 n \n"
        b"trailer<< /Size 5 /Root 1 0 R >>\nstartxref\n264\n%%EOF\n"
    )
    ds = Dataset()
    ds.Modality = "DOC"
    ds.SOPClassUID = ENCAPSULATED_PDF_SOP_CLASS_UID
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    ds.EncapsulatedDocument = empty_pdf
    text, ents = detect_phi(ds)
    assert text == ""
    assert ents == []


def test_detect_phi_unsupported_modality() -> None:
    ds = Dataset()
    ds.Modality = "CT"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    with pytest.raises(ValueError, match="Unsupported"):
        detect_phi(ds)


def test_build_basic_text_sr_from_ocr_lines() -> None:
    source = Dataset()
    source.PatientID = "ANON1"
    source.PatientName = "ANON1"
    source.StudyInstanceUID = generate_uid()
    sr = build_basic_text_sr(source, ["Line one", "", "Line two"])
    assert sr.Modality == "SR"
    assert sr.StudyInstanceUID == source.StudyInstanceUID
    assert [i.TextValue for i in sr.ContentSequence] == ["Line one", "Line two"]


def test_write_ocr_report_sr_creates_sibling_series(tmp_path: Path) -> None:
    study = tmp_path / "study"
    series = study / "ser1"
    series.mkdir(parents=True)
    src = Dataset()
    src.file_meta = FileMetaDataset()
    src.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    src.SOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    src.SOPInstanceUID = generate_uid()
    src.file_meta.MediaStorageSOPClassUID = src.SOPClassUID
    src.file_meta.MediaStorageSOPInstanceUID = src.SOPInstanceUID
    src.StudyInstanceUID = generate_uid()
    src.PatientID = "ANON1"
    src.Modality = "SC"
    src.save_as(series / "i.dcm", enforce_file_format=True)

    out = write_ocr_report_sr(series, ["Hello"])
    assert out is not None and out.parent.parent == study
    assert classify_series(out.parent) == SeriesKind.NATIVE_SR
    assert write_ocr_report_sr(series, ["", "  "]) is None


def test_cleansed_ocr_lines_blank_phi() -> None:
    def _fake(text: str, *, locale: str = "en_US"):
        del locale
        if PHONE_TEXT in text:
            start = text.index("(404)")
            end = start + len("(404) 555-0162")
            return [Entity("PHONE", start, end, 0.9, "PHONE")]
        return []

    with patch(
        "anonymizer.controller.ai.embedded_phi.pixel.ocr_transcript_sr.detect_entities",
        side_effect=_fake,
    ):
        lines = cleansed_ocr_lines({1: ["Dose 12 mGy"], 0: [PHONE_TEXT]})
    assert all("555-0162" not in ln for ln in lines)
    assert any("Dose" in ln for ln in lines)


def test_classify_series_sop_class_and_text_report(tmp_path: Path, sr_series: Path) -> None:
    assert classify_series(sr_series) == SeriesKind.NATIVE_SR
    assert classify_series(".", modality="CT") == SeriesKind.IMAGING
    assert classify_series(".", modality="SC") == SeriesKind.OTHER_PIXEL

    d = tmp_path / "sc"
    d.mkdir()
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    ds.SOPInstanceUID = generate_uid()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "SC"
    ds.SeriesDescription = "Dose Report"
    ds.save_as(d / "x.dcm", enforce_file_format=True)
    assert classify_series(d) == SeriesKind.PIXEL_TEXT_REPORT
