"""Keep-and-scrub helpers for free-text PHI (experiment / prototyping only).

Does not change the product default anonymizer script. Callers must opt in.
"""

from __future__ import annotations

import io
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from prototyping.metadata_phi.extract import is_uid_metadata_tag, pdf_text_from_dataset
from prototyping.metadata_phi.pipeline import analyze_text
from prototyping.metadata_phi.types import Span

_REDACT = "[REDACTED]"


def text_pdf_bytes(text: str) -> bytes:
    """Minimal one-page PDF carrying ``text`` (ASCII-safe multi-line stream)."""
    lines = text.split("\n") if "\n" in text else [text[i : i + 90] for i in range(0, len(text), 90)]
    content_lines = ["BT /F1 10 Tf 50 750 Td"]
    for i, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if i == 0:
            content_lines.append(f"({escaped}) Tj")
        else:
            content_lines.append(f"0 -14 Td ({escaped}) Tj")
    content_lines.append("ET\n")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objects = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        (
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
        ),
        (
            f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
            + stream
            + b"endstream\nendobj\n"
        ),
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.1\n")
    offsets = [0]
    for obj in objects:
        offsets.append(out.tell())
        out.write(obj)
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))
    out.write(
        f"trailer<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return out.getvalue()


def scrub_text(
    text: str,
    *,
    engine: str = "presidio_transformers",
    locale: str = "en_US",
    apply_guard: bool = True,
    replacement: str = _REDACT,
) -> tuple[str, list[Span]]:
    """Replace detected PHI spans in ``text`` (right-to-left so offsets stay valid)."""
    spans = analyze_text(
        text, engine=engine, locale=locale, apply_guard=apply_guard
    )
    if not spans:
        return text, []
    ordered = sorted(spans, key=lambda s: (s.start, s.end), reverse=True)
    out = text
    for s in ordered:
        out = out[: s.start] + replacement + out[s.end :]
    return out, spans


def _scrub_content_sequence(
    seq: Sequence,
    *,
    engine: str,
    locale: str,
    apply_guard: bool,
    replacement: str,
) -> int:
    n = 0
    for item in seq:
        if not isinstance(item, Dataset):
            continue
        for attr in ("TextValue", "PersonName", "PersonNameValue"):
            if hasattr(item, attr):
                raw = str(getattr(item, attr) or "")
                if not raw.strip():
                    continue
                scrubbed, spans = scrub_text(
                    raw,
                    engine=engine,
                    locale=locale,
                    apply_guard=apply_guard,
                    replacement=replacement,
                )
                if spans:
                    setattr(item, attr, scrubbed)
                    n += len(spans)
        if hasattr(item, "ContentSequence"):
            n += _scrub_content_sequence(
                item.ContentSequence,
                engine=engine,
                locale=locale,
                apply_guard=apply_guard,
                replacement=replacement,
            )
    return n


def scrub_dicom_file(
    path: str | Path,
    out_path: str | Path,
    *,
    engine: str = "presidio_transformers",
    locale: str = "en_US",
    apply_guard: bool = True,
    replacement: str = _REDACT,
) -> dict:
    """
    Read a DICOM file, scrub free-text PHI in flat tags + SR ContentSequence,
    write ``out_path``. UID tags are left unchanged.
    """
    path = Path(path)
    out_path = Path(out_path)
    ds = dcmread(str(path), force=True)
    n_spans = 0
    flat_tags = (
        "PatientName",
        "PatientID",
        "PatientAddress",
        "PatientTelephoneNumbers",
        "PatientComments",
        "OtherPatientNames",
        "StudyDescription",
        "SeriesDescription",
        "InstitutionName",
        "InstitutionAddress",
        "ReferringPhysicianName",
        "ReferringPhysicianAddress",
        "PerformingPhysicianName",
        "OperatorsName",
        "RequestingPhysician",
        "ImageComments",
        "AdditionalPatientHistory",
    )
    for tag in flat_tags:
        if is_uid_metadata_tag(tag) or not hasattr(ds, tag):
            continue
        raw = str(getattr(ds, tag) or "").strip()
        if not raw:
            continue
        scrubbed, spans = scrub_text(
            raw,
            engine=engine,
            locale=locale,
            apply_guard=apply_guard,
            replacement=replacement,
        )
        if spans:
            setattr(ds, tag, scrubbed)
            n_spans += len(spans)

    if hasattr(ds, "ContentSequence"):
        n_spans += _scrub_content_sequence(
            ds.ContentSequence,
            engine=engine,
            locale=locale,
            apply_guard=apply_guard,
            replacement=replacement,
        )

    if hasattr(ds, "EncapsulatedDocument"):
        pdf_text = pdf_text_from_dataset(ds)
        if pdf_text.strip():
            scrubbed, spans = scrub_text(
                pdf_text,
                engine=engine,
                locale=locale,
                apply_guard=apply_guard,
                replacement=replacement,
            )
            if spans:
                ds.EncapsulatedDocument = text_pdf_bytes(scrubbed)
                n_spans += len(spans)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(out_path), enforce_file_format=True)
    return {"input": str(path), "output": str(out_path), "spans_redacted": n_spans}
