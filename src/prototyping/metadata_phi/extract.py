"""Extract free-text chunks from DICOM metadata, SR content, and encapsulated PDF."""

import io
from collections.abc import Iterable, Iterator
from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from prototyping.metadata_phi.types import TextChunk

# DICOM UID attributes — not free-text PHI carriers; do not scan with date/phone NER.
UID_METADATA_TAGS = frozenset(
    {
        "SOPInstanceUID",
        "SOPClassUID",
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "FrameOfReferenceUID",
        "SynchronizationFrameOfReferenceUID",
        "MediaStorageSOPInstanceUID",
        "MediaStorageSOPClassUID",
        "ImplementationClassUID",
        "TransferSyntaxUID",
        "ReferencedSOPInstanceUID",
        "ReferencedSOPClassUID",
        "PaletteColorLookupTableUID",
    }
)


def is_uid_metadata_tag(tag_or_path: str) -> bool:
    """True for UID tags or paths that end with a UID attribute."""
    if not tag_or_path:
        return False
    leaf = tag_or_path.rsplit(".", 1)[-1]
    if leaf in UID_METADATA_TAGS:
        return True
    return any(tag_or_path.endswith(name) for name in UID_METADATA_TAGS)


# Common LO/LT/SH/ST tags that often carry reviewable free text.
_FLAT_TEXT_TAGS: tuple[str, ...] = (
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientComments",
    "OtherPatientIDs",
    "OtherPatientNames",
    "StudyDescription",
    "SeriesDescription",
    "ProtocolName",
    "RequestedProcedureDescription",
    "PerformedProcedureStepDescription",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "ReferringPhysicianName",
    "ReferringPhysicianAddress",
    "PerformingPhysicianName",
    "OperatorsName",
    "RequestingPhysician",
    "AdmissionID",
    "AccessionNumber",
    "StudyID",
    "ImageComments",
)


def _as_str(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _walk_content_sequence(seq: Sequence, prefix: str = "ContentSequence") -> Iterator[tuple[str, str]]:
    for i, item in enumerate(seq):
        path = f"{prefix}[{i}]"
        if not isinstance(item, Dataset):
            continue
        for attr in ("TextValue", "PersonName", "PersonNameValue"):
            if hasattr(item, attr):
                text = _as_str(getattr(item, attr))
                if text:
                    yield f"{path}.{attr}", text
        if hasattr(item, "ConceptNameCodeSequence"):
            for j, code in enumerate(item.ConceptNameCodeSequence):
                meaning = _as_str(getattr(code, "CodeMeaning", ""))
                if meaning:
                    yield f"{path}.ConceptNameCodeSequence[{j}].CodeMeaning", meaning
        if hasattr(item, "ContentSequence"):
            yield from _walk_content_sequence(item.ContentSequence, f"{path}.ContentSequence")


def pdf_text_from_dataset(ds: Dataset) -> str:
    raw = getattr(ds, "EncapsulatedDocument", None)
    if raw is None:
        return ""
    data = bytes(raw) if not isinstance(raw, (bytes, bytearray)) else bytes(raw)
    if not data:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        # Fallback: best-effort ASCII extract from PDF bytes.
        ascii_parts = []
        for chunk in data.split(b"("):
            if b")" in chunk:
                frag = chunk.split(b")", 1)[0]
                try:
                    s = frag.decode("latin-1", errors="ignore")
                except Exception:
                    continue
                if s.isprintable() and len(s) >= 3:
                    ascii_parts.append(s)
        return "\n".join(ascii_parts)

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages).strip()


def extract_from_dataset(ds: Dataset, *, path: str = "", locale: str = "en_US") -> list[TextChunk]:
    sop = _as_str(getattr(ds, "SOPInstanceUID", ""))
    chunks: list[TextChunk] = []

    for tag in _FLAT_TEXT_TAGS:
        if hasattr(ds, tag):
            text = _as_str(getattr(ds, tag))
            if text:
                chunks.append(
                    TextChunk(text=text, path=path, sop_uid=sop, tag_or_path=tag, locale=locale)
                )

    if hasattr(ds, "ContentSequence"):
        for tag_path, text in _walk_content_sequence(ds.ContentSequence):
            chunks.append(
                TextChunk(text=text, path=path, sop_uid=sop, tag_or_path=tag_path, locale=locale)
            )

    if getattr(ds, "Modality", "") == "DOC" or hasattr(ds, "EncapsulatedDocument"):
        pdf = pdf_text_from_dataset(ds)
        if pdf:
            chunks.append(
                TextChunk(
                    text=pdf,
                    path=path,
                    sop_uid=sop,
                    tag_or_path="EncapsulatedDocument",
                    locale=locale,
                )
            )

    return chunks


def extract_from_file(path: str | Path, *, locale: str = "en_US") -> list[TextChunk]:
    path = Path(path)
    ds = dcmread(str(path), force=True)
    return extract_from_dataset(ds, path=str(path), locale=locale)


def extract_from_paths(paths: Iterable[str | Path], *, locale: str = "en_US") -> list[TextChunk]:
    out: list[TextChunk] = []
    for p in paths:
        out.extend(extract_from_file(p, locale=locale))
    return out
