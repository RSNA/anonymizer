"""Native report text PHI for Structured Reports and Encapsulated PDF (DOC/PDF).
Modalities
----------
- **SR**: Modality == "SR" or SOPClassUID under 1.2.840.10008.5.1.4.1.1.88.*.

Public API
----------
METADATA_PHI_FIELDS
    Metadata phi fields.

METADATA_LABEL_SCORED_FAMILY
    Metadata label scored family.

BASIC_TEXT_SR_SOP_CLASS_UID
    Basic text sr sop class uid.

detect_phi_in_text(text: str, ds: Dataset, *, locale: str='en_US', phi_header: object | None=None, whitelist: Sequence[str] | None=None) -> list[Entity]
    Report View PHI pipeline on arbitrary unicode (source text unchanged).

detect_phi(ds: Dataset, *, locale: str='en_US', phi_header: object | None=None, whitelist: Sequence[str] | None=None) -> tuple[str, list[Entity]]
    Extract report unicode from ds and find PHI spans (text unchanged).

entities_from_study_phi(text: str, ds: Dataset, phi_header: object | None) -> list[Entity]
    Metadata PHI spans: original study/patient PHI strings found in report text.

merge_phi_entities(meta: Sequence[Entity], ner: Sequence[Entity]) -> tuple[list[Entity], int]
    Metadata spans win; keep NER spans that do not overlap them.

remove_phi(text: str, entities: Sequence[Entity], *, synthetic: bool=False) -> str
    Replace PHI spans in text (no Dataset I/O).

write_report_text(ds: Dataset, text: str) -> Dataset
    Persist cleansed report unicode for ML/labelling and de-identify ds.

render_pdf_pages(data: bytes, *, scale: float=1.5) -> list[Image.Image]
    Rasterize PDF bytes for Report View graphic preview.

extract_report_text(ds: Dataset) -> str
    Extract report unicode from ds without running NER.

build_basic_text_sr(source: Dataset, lines: Sequence[str], *, series_description: str='De-identified Report', series_number: int=9000) -> Dataset
    Return an (unsaved) Basic Text SR with one TEXT item per non-empty line.

encapsulated_pdf_bytes(ds: Dataset) -> bytes | None
    Return raw PDF bytes from EncapsulatedDocument, or None when absent / not a PDF.
"""
import datetime as _dt
import io
import logging
import re
from collections.abc import Iterator, Sequence

from PIL import Image
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.embedded_phi.classify_series import ENCAPSULATED_PDF_SOP_CLASS_UID, SR_SOP_CLASS_PREFIX
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity, detect_entities, replace_entities
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import collect_anonymized_values, mask_text_for_ner

try:
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None  # type: ignore[assignment]

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Minimum PHI needle length (avoid matching single-character sex / noise).
_MIN_PHI_NEEDLE = 2

# Original PHI header attr → DICOM keyword (entity.label) → scored color family.
# Entity.label is the DICOM keyword so UI/remove know which tag drove the hit.
METADATA_PHI_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("patient_id", "PatientID", "ID"),
    ("accession_number", "AccessionNumber", "ID"),
    ("patient_name", "PatientName", "FIRST_NAME"),
    ("study_date", "StudyDate", "DATE"),
    ("patient_birth_date", "PatientBirthDate", "DATE"),
)
METADATA_LABEL_SCORED_FAMILY: dict[str, str] = {
    dicom_kw.upper(): family for _, dicom_kw, family in METADATA_PHI_FIELDS
}

BASIC_TEXT_SR_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.88.11"

_INHERIT_KEYWORDS = (
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientSex",
    "StudyInstanceUID",
    "StudyDate",
    "StudyTime",
    "AccessionNumber",
    "ReferringPhysicianName",
    "StudyID",
    "StudyDescription",
)

# Join nonempty TEXT/PNAME slots. Prefer this over bare newlines when a slot may
# contain \\n; display/NER use the same string (compact: no blank slots).
_SLOT_SEP = "\x1e"

_TEXT_ATTRS = {"TEXT": "TextValue", "PNAME": "PersonName"}

_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_MARGIN = 50
_FONT_SIZE = 11
_LINE_HEIGHT = 14
_CHARS_PER_LINE = 90
_LINES_PER_PAGE = 48

_LABEL_VALUE = re.compile(r"^(.+?:)\s*$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_phi_in_text(
    text: str,
    ds: Dataset,
    *,
    locale: str = "en_US",
    phi_header: object | None = None,
    whitelist: Sequence[str] | None = None,
) -> list[Entity]:
    """
    Report View PHI pipeline on arbitrary unicode (source text unchanged).

    1. Metadata: match original PHI strings from phi_header; each hit is
       labeled with the DICOM keyword and carries replacement = anonymized
       value already on ds.
    2. Radiology pre-NER mask (anon surfaces / UIDs / compact dates / whitelist).
    3. NER on the masked unicode (same length → offsets still match text);
       spans overlapping metadata are dropped.
    """
    body = str(text or "")
    if not body.strip():
        return []
    meta_ents = entities_from_study_phi(body, ds, phi_header)
    anon_values = collect_anonymized_values(ds)
    masked = mask_text_for_ner(
        body,
        whitelist=whitelist or (),
        anon_values=anon_values,
        log_context="report",
    )
    ner_ents = detect_entities(masked.text, locale=locale)
    entities, ner_dropped = merge_phi_entities(meta_ents, ner_ents)
    logger.info(
        "report: detect_phi_in_text entities=%d "
        "(metadata=%d ner_kept=%d ner_dropped_overlap=%d masked=%d chars=%d)",
        len(entities),
        len(meta_ents),
        len(ner_ents) - ner_dropped,
        ner_dropped,
        len(masked.hits),
        len(body),
    )
    return entities


def detect_phi(
    ds: Dataset,
    *,
    locale: str = "en_US",
    phi_header: object | None = None,
    whitelist: Sequence[str] | None = None,
) -> tuple[str, list[Entity]]:
    """
    Extract report unicode from ds and find PHI spans (text unchanged).

    Delegates scoring to detect_phi_in_text (study-PHI match then filtered NER).

    SR: Modality SR or SOP Class 1.2.840.10008.5.1.4.1.1.88.*.
    DOC/PDF: Modality DOC|PDF or Encapsulated PDF SOP …104.1.

    Args:
        ds: DICOM dataset (SR or Encapsulated PDF / DOC); headers already anonymized.
        locale: NER locale pack (default en_US).
        phi_header: StudyPhiHeader (or duck-type) with original PHI field strings.
        whitelist: Optional radiology terms masked before NER.

    Returns:
        (text, entities) with entity offsets into text.

    Raises:
        ValueError: if ds is not an SR or DOC/PDF encapsulated report.
    """
    kind = _report_kind(ds)
    text = extract_report_text(ds)
    logger.info(
        "report: detect start kind=%s chars=%d phi_header=%s "
        "(metadata then filtered NER; text unchanged until remove)",
        kind,
        len(text),
        "yes" if phi_header is not None else "no",
    )
    if not text.strip():
        logger.warning(
            "report: detect skipped — empty extract (kind=%s SOPClassUID=%s)",
            kind,
            str(ds.get("SOPClassUID", "") or ""),
        )
        return text, []

    entities = detect_phi_in_text(
        text,
        ds,
        locale=locale,
        phi_header=phi_header,
        whitelist=whitelist,
    )
    logger.info(
        "report: detect done text_unchanged=1 entities=%d",
        len(entities),
    )
    return text, entities


def entities_from_study_phi(
    text: str,
    ds: Dataset,
    phi_header: object | None,
) -> list[Entity]:
    """
    Metadata PHI spans: original study/patient PHI strings found in report text.

    Entity.label is the DICOM keyword (PatientID, AccessionNumber, …).
    Entity.replacement is the anonymized value already on ds for that tag.
    """
    if phi_header is None:
        logger.info("report: metadata-phi skip — no phi_header")
        return []
    if not str(text or "").strip():
        logger.info("report: metadata-phi skip — empty text")
        return []

    # (needle, anon_replacement, dicom_keyword, scored_family)
    pairs: list[tuple[str, str, str, str]] = []
    for phi_attr, dicom_kw, family in METADATA_PHI_FIELDS:
        phi_val = str(getattr(phi_header, phi_attr, "") or "").strip()
        anon_val = str(ds.get(dicom_kw, "") or "").strip()
        if not phi_val or len(phi_val) < _MIN_PHI_NEEDLE:
            continue
        # Skip when PHI string already equals the anonymized tag (nothing to scrub).
        if anon_val and phi_val == anon_val:
            continue
        for needle in _phi_string_variants(phi_val, family=family):
            if len(needle) < _MIN_PHI_NEEDLE:
                continue
            if anon_val and needle == anon_val:
                continue
            pairs.append((needle, anon_val, dicom_kw, family))

    if not pairs:
        logger.info("report: metadata-phi no needles from phi_header")
        return []

    # Longest needles first so "DOE^JOHN" wins over "DOE".
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    accepted: list[Entity] = []
    occupied: list[tuple[int, int]] = []
    for needle, anon_val, dicom_kw, _family in pairs:
        for start, end in _find_all_spans(text, needle):
            if _spans_overlap(start, end, occupied):
                continue
            occupied.append((start, end))
            accepted.append(
                Entity(
                    label=dicom_kw,
                    start=start,
                    end=end,
                    score=1.0,
                    raw_label=f"METADATA_{dicom_kw}",
                    replacement=anon_val,
                )
            )
    accepted.sort(key=lambda e: (e.start, e.end))
    logger.info(
        "report: metadata-phi spans=%d needles=%d labels=%s",
        len(accepted),
        len(pairs),
        sorted({e.label for e in accepted}),
    )
    for ent in accepted:
        frag = text[ent.start : ent.end]
        logger.info(
            "report: metadata-phi hit label=%s [%d:%d] %r → replacement=%r",
            ent.label,
            ent.start,
            ent.end,
            frag,
            ent.replacement,
        )
    return accepted


def _phi_string_variants(value: str, *, family: str) -> list[str]:
    """Exact PHI string plus common PN / whitespace variants for report body match."""
    text = str(value or "").strip()
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def _add(candidate: str) -> None:
        c = candidate.strip()
        if len(c) < _MIN_PHI_NEEDLE or c in seen:
            return
        seen.add(c)
        out.append(c)

    _add(text)
    if family == "FIRST_NAME":
        # Person-name family (DICOM PN): Family^Given^Middle^Prefix^Suffix
        if "^" in text:
            parts = [p.strip() for p in text.split("^") if p.strip()]
            if parts:
                _add(" ".join(parts))
                _add(", ".join(parts[:2]) if len(parts) >= 2 else parts[0])
                if len(parts) >= 2:
                    _add(f"{parts[0]}, {parts[1]}")
                    _add(f"{parts[1]} {parts[0]}")
        elif "," in text:
            left, _, right = text.partition(",")
            family_name, given = left.strip(), right.strip()
            if family_name and given:
                _add(f"{family_name}^{given}")
                _add(f"{given} {family_name}")
    return out


def _find_all_spans(text: str, needle: str) -> list[tuple[int, int]]:
    """All non-overlapping? No — all occurrences; caller dedupes overlaps."""
    body = str(text or "")
    n = str(needle or "")
    if not body or not n:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        i = body.find(n, start)
        if i < 0:
            break
        spans.append((i, i + len(n)))
        start = i + max(1, len(n))
    if spans:
        return spans
    # Case-insensitive fallback (preserve source-slice length via matched span).
    lower_body = body.casefold()
    lower_needle = n.casefold()
    start = 0
    while True:
        i = lower_body.find(lower_needle, start)
        if i < 0:
            break
        spans.append((i, i + len(n)))
        start = i + max(1, len(n))
    return spans


def _spans_overlap(start: int, end: int, occupied: Sequence[tuple[int, int]]) -> bool:
    return any(start < b and end > a for a, b in occupied)


def merge_phi_entities(
    meta: Sequence[Entity], ner: Sequence[Entity]
) -> tuple[list[Entity], int]:
    """
    Metadata spans win; keep NER spans that do not overlap them.

    Returns:
        (merged_entities, ner_dropped_overlap_count).
    """
    occupied = [(e.start, e.end) for e in meta]
    merged = list(meta)
    dropped = 0
    for ent in ner:
        if _spans_overlap(ent.start, ent.end, occupied):
            dropped += 1
            logger.info(
                "report: detect drop NER label=%s [%d:%d] — overlaps metadata",
                ent.label,
                ent.start,
                ent.end,
            )
            continue
        occupied.append((ent.start, ent.end))
        merged.append(ent)
    merged.sort(key=lambda e: (e.start, e.end))
    return merged, dropped


# Back-compat alias
_merge_phi_entities = merge_phi_entities


def remove_phi(
    text: str,
    entities: Sequence[Entity],
    *,
    synthetic: bool = False,
) -> str:
    """
    Replace PHI spans in text (no Dataset I/O).

    Metadata entities (replacement set from detect) always write the
    anonymized DICOM value. NER entities blank or synthesize per synthetic.

    Args:
        text: Report unicode from detect_phi.
        entities: Spans with offsets into text (metadata + NER, merged).
        synthetic: If False, blank NER spans; if True, synthetic NER replacements.

    Returns:
        Cleaned unicode string.
    """
    mode = "synth" if synthetic else "blank"
    meta_n = sum(1 for e in entities if e.replacement is not None)
    ner_n = len(entities) - meta_n
    logger.info(
        "report: remove start synthetic=%s entities=%d "
        "(metadata→anon_dicom=%d ner=%d)",
        synthetic,
        len(entities),
        meta_n,
        ner_n,
    )
    cleaned, _used = replace_entities(text, entities, mode=mode)
    logger.info(
        "report: remove done synthetic=%s entities=%d chars %d→%d",
        synthetic,
        len(entities),
        len(text),
        len(cleaned),
    )
    return cleaned


def write_report_text(ds: Dataset, text: str) -> Dataset:
    """
    Persist cleansed report unicode for ML/labelling and de-identify ds.

    Primary deliverable: a Basic Text SR (SOP …88.11) with one TEXT
    content item per non-empty line. Caller saves that SR as a sibling series.

    Also mutates ds in place:
    - SR: write fragments back into TEXT/PNAME in ContentSequence walk order.
    - DOC/PDF: replace EncapsulatedDocument with a plain-text PDF of text
      (via _render_plain_text_pdf — text operators, not graphic preview).

    Args:
        ds: Source SR or DOC/PDF dataset (patient/study attrs inherited by the SR).
        text: Cleansed report unicode from remove_phi.

    Returns:
        Unsaved Basic Text SR dataset ready for save_as.

    Raises:
        ValueError: if ds is unsupported or SR slot count mismatches.
    """
    kind = _report_kind(ds)
    if kind == "sr":
        _write_sr_slots(ds, text)
    else:
        _write_pdf_bytes(ds, text)
    lines = [ln for ln in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]
    # Prefer slot fragments for SR so ML SR matches ContentSequence cells.
    if kind == "sr" and _SLOT_SEP in text:
        lines = [p for p in text.split(_SLOT_SEP) if str(p).strip()]
    sr = build_basic_text_sr(ds, lines, series_description="De-identified Report")
    logger.info(f"report: write kind={kind} ml_lines={len(lines)}")
    return sr


def render_pdf_pages(data: bytes, *, scale: float = 1.5) -> list[Image.Image]:
    """
    Rasterize PDF bytes for Report View graphic preview.

    This is display-only (pypdfium2 page bitmaps). It does **not** build or
    rewrite PDF text; DOC/PDF de-id write-back uses _render_plain_text_pdf.

    Args:
        data: Raw PDF bytes from EncapsulatedDocument.
        scale: Render scale (default 1.5).

    Returns:
        One PIL image per page, or empty list if unusable.
    """
    if pdfium is None:  # pragma: no cover
        logger.warning("report: pypdfium2 not installed; PDF page render skipped")
        return []
    try:
        doc = pdfium.PdfDocument(data)
        pages: list[Image.Image] = []
        for i in range(len(doc)):
            page = doc[i]
            bitmap = page.render(scale=scale)
            pages.append(bitmap.to_pil())
        return pages
    except Exception:  # noqa: BLE001
        logger.exception("report: page render failed")
        return []


def extract_report_text(ds: Dataset) -> str:
    """
    Extract report unicode from ds without running NER.

    SR: Modality SR or SOP Class 1.2.840.10008.5.1.4.1.1.88.* —
    TEXT/PNAME ContentSequence values joined with a private slot separator.
    DOC/PDF: Modality DOC|PDF or Encapsulated PDF SOP …104.1 —
    EncapsulatedDocument PDF text layer (empty when raster-only / no text layer).

    Args:
        ds: DICOM dataset (SR or Encapsulated PDF / DOC).

    Returns:
        Report unicode (may be empty).

    Raises:
        ValueError: if ds is not an SR or DOC/PDF encapsulated report.
    """
    kind = _report_kind(ds)
    if kind == "sr":
        return _extract_sr_text(ds)
    return _extract_pdf_text_from_ds(ds)


def build_basic_text_sr(
    source: Dataset,
    lines: Sequence[str],
    *,
    series_description: str = "De-identified Report",
    series_number: int = 9000,
) -> Dataset:
    """
    Return an (unsaved) Basic Text SR with one TEXT item per non-empty line.

    Args:
        source: Dataset whose patient/study attributes are copied onto the SR.
        lines: Report lines (empty strings skipped).
        series_description: SeriesDescription for the new SR series.
        series_number: SeriesNumber for the new SR series.

    Returns:
        Unsaved Basic Text SR dataset (SOP …88.11).
    """
    sr = Dataset()
    sr.file_meta = FileMetaDataset()
    sr.file_meta.MediaStorageSOPClassUID = BASIC_TEXT_SR_SOP_CLASS_UID
    sr.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    sr.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    sr.file_meta.ImplementationClassUID = generate_uid()

    for kw in _INHERIT_KEYWORDS:
        if kw in source:
            setattr(sr, kw, source[kw].value)
    sr.SOPClassUID = BASIC_TEXT_SR_SOP_CLASS_UID
    sr.SOPInstanceUID = sr.file_meta.MediaStorageSOPInstanceUID
    sr.SeriesInstanceUID = generate_uid()
    sr.Modality = "SR"
    sr.SeriesDescription = series_description
    sr.SeriesNumber = series_number
    sr.InstanceNumber = 1
    now = _dt.datetime.now()
    sr.ContentDate = now.strftime("%Y%m%d")
    sr.ContentTime = now.strftime("%H%M%S")
    sr.CompletionFlag = "PARTIAL"
    sr.VerificationFlag = "UNVERIFIED"
    sr.ValueType = "CONTAINER"
    sr.ConceptNameCodeSequence = DicomSequence([_code("11528-7", "LN", "Radiology Report")])
    sr.ContinuityOfContent = "SEPARATE"
    items = []
    for line in lines:
        body = str(line).strip()
        if not body:
            continue
        item = Dataset()
        item.RelationshipType = "CONTAINS"
        item.ValueType = "TEXT"
        item.ConceptNameCodeSequence = DicomSequence([_code("121071", "DCM", "Finding")])
        item.TextValue = body
        items.append(item)
    sr.ContentSequence = DicomSequence(items)
    return sr


def encapsulated_pdf_bytes(ds: Dataset) -> bytes | None:
    """
    Return raw PDF bytes from EncapsulatedDocument, or None when absent / not a PDF.

    Args:
        ds: DICOM dataset that may carry an Encapsulated Document.

    Returns:
        PDF bytes with trailing null pad stripped, or None.
    """
    blob = ds.get("EncapsulatedDocument")
    if not blob:
        return None
    if str(ds.get("MIMETypeOfEncapsulatedDocument", "application/pdf")).lower() != "application/pdf":
        return None
    return bytes(blob).rstrip(b"\x00")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _code(value: str, scheme: str, meaning: str) -> Dataset:
    """
    Build a minimal DICOM coded-concept sequence item.

    Args:
        value: Code value.
        scheme: Coding scheme designator.
        meaning: Code meaning.

    Returns:
        Dataset with CodeValue / CodingSchemeDesignator / CodeMeaning.
    """
    item = Dataset()
    item.CodeValue = value
    item.CodingSchemeDesignator = scheme
    item.CodeMeaning = meaning
    return item


def _report_kind(ds: Dataset) -> str:
    """
    Classify ds as "sr" or "pdf".

    Args:
        ds: DICOM dataset.

    Returns:
        "sr" or "pdf".

    Raises:
        ValueError: if the dataset is not a supported report modality.
    """
    mod = str(ds.get("Modality", "") or "").strip().upper()
    sop = str(ds.get("SOPClassUID", "") or "")
    if sop.startswith(SR_SOP_CLASS_PREFIX) or mod == "SR":
        return "sr"
    if sop == ENCAPSULATED_PDF_SOP_CLASS_UID or mod in {"DOC", "PDF"}:
        return "pdf"
    raise ValueError(f"Unsupported report dataset: Modality={mod!r} SOPClassUID={sop!r}")


def _sr_slot_attr(item: Dataset) -> str | None:
    """
    Return the text slot attribute on an SR content item, if any.

    Prefer ValueType TEXT/PNAME. When ValueType was stripped at ingest
    (legacy Basic/Retain @remove on 0040,A040) but TextValue or
    PersonName remains, fall back to that attribute so extract still works.

    Args:
        item: One ContentSequence content item.

    Returns:
        "TextValue", "PersonName", or None.
    """
    vt = str(item.get("ValueType", "") or "").strip().upper()
    if vt in _TEXT_ATTRS:
        attr = _TEXT_ATTRS[vt]
        return attr if attr in item else None
    if "TextValue" in item:
        return "TextValue"
    if "PersonName" in item:
        return "PersonName"
    return None


def _iter_sr_text_items(ds: Dataset) -> Iterator[tuple[Dataset, str]]:
    """
    Yield (item, attr_name) for each TEXT/PNAME content item (depth-first).

    Args:
        ds: SR dataset (root may hold ContentSequence or be a CONTAINER).

    Yields:
        Pairs of content-item dataset and attribute name (TextValue or PersonName).
    """

    def _walk(container: Dataset) -> Iterator[tuple[Dataset, str]]:
        """
        Recurse into ContentSequence of container.

        Args:
            container: Dataset that may hold nested ContentSequence.

        Yields:
            (item, attr_name) for each TEXT/PNAME content item.
        """
        for item in container.get("ContentSequence", []) or []:
            attr = _sr_slot_attr(item)
            if attr is not None:
                yield item, attr
            yield from _walk(item)

    yield from _walk(ds)


def _normalize_sr_slot_text(raw: str) -> str:
    """
    Normalize one SR text slot for display / NER / write-back.

    Collapses \\r\\n / \\r to \\n (dose Comment tables often use CR/LF)
    and strips outer whitespace.
    """
    body = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    # Drop empty lines inside a multi-line slot (compact tables).
    if "\n" in body:
        body = "\n".join(ln.strip() for ln in body.split("\n") if ln.strip())
    return body


def _sr_slot_is_unique_keep(value: str) -> bool:
    """True when value must always appear even if seen before (tables / prose)."""
    if "|" in value or "\n" in value:
        return True
    return len(value) > 80


def _sr_compact_slot_plan(
    ds: Dataset,
) -> tuple[list[tuple[Dataset, str]], list[str], list[int]]:
    """
    Build a compact SR text plan: dedupe repeated short values (dose events).

    Radiation Dose SRs repeat Device Manufacturer / Model / Serial and Acquisition
    Protocol once per irradiation event. Compact extract keeps the first occurrence
    of each distinct short value; multi-line / pipe tables are always kept.
    Write-back remaps each original nonempty slot to its compact index so clearing
    a duplicated serial still clears every event copy.

    Args:
        ds: SR dataset.

    Returns:
        (nonempty_items, compact_values, item_to_compact_index).
    """
    items: list[tuple[Dataset, str]] = []
    compact: list[str] = []
    item_to_compact: list[int] = []
    value_to_idx: dict[str, int] = {}
    for item, attr in _iter_sr_text_items(ds):
        val = _normalize_sr_slot_text(str(item.get(attr, "") or ""))
        if not val:
            continue
        items.append((item, attr))
        if _sr_slot_is_unique_keep(val) or val not in value_to_idx:
            idx = len(compact)
            compact.append(val)
            if not _sr_slot_is_unique_keep(val):
                value_to_idx[val] = idx
            item_to_compact.append(idx)
        else:
            item_to_compact.append(value_to_idx[val])
    return items, compact, item_to_compact


def _join_sr_compact_parts(parts: list[str]) -> str:
    """Join compact parts; use _SLOT_SEP when any part embeds newlines."""
    if not parts:
        return ""
    if any("\n" in p for p in parts):
        return _SLOT_SEP.join(parts)
    return "\n".join(parts)


def _split_sr_compact_text(text: str, *, compact_count: int) -> list[str]:
    """Split cleansed extract back into compact_count fragments."""
    if compact_count <= 0:
        return []
    if _SLOT_SEP in text:
        parts = text.split(_SLOT_SEP)
    elif compact_count == 1:
        parts = [text]
    else:
        parts = text.split("\n")
    return parts


def _extract_sr_text(ds: Dataset) -> str:
    """
    Join TEXT/PNAME values from ContentSequence into compact report unicode.

    Args:
        ds: SR dataset.

    Returns:
        Joined unicode report text (may be empty). Blank slots omitted; short
        duplicate values collapsed (dose-event device/protocol repeats).
    """
    all_items = list(_iter_sr_text_items(ds))
    vt_missing = sum(
        1 for item, _attr in all_items if not str(item.get("ValueType", "") or "").strip()
    )
    items, compact, _map = _sr_compact_slot_plan(ds)
    logger.info(
        "report: extract kind=sr slots=%d nonempty=%d compact=%d value_type_missing=%d chars=%d",
        len(all_items),
        len(items),
        len(compact),
        vt_missing,
        sum(len(p) for p in compact),
    )
    if not all_items:
        logger.warning(
            "report: extract kind=sr empty — no TextValue/PersonName content items "
            "(SOPClassUID=%s). Dose/CAD SRs may be mostly NUM/CODE; check ingest kept "
            "ValueType/TextValue.",
            str(ds.get("SOPClassUID", "") or ""),
        )
    elif not items:
        logger.warning(
            "report: extract kind=sr all %d slot(s) blank (ValueType missing on %d)",
            len(all_items),
            vt_missing,
        )
    else:
        if vt_missing:
            logger.info(
                "report: extract kind=sr recovered slots via TextValue/PersonName "
                "fallback (ValueType stripped at ingest)"
            )
        if len(compact) < len(items):
            logger.info(
                "report: extract kind=sr deduped %d → %d unique short values",
                len(items),
                len(compact),
            )
    return _join_sr_compact_parts(compact)


def _write_sr_slots(ds: Dataset, text: str) -> None:
    """
    Write cleansed compact extract back into nonempty TEXT/PNAME items.

    Compact indices are expanded so every original slot that shared a short value
    receives the same replacement (dose-event duplicates stay in sync).

    Args:
        ds: SR dataset mutated in place.
        text: Cleansed unicode from extract (\\n- or _SLOT_SEP-joined).

    Raises:
        ValueError: if fragment count does not match the compact plan.
    """
    items, compact, item_to_compact = _sr_compact_slot_plan(ds)
    parts = _split_sr_compact_text(text, compact_count=len(compact))
    if len(parts) != len(compact):
        raise ValueError(
            f"SR slot count mismatch: text parts={len(parts)} compact_slots={len(compact)}"
        )
    for (item, attr), cidx in zip(items, item_to_compact, strict=True):
        setattr(item, attr, parts[cidx])


def _format_extracted_pdf_text(raw: str) -> str:
    """
    Normalize pypdf layout extract into readable paragraphs for display and NER.

    Args:
        raw: Raw text from pypdf page extraction.

    Returns:
        Normalized unicode (may be empty).
    """
    if not raw or not raw.strip():
        return ""
    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        cleaned = re.sub(r"\s+:", ":", cleaned)
        lines.append(cleaned)

    paired: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line and _LABEL_VALUE.match(line) and nxt and not _LABEL_VALUE.match(nxt):
            paired.append(f"{line} {nxt}")
            i += 2
            continue
        paired.append(line)
        i += 1

    out: list[str] = []
    blank = False
    for line in paired:
        if not line:
            blank = True
            continue
        if out and blank:
            out.append("")
        blank = False
        out.append(line)
    return "\n".join(out).strip()


def _extract_pdf_text_from_bytes(data: bytes) -> str:
    """
    Extract unicode text layer from PDF bytes (empty when raster-only).

    Args:
        data: Raw PDF bytes.

    Returns:
        Normalized text layer, or "" if none / unreadable.
    """
    if PdfReader is None:  # pragma: no cover
        logger.warning("report: pypdf not installed; PDF text extraction skipped")
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception:  # noqa: BLE001
        logger.exception("report: text extraction failed")
        return ""
    raw = "\n\n".join(p.strip() for p in pages if p.strip())
    return _format_extracted_pdf_text(raw)


def _extract_pdf_text_from_ds(ds: Dataset) -> str:
    """
    Extract EncapsulatedDocument PDF text layer from ds.

    Args:
        ds: DOC/PDF dataset.

    Returns:
        Text layer unicode, or "" when absent / raster-only.
    """
    data = encapsulated_pdf_bytes(ds)
    if not data:
        return ""
    return _extract_pdf_text_from_bytes(data)


def _pdf_escape(text: str) -> str:
    """
    Escape parentheses and backslashes for a PDF literal string.

    Args:
        text: Latin-1-safe line content.

    Returns:
        Escaped string for Tj.
    """
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_lines(text: str) -> list[str]:
    """
    Wrap text into fixed-width lines for the plain-text PDF builder.

    Args:
        text: Full report unicode.

    Returns:
        List of lines (at least one).
    """
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        while len(paragraph) > _CHARS_PER_LINE:
            cut = paragraph.rfind(" ", 0, _CHARS_PER_LINE)
            if cut < _CHARS_PER_LINE // 2:
                cut = _CHARS_PER_LINE
            lines.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        lines.append(paragraph)
    return lines or [""]


def _render_plain_text_pdf(text: str) -> bytes:
    """
    Build a minimal single-font PDF from text (text operators, not images).

    Used only by write_report_text to de-id DOC/PDF EncapsulatedDocument.
    Not a graphic preview — use render_pdf_pages for display rasters.

    Args:
        text: Unicode to embed (non–Latin-1 glyphs replaced).

    Returns:
        PDF-1.4 bytes with extractable Tj text.
    """
    lines = _wrap_lines(text)
    pages: list[list[str]] = []
    for i in range(0, max(len(lines), 1), _LINES_PER_PAGE):
        pages.append(lines[i : i + _LINES_PER_PAGE])

    objects: list[bytes] = []

    def add_obj(body: bytes) -> int:
        """
        Append a PDF object body and return its 1-based object number.

        Args:
            body: Raw PDF object contents (without obj/endobj wrappers).

        Returns:
            1-based object id for cross-references.
        """
        objects.append(body)
        return len(objects)

    font_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    page_ids: list[int] = []
    for page_lines in pages:
        y = _PAGE_HEIGHT - _MARGIN
        content_parts = [f"BT /F1 {_FONT_SIZE} Tf {_MARGIN} {y} Td"]
        first = True
        for line in page_lines:
            if not first:
                content_parts.append(f"0 -{_LINE_HEIGHT} Td")
            first = False
            safe = _pdf_escape(line.encode("latin-1", errors="replace").decode("latin-1"))
            content_parts.append(f"({safe}) Tj")
        content_parts.append("ET")
        stream = "\n".join(content_parts).encode("latin-1")
        content_id = add_obj(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")
        page_id = add_obj(
            (
                f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] "
                f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            ).encode("ascii")
        )
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_id = add_obj(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii"))
    parent_pat = re.compile(rb"/Parent 0 0 R")
    for pid in page_ids:
        objects[pid - 1] = parent_pat.sub(f"/Parent {pages_id} 0 R".encode("ascii"), objects[pid - 1])
    catalog_id = add_obj(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


def _write_pdf_bytes(ds: Dataset, text: str) -> None:
    """
    Replace EncapsulatedDocument with a plain-text PDF of text.

    Args:
        ds: DOC/PDF dataset mutated in place.
        text: Cleansed report unicode.
    """
    pdf_bytes = _render_plain_text_pdf(text)
    if len(pdf_bytes) % 2:
        pdf_bytes += b"\x00"
    ds.EncapsulatedDocument = pdf_bytes
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
