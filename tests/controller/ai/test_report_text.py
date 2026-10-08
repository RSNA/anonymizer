"""Report Text Review controller: SR walk, session detect/remove/save, hitchhikers, OCR→SR, PDF, routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydicom import Dataset, dcmread
from pydicom.dataset import FileMetaDataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series
from anonymizer.controller.ai.embedded_phi.ner.dicom_text_attributes import iter_hitchhiker_slots
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import PhiEntity
from anonymizer.controller.ai.embedded_phi.ner.process_series_text import process_series_text
from anonymizer.controller.ai.embedded_phi.ner.replace import apply_entities
from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import (
    extract_pdf_layout,
    extract_pdf_text,
    format_extracted_pdf_text,
    rects_for_span,
    render_plain_text_pdf,
)
from anonymizer.controller.ai.embedded_phi.report.report_from_ocr import (
    BASIC_TEXT_SR_SOP_CLASS_UID,
    build_basic_text_sr,
    write_ocr_report_sr,
)
from anonymizer.controller.ai.embedded_phi.report.report_session import ReportSession
from anonymizer.controller.ai.embedded_phi.report.report_sr import iter_sr_slots

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


def test_iter_sr_slots_walks_nested_content(sr_series: Path) -> None:
    ds = dcmread(sr_series / "a.dcm")
    slots = list(iter_sr_slots(ds))
    assert [s.text for s in slots] == [PHONE_TEXT, "Email jane.doe@hospital.org", "No acute findings."]
    slots[0].write("X")
    assert ds.ContentSequence[0].TextValue == "X"


def test_apply_entities_respects_subset() -> None:
    text = "Call (404) 555-0162 and mail a.b@example.org"
    ents = [PhiEntity("EMAIL", text.index("a.b@"), len(text))]
    assert apply_entities(text, ents, mode="blank") == "Call (404) 555-0162 and mail"


def test_session_detect_remove_save_capture(sr_series: Path) -> None:
    session = ReportSession(sr_series, "sr")
    scans = session.detect()
    assert session.counts().get("PHONE") == 1
    assert session.counts().get("EMAIL") == 1
    assert scans

    # Exclude the email: only the phone should be removed.
    email_scan = next(s for s in scans if any(e.label == "EMAIL" for e in s.entities))
    email_ent = next(e for e in email_scan.entities if e.label == "EMAIL")
    assert session.toggle_excluded(email_scan.slot.key, email_ent.start) is True
    assert session.counts().get("EMAIL", 0) == 0

    class FakeModel:
        def __init__(self) -> None:
            self.instance: dict[str, list[str]] = {}
            self.scanned: list[str] = []

        def set_instance_embedded_phi(self, uid: str, texts) -> bool:
            self.instance[uid] = list(texts)
            return True

        def set_series_embedded_phi_scanned(self, uid: str, *, scanned: bool = True) -> bool:
            self.scanned.append(uid)
            return True

    changed = session.remove("blank")
    assert changed == 1
    assert session.dirty
    model = FakeModel()
    saved = session.save(model)  # type: ignore[arg-type]
    assert saved == [sr_series / "a.dcm"]

    on_disk = dcmread(sr_series / "a.dcm")
    assert "555-0162" not in on_disk.ContentSequence[0].TextValue
    assert on_disk.ContentSequence[0].ContentSequence[0].TextValue == "Email jane.doe@hospital.org"
    # PHI-only capture: original entity text, never the report body.
    (texts,) = model.instance.values()
    assert any("555-0162" in t for t in texts)
    assert all("No acute findings" not in t for t in texts)
    assert model.scanned == [str(on_disk.SeriesInstanceUID)]


def test_session_synthetic_replaces_with_fake(sr_series: Path) -> None:
    session = ReportSession(sr_series, "sr")
    session.detect()
    session.remove("synth", project_id="p", anon_ptid="ANON0001")
    session.save(None)
    text = dcmread(sr_series / "a.dcm").ContentSequence[0].TextValue
    assert "(404) 555-0162" not in text
    assert text.startswith("Call (")


def test_pdf_session_remove_save_redacts_document(tmp_path: Path) -> None:
    from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import (
        PDF_SOP_CLASS_UID,
        encapsulated_pdf_bytes,
        extract_pdf_text,
        render_plain_text_pdf,
    )

    series = tmp_path / "pdf_series"
    series.mkdir()
    seed_pdf = render_plain_text_pdf(f"Patient call {PHONE_TEXT}")
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = PDF_SOP_CLASS_UID
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = PDF_SOP_CLASS_UID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.PatientID = "ANON0001"
    ds.Modality = "DOC"
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    ds.EncapsulatedDocument = seed_pdf + (b"\x00" if len(seed_pdf) % 2 else b"")
    ds.save_as(series / "report.dcm", enforce_file_format=True)

    assert "555-0162" in extract_pdf_text(dcmread(series / "report.dcm"))

    session = ReportSession(series, "pdf")
    assert session.can_edit
    session.detect(ocr_reader=None)  # native text arm only
    assert session.counts().get("PHONE", 0) >= 1
    session.remove("blank")
    saved = session.save(None)
    assert series / "report.dcm" in saved
    after_bytes = encapsulated_pdf_bytes(dcmread(series / "report.dcm"))
    assert after_bytes and after_bytes.startswith(b"%PDF")
    # Redacted page-image PDF: phone digits must not remain as extractable text.
    after = extract_pdf_text(dcmread(series / "report.dcm"))
    assert "555-0162" not in after


def test_pdf_session_empty_series_save_noop(tmp_path: Path) -> None:
    session = ReportSession(tmp_path, "pdf")
    assert session.can_edit
    assert session.save(None) == []


def test_extract_pdf_text_handles_non_pdf() -> None:
    assert extract_pdf_text(Dataset()) == ""


def test_extract_pdf_layout_char_boxes_align_with_text() -> None:
    data = render_plain_text_pdf("Patient: Jane Doe MRN 4455667")
    layouts = extract_pdf_layout(data)
    assert layouts
    page = layouts[0]
    assert len(page.text) == len(page.char_boxes)
    idx = page.text.find("Jane")
    assert idx >= 0
    rects = rects_for_span(page, idx, idx + 4)
    assert rects
    x0, y0, x1, y1 = rects[0]
    assert x1 > x0 and y1 > y0


def test_format_extracted_pdf_text_pairs_labels_and_collapses_tabs() -> None:
    raw = (
        "Patient:\t\n"
        "Mnikathi\tMxolisi\n"
        "ID\tNumber:\t\n"
        "0008295650082\n"
        "The\tsize\tand\tshape\tof\tthe\theart\tis\tnormal.\n"
    )
    formatted = format_extracted_pdf_text(raw)
    assert "Patient: Mnikathi Mxolisi" in formatted
    assert "ID Number: 0008295650082" in formatted
    assert "The size and shape of the heart is normal." in formatted
    assert "\t" not in formatted


def test_extract_pdf_text_roundtrip() -> None:
    pypdf = pytest.importorskip("pypdf")
    import io

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    ds = Dataset()
    ds.EncapsulatedDocument = buf.getvalue()
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    assert extract_pdf_text(ds) == ""  # blank page: parsed fine, no text


def test_hitchhiker_slots_and_batch_text(tmp_path: Path) -> None:
    series = tmp_path / "s"
    series.mkdir()
    ds = _make_sr(series / "b.dcm", ["Normal."])
    ds.ImageComments = "Patient phone (404) 555-0162"
    ds.ProtocolName = "CT HEAD"
    ds.save_as(series / "b.dcm", enforce_file_format=True)

    slots = list(iter_hitchhiker_slots(dcmread(series / "b.dcm")))
    assert {s.context for s in slots} == {"ImageComments", "ProtocolName"}

    dry = process_series_text(series, dry_run=True)
    assert dry.instances_changed == 0
    assert any("555-0162" in t for t in dry.removed)
    assert "555-0162" in str(dcmread(series / "b.dcm").ImageComments)

    result = process_series_text(series, mode="blank")
    assert result.instances_changed == 1
    assert "555-0162" not in str(dcmread(series / "b.dcm").ImageComments)
    assert dcmread(series / "b.dcm").ProtocolName == "CT HEAD"


def test_build_basic_text_sr_from_ocr_lines(tmp_path: Path) -> None:
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
    ds.Modality = "SC"
    ds.SeriesDescription = "Dose Report"
    ds.save_as(d / "x.dcm", enforce_file_format=True)
    assert classify_series(d) == SeriesKind.PIXEL_TEXT_REPORT


def test_cleansed_ocr_lines_blank_phi() -> None:
    from anonymizer.controller.ai.embedded_phi.report.report_from_ocr import cleansed_ocr_lines

    lines = cleansed_ocr_lines({1: ["Dose 12 mGy"], 0: [PHONE_TEXT]})
    assert "555-0162" not in " ".join(lines)
    assert any("Dose 12 mGy" in ln for ln in lines)


def test_dedupe_overlapping_hits_prefers_native() -> None:
    from anonymizer.controller.ai.embedded_phi.report.hits import ReportHit, dedupe_overlapping_hits

    native = ReportHit(
        page_index=0,
        text="FL HEALTH",
        label="LOCATION",
        rect=(10.0, 10.0, 80.0, 30.0),
        source="native",
        key="0:native:0:9:FL HEALTH",
    )
    ocr = ReportHit(
        page_index=0,
        text="FL HEALTH",
        label="NAME",
        rect=(12.0, 11.0, 78.0, 29.0),
        source="ocr",
        key="0:ocr:0:9:FL HEALTH",
    )
    distant = ReportHit(
        page_index=0,
        text="Molife",
        label="NAME",
        rect=(200.0, 400.0, 260.0, 420.0),
        source="ocr",
        key="0:ocr:10:16:Molife",
    )
    out = dedupe_overlapping_hits([ocr, native, distant])
    assert [h.key for h in out] == [native.key, distant.key]


def test_format_phi_xml_and_analyze_logs(caplog) -> None:
    import logging

    from anonymizer.controller.ai.embedded_phi.ner.phi_entity import Span
    from anonymizer.controller.ai.embedded_phi.report.report_ner import (
        analyze_report_text,
        format_phi_xml,
    )

    text = "Patient Jane Doe phone (404) 555-0162"
    spans = [
        Span("NAME", 8, 16, 0.9, "NAME"),
        Span("PHONE", 23, 37, 0.9, "PHONE"),
    ]
    tagged = format_phi_xml(text, spans)
    assert "<NAME>Jane Doe</NAME>" in tagged
    assert "<PHONE>(404) 555-0162</PHONE>" in tagged

    with (
        caplog.at_level(logging.INFO, logger="anonymizer.controller.ai.embedded_phi.report.report_ner"),
        patch(
            "anonymizer.controller.ai.embedded_phi.report.report_ner.detect_phi",
            return_value=spans,
        ),
    ):
        ents = analyze_report_text(text, unit="page=0")
    assert ents == spans
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "report_ner: in page=0" in joined
    assert text in joined
    assert "report_ner: out page=0" in joined
    assert "<NAME>Jane Doe</NAME>" in joined


def test_detect_pdf_hits_text_layer_only(caplog) -> None:
    """Layout → native NER only; no EasyOCR / embedded-image arm."""
    import logging

    from anonymizer.controller.ai.embedded_phi.ner.phi_entity import Span
    from anonymizer.controller.ai.embedded_phi.report import pdf_ocr as pdf_ocr_mod
    from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import PdfPageLayout

    layout = PdfPageLayout(
        page_index=0,
        width=595.0,
        height=842.0,
        text="Imaged At: Fl Health Patient: Anonymous",
        char_boxes=[(0.0, 0.0, 1.0, 1.0)] * len("Imaged At: Fl Health Patient: Anonymous"),
        images=[],
    )

    def fake_analyze(text: str, locale: str = "en_US", unit: str = "text"):
        needle = "Fl Health"
        start = text.index(needle)
        return [Span("LOCATION", start, start + len(needle), 0.9, "LOCATION")]

    progress_msgs: list[str] = []
    with (
        caplog.at_level(logging.INFO, logger="anonymizer.controller.ai.embedded_phi.report.pdf_ocr"),
        patch.object(pdf_ocr_mod, "extract_pdf_layout", return_value=[layout]),
        patch(
            "anonymizer.controller.ai.embedded_phi.report.pdf_ocr.analyze_report_text",
            side_effect=fake_analyze,
        ),
        patch(
            "anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf.rects_for_span",
            return_value=[(1.0, 1.0, 2.0, 2.0)],
        ),
    ):
        _layouts, hits = pdf_ocr_mod.detect_pdf_hits(
            b"%PDF", locale="en_US", progress=progress_msgs.append
        )
    assert progress_msgs
    assert all(h.source == "native" for h in hits)
    assert any(h.label == "LOCATION" and "Fl Health" in h.text for h in hits)
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "text-layer only" in joined
    assert "OCR" not in joined or "ignored" in joined.lower() or "text-layer" in joined


def test_preview_redacted_pdf_after_remove(tmp_path: Path) -> None:
    """Remove stashes paint rects; preview returns redacted bytes without writing DICOM."""
    from anonymizer.controller.ai.embedded_phi.report.hits import ReportHit
    from anonymizer.controller.ai.embedded_phi.report.report_session import ReportSession

    series = tmp_path / "pdfser"
    series.mkdir()
    pdf = render_plain_text_pdf("Patient Jane Doe phone (404) 555-0162")
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.104.1"
    ds.SOPInstanceUID = generate_uid()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.PatientID = "ANON1"
    ds.Modality = "DOC"
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    ds.EncapsulatedDocument = pdf if len(pdf) % 2 == 0 else pdf + b"\x00"
    ds.save_as(series / "r.dcm", enforce_file_format=True)

    session = ReportSession(series, "pdf")
    assert session.pdf_bytes()
    session.hits = [
        ReportHit(
            page_index=0,
            text="Jane Doe",
            label="NAME",
            rect=(40.0, 40.0, 120.0, 60.0),
            source="ocr",
            key="0:ocr:0:8:Jane Doe",
        )
    ]
    n = session.remove(mode="blank")
    assert n >= 1
    preview = session.preview_redacted_pdf()
    assert preview is not None and preview.startswith(b"%PDF")
    assert len(preview) > 100

