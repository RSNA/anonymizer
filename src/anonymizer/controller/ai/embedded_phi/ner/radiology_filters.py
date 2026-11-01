"""Pre-NER / post-NER text helpers (Metadata / Report).

Clean Descriptors metadata detect no longer uses prepare_metadata_ner_segments.
That path is frozen in metadata/ner_compile.py (alnum-only concat + offset map);
whitelist, date fill, and for/caret expand run only after OpenMed.

Still used:

* **Report body** — mask_text_for_ner: same-length mask of anon surfaces,
  UIDs, dates/clock-times, whitelist terms (report path only).
* **Post-NER** — date_time_pattern_entities, collect_anonymized_values,
  MetadataNerItem.
* **Legacy prepare_metadata_ner_segments** — kept for unit tests / older
  callers; not the Clean Descriptors detect path.

Public API
----------
DEFAULT_WHITELIST_SIMILARITY
    Default whitelist similarity (0.85).

DEFAULT_WHITELIST_MIN_LENGTH_RATIO
    Default whitelist min length ratio (0.7).

FilterHit
    One term/span removed or skipped before NER.

MaskResult
    Report-body mask: same-length unicode + audit hits.

MetadataNerItem
    One metadata Content cell considered for NER.

PreparedMetadataSegment
    Cell kept for NER, wrapped for clinical-report-style context.

collect_anonymized_values(ds: Dataset, *, extra: Iterable[str] | None=None) -> frozenset[str]
    Anonymized header strings already on ds (plus optional extras).

is_anon_identity_tag(*, tag_path: str='', tag: str='', field_name: str='') -> bool
    True for Patient ID / Patient Name / Accession / Study ID / birth-date tags
    that Clean Descriptors must never rewrite.

mask_text_for_ner(text: str, *, whitelist: Sequence[str]=(), anon_values: Set[str] | None=None, similarity: float=DEFAULT_WHITELIST_SIMILARITY, min_length_ratio: float=..., mask_uids: bool=True, mask_dates: bool=True, mask_times: bool=True, log_context: str='report') -> MaskResult
    Same-length mask of anon surfaces and optional UID / date / time / whitelist spans.

prepare_metadata_ner_segments(items: Sequence[MetadataNerItem], *, whitelist: Sequence[str]=(), anon_values: Set[str] | None=None, similarity: float=DEFAULT_WHITELIST_SIMILARITY, min_length_ratio: float=..., log_context: str='metadata') -> list[PreparedMetadataSegment]
    Filter/wrap cells for NER; IS/DS keep full text; CS via digits_only.

remap_ner_entities_to_original(entities: Sequence[Entity], prepared: PreparedMetadataSegment) -> list[Entity]
    Keep NER spans fully inside the value region; remap to original_text.

date_time_pattern_entities(text: str) -> list[Entity]
    DATE entities for compact DA / TM / colon clock times in text (OpenMed gap-fill).

is_dicom_uid_text(text: str) -> bool
    True when text is (or is only) a DICOM UID.

is_compact_dicom_datetime(text: str) -> bool
    True for compact DA (YYYYMMDD) or TM (HHMMSS[.frac]) only.

wrap_field_for_ner(field_name: str, value: str) -> tuple[str, int, int]
    Wrap a metadata cell as Field Name: value. for OpenMed chunk context.

caret_to_space_for_ner(text: str) -> str
    Same-length PersonName caret (^) → space so NER sees prose, not PN syntax.
"""
import logging
import re
from collections.abc import Iterable, Sequence, Set
from dataclasses import dataclass

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    DATE_VRS,
    DIGITS_ONLY_VRS,
    INTEGER_AND_CODE_STRING_VRS,
    SKIP_TEXT_KEYWORDS,
    TEXT_VRS,
    digits_only,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.term_similarity import similarity_term_match
from anonymizer.controller.script.operands import is_safe_operation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Default similarity (aligned with OCR modality whitelist STANDARD preset).
DEFAULT_WHITELIST_SIMILARITY = 0.85
DEFAULT_WHITELIST_MIN_LENGTH_RATIO = 0.7

# DICOM keywords whose current (anonymized) values must not be re-scored by NER
# and must never be rewritten by Clean Descriptors.
_ANON_SURFACE_KEYWORDS = (
    "PatientName",
    "PatientID",
    "AccessionNumber",
    "StudyDate",
    "PatientBirthDate",
    "StudyID",
)
_ANON_IDENTITY_TAG_HEX = frozenset(
    {
        "00100010",  # PatientName
        "00100020",  # PatientID
        "00080050",  # AccessionNumber
        "00080020",  # StudyDate
        "00100030",  # PatientBirthDate
        "00200010",  # StudyID
    }
)

# VRs that never carry clinical free-text PHI for NER.
# IS/DS/CS are descriptor carriers (see INTEGER_AND_CODE_STRING_VRS) — not listed here.
_NON_PROSE_VR_CORE = frozenset(
    {
        "UI",
        "US",
        "SS",
        "UL",
        "SL",
        "FL",
        "FD",
        "AT",
        "OB",
        "OW",
        "OF",
        "OD",
        "OL",
        "OV",
        "UN",
        "SQ",
    }
)

_UID_RE = re.compile(
    r"\b(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){3,}\b"
)
_COMPACT_DATE_RE = re.compile(r"\b(?:19|20)\d{6}\b")
# Compact TM (HHMMSS[.frac]). Do not start after '.' — fractional digits of a
# decimal measurement (e.g. 0.096000) are not DICOM times.
_COMPACT_TIME_RE = re.compile(r"(?<!\.)\b\d{6}(?:\.\d{1,6})?\b")
# Decimal measurements kept out of compact-TM DATE fill / time masks
# (e.g. Attenuation Correction Method "0.096000 cm-1").
_DECIMAL_FLOAT_RE = re.compile(r"\b\d+\.\d+\b")
# Colon clock times (HH:MM[:SS[.frac]] [AM/PM]) — masked before NER so a
# model date_time span can only cover the date component we focus on.
_COLON_TIME_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?"
    r"(?:\s*[AaPp]\.?[Mm]\.?)?\b"
)
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'._/-]*")


@dataclass(frozen=True)
class FilterHit:
    """One term/span removed or skipped before NER."""

    reason: str
    text: str
    detail: str = ""


@dataclass(frozen=True)
class MaskResult:
    """Report-body mask: same-length unicode + audit hits."""

    text: str
    hits: tuple[FilterHit, ...]


@dataclass(frozen=True)
class MetadataNerItem:
    """One metadata Content cell considered for NER."""

    text: str
    field_name: str = ""
    tag: str = ""
    vr: str = ""
    tag_path: str = ""
    is_anonymizer_field: bool = False
    is_date: bool = False
    script_operation: str = ""


@dataclass(frozen=True)
class PreparedMetadataSegment:
    """Cell kept for NER, wrapped for clinical-report-style context."""

    original_text: str
    ner_text: str
    value_start: int
    value_end: int
    field_name: str = ""


def collect_anonymized_values(
    ds: Dataset,
    *,
    extra: Iterable[str] | None = None,
) -> frozenset[str]:
    """
    Anonymized header strings already on ds (plus optional extras).

    These must not be fed to NER as if they were residual PHI.
    """
    values: set[str] = set()
    for kw in _ANON_SURFACE_KEYWORDS:
        raw = str(ds.get(kw, "") or "").strip()
        if raw:
            values.add(raw)
    for item in extra or ():
        text = str(item or "").strip()
        if text:
            values.add(text)
    return frozenset(values)


def is_anon_identity_tag(
    *,
    tag_path: str = "",
    tag: str = "",
    field_name: str = "",
) -> bool:
    """
    True for identity tags Clean Descriptors must never rewrite.

    Patient ID, Patient Name, Accession Number, Study ID, Study Date, and
    Patient Birth Date are set at ingest; Clean Descriptors must not blank them
    when OpenMed tags the anonymized values as ID/NAME.

    Args:
        tag_path: Leaf path (e.g. PatientID or ContentSequence[0].TextValue).
        tag: Formatted (GGGG,EEEE) or hex string.
        field_name: Display name (unused for matching; reserved for callers).

    Returns:
        True when the tag is an anonymized identity / date surface.
    """
    del field_name
    leaf = str(tag_path or "").split(".")[-1].strip()
    if leaf in _ANON_SURFACE_KEYWORDS:
        return True
    hex8 = "".join(ch for ch in str(tag or "") if ch in "0123456789abcdefABCDEF").upper()
    return hex8 in _ANON_IDENTITY_TAG_HEX


def mask_text_for_ner(
    text: str,
    *,
    whitelist: Sequence[str] = (),
    anon_values: Set[str] | None = None,
    similarity: float = DEFAULT_WHITELIST_SIMILARITY,
    min_length_ratio: float = DEFAULT_WHITELIST_MIN_LENGTH_RATIO,
    mask_uids: bool = True,
    mask_dates: bool = True,
    mask_times: bool = True,
    log_context: str = "report",
) -> MaskResult:
    """
    Same-length mask of anon surfaces and optional UID / date / time / whitelist spans.

    Offsets into the returned string match the original, so NER spans remain
    valid against the unmasked body used for study-PHI matching / UI.

    Args:
        text: Source unicode to mask.
        whitelist: Radiology terms to blank before NER.
        anon_values: Anonymized header surfaces already on the dataset.
        similarity: Whitelist fuzzy-match threshold.
        min_length_ratio: Whitelist minimum length ratio.
        mask_uids: When True, blank embedded DICOM UID spans.
        mask_dates: When True, blank compact YYYYMMDD spans.
        mask_times: When True, blank compact and colon clock-time spans.
        log_context: Log prefix for mask audit lines.
    """
    body = str(text or "")
    if not body:
        return MaskResult(text="", hits=())

    chars = list(body)
    hits: list[FilterHit] = []
    occupied: list[tuple[int, int]] = []
    anon = frozenset(str(v).strip() for v in (anon_values or ()) if str(v).strip())
    terms = [str(t).strip() for t in whitelist if str(t).strip()]

    def _claim(start: int, end: int, reason: str, frag: str, detail: str = "") -> None:
        if start < 0 or end > len(chars) or start >= end:
            return
        if any(start < b and end > a for a, b in occupied):
            return
        for i in range(start, end):
            chars[i] = " "
        occupied.append((start, end))
        hits.append(FilterHit(reason=reason, text=frag, detail=detail))

    for value in sorted(anon, key=len, reverse=True):
        for start, end in _find_all(body, value):
            _claim(start, end, "anonymized", body[start:end], detail="header_surface")

    if mask_uids:
        for match in _UID_RE.finditer(body):
            _claim(match.start(), match.end(), "uid", match.group(0))

    if mask_dates:
        for match in _COMPACT_DATE_RE.finditer(body):
            _claim(match.start(), match.end(), "date", match.group(0), detail="DA")

    if mask_times:
        # Decimal floats occupy ranges so compact TM cannot claim fractional digits.
        for match in _DECIMAL_FLOAT_RE.finditer(body):
            occupied.append((match.start(), match.end()))

        for match in _COMPACT_TIME_RE.finditer(body):
            # Avoid re-masking digits that are part of a longer UID already claimed.
            _claim(match.start(), match.end(), "time", match.group(0), detail="TM")

        for match in _COLON_TIME_RE.finditer(body):
            # Date component stays visible; only the clock time is masked, so
            # the model cannot return a combined date_time span.
            _claim(match.start(), match.end(), "time", match.group(0), detail="TM")

    if terms:
        for match in _WORD_RE.finditer(body):
            token = match.group(0)
            hit = similarity_term_match(
                token,
                terms,
                threshold=similarity,
                min_length_ratio=min_length_ratio,
            )
            if hit.matched:
                _claim(
                    match.start(),
                    match.end(),
                    "whitelist",
                    token,
                    detail=f"term={hit.term!r} sim={hit.similarity:.3f}",
                )

    masked = "".join(chars)
    _log_mask_hits(log_context, hits)
    return MaskResult(text=masked, hits=tuple(hits))


def prepare_metadata_ner_segments(
    items: Sequence[MetadataNerItem],
    *,
    whitelist: Sequence[str] = (),
    anon_values: Set[str] | None = None,
    similarity: float = DEFAULT_WHITELIST_SIMILARITY,
    min_length_ratio: float = DEFAULT_WHITELIST_MIN_LENGTH_RATIO,
    log_context: str = "metadata",
) -> list[PreparedMetadataSegment]:
    """
    Select Content cells with alphanumeric text for NER and wrap with field context.

    Skipped cells are logged with reason; keepers become Field Name: value.
    (or bare value. when the name is empty/structural).

    Anonymized header surfaces and whitelist terms are masked out of the value
    (same-length) before the model runs. Embedded dates, times, and UIDs are
    left visible so Clean Descriptors can detect and remove them. CS uses
    digits_only before wrap. A cell left with no alphanumeric text after
    masking is skipped, not sent.
    """
    anon = frozenset(str(v).strip() for v in (anon_values or ()) if str(v).strip())
    prepared: list[PreparedMetadataSegment] = []
    skips: list[tuple[MetadataNerItem, FilterHit]] = []
    seen: set[str] = set()

    for item in items:
        text = str(item.text or "")
        stripped = text.strip()
        vr = str(item.vr or "").upper()
        # CS: same digits_only helper as extract so NER matches Content.
        if vr in DIGITS_ONLY_VRS:
            stripped = digits_only(stripped)
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)

        reason = _descriptor_ner_skip_reason(item, text=stripped, anon=anon)
        if reason is not None:
            skips.append((item, reason))
            continue

        # Anon + whitelist only — dates/times/UIDs stay for NER → scrub.
        masked = mask_text_for_ner(
            stripped,
            whitelist=whitelist,
            anon_values=anon,
            similarity=similarity,
            min_length_ratio=min_length_ratio,
            mask_uids=False,
            mask_dates=False,
            mask_times=False,
            log_context=f"{log_context}.cell",
        )
        if not any(ch.isalnum() for ch in masked.text):
            reason = (
                "whitelist"
                if any(hit.reason == "whitelist" for hit in masked.hits)
                else "masked_empty"
            )
            skips.append((item, FilterHit(reason, stripped, detail="no_text_after_mask")))
            continue
        # PersonName caret → space (same length) before wrap so OpenMed sees
        # "LOPEZ JOANN" not "LOPEZ^JOANN" (caret confuses Given → ID).
        ner_value = caret_to_space_for_ner(masked.text)
        ner_text, value_start, value_end = _wrap_field_for_ner(
            item.field_name, ner_value
        )
        prepared.append(
            PreparedMetadataSegment(
                original_text=stripped,
                ner_text=ner_text,
                value_start=value_start,
                value_end=value_end,
                field_name=str(item.field_name or "").strip(),
            )
        )

    _log_metadata_prepare(log_context, skips=skips, prepared=prepared)
    return prepared


def remap_ner_entities_to_original(
    entities: Sequence[Entity],
    prepared: PreparedMetadataSegment,
) -> list[Entity]:
    """Keep NER spans fully inside the value region; remap to original_text."""
    out: list[Entity] = []
    for ent in entities:
        if ent.start < prepared.value_start or ent.end > prepared.value_end:
            continue
        start = ent.start - prepared.value_start
        end = ent.end - prepared.value_start
        if start < 0 or end > len(prepared.original_text) or start >= end:
            continue
        out.append(
            Entity(
                label=ent.label,
                start=start,
                end=end,
                score=ent.score,
                raw_label=ent.raw_label,
                replacement=ent.replacement,
            )
        )
    return out


def date_time_pattern_entities(text: str) -> list[Entity]:
    """
    DATE entities for compact DICOM dates/times embedded in free text.

    Special case (metadata Clean Descriptors / Detect):
    OpenMed reliably tags punctuated or word dates (2010/12/03, 12/03/2010,
    "December 3, 2010") but often misses bare YYYYMMDD after radiology prose
    (e.g. "PET-CT SERIES 20101203"). Those compact DA/TM forms are still PHI
    for text_removed. This helper claims them as product DATE on the original
    Content so they merge with NER spans and go through the same remove path.

    Do not use this as a pre-NER mask — masking hid the digits from the model
    and from scrub. Call after NER remap; callers skip overlaps with NER.

    Decimal measurements (e.g. 0.096000) are keep-listed so their fractional
    digits are never claimed as compact TM.

    Args:
        text: Original Content cell (or any unicode to scan).

    Returns:
        Non-overlapping DATE entities (DA first, then colon times, then TM).
    """
    body = str(text or "")
    if not body:
        return []

    occupied: list[tuple[int, int]] = []
    out: list[Entity] = []

    def _claim(start: int, end: int, *, raw_label: str) -> None:
        if start < 0 or end > len(body) or start >= end:
            return
        if any(start < b and end > a for a, b in occupied):
            return
        occupied.append((start, end))
        out.append(
            Entity(
                label="DATE",
                start=start,
                end=end,
                score=1.0,
                raw_label=raw_label,
            )
        )

    for match in _COMPACT_DATE_RE.finditer(body):
        _claim(match.start(), match.end(), raw_label="compact_da")
    for match in _COLON_TIME_RE.finditer(body):
        _claim(match.start(), match.end(), raw_label="colon_tm")
    # Keep-list: decimal floats occupy ranges without emitting DATE, so compact
    # TM cannot claim fractional digit runs (0.096000 → not DATE on 096000).
    for match in _DECIMAL_FLOAT_RE.finditer(body):
        start, end = match.start(), match.end()
        if start < 0 or end > len(body) or start >= end:
            continue
        if any(start < b and end > a for a, b in occupied):
            continue
        occupied.append((start, end))
    for match in _COMPACT_TIME_RE.finditer(body):
        token = match.group(0).split(".", 1)[0]
        if len(token) < 6:
            continue
        hh, mm, ss = int(token[0:2]), int(token[2:4]), int(token[4:6])
        # Skip durations / counts that are not a valid clock time (e.g. 360000).
        if hh > 23 or mm > 59 or ss > 59:
            continue
        _claim(match.start(), match.end(), raw_label="compact_tm")

    out.sort(key=lambda e: (e.start, e.end))
    return out


def is_dicom_uid_text(text: str) -> bool:
    """True when text is (or is only) a DICOM UID."""
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _UID_RE.fullmatch(stripped):
        return True
    # Multi-value UID-ish (rare); treat as UID if every token matches.
    parts = [p for p in re.split(r"[\\|/]+", stripped) if p.strip()]
    return bool(parts) and all(_UID_RE.fullmatch(p.strip()) for p in parts)


def is_compact_dicom_datetime(text: str) -> bool:
    """True for compact DA (YYYYMMDD) or TM (HHMMSS[.frac]) only."""
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _COMPACT_DATE_RE.fullmatch(stripped):
        return True
    return bool(_COMPACT_TIME_RE.fullmatch(stripped))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _descriptor_ner_skip_reason(
    item: MetadataNerItem,
    *,
    text: str,
    anon: Set[str],
) -> FilterHit | None:
    """
    Decide whether a descriptor cell is sent to NER.

    Returns:
        None if the cell should be wrapped and sent to NER.
        FilterHit if the cell should be skipped (reason + detail for logs).

    Check order:
        1. anonymizer — de-identification stamp / anonymizer-owned field
        2. safe — script @safe() (Retain Device Identity, etc.): never NER
        3. code_field — DICOM code-set plumbing (CodeValue, …)
        4. short_coded_string — IS/CS with length <= 3 (after digits_only)
        5. date — true DA/DT rows only (script owns those tags)
        6. uid — UI VR or UID-shaped value
        7. non_prose_vr — binary / structural VRs still on the non-prose list
        8. anonymized — equals an anonymized header surface already on ds
        9. no_alnum — no alphanumeric characters

    CS is digits_only before this runs. IS/DS keep full text (including
    compact YYYYMMDD and embedded PHI) so NER and date/time pattern merge
    can scrub PHI planted in those VRs.
    """
    if item.is_anonymizer_field:
        return FilterHit("anonymizer", text, detail=item.field_name or item.tag)

    if is_safe_operation(item.script_operation):
        return FilterHit("safe", text, detail=item.script_operation or "@safe()")

    leaf_keyword = re.sub(r"\[\d+\]$", "", str(item.tag_path or "").rsplit(".", 1)[-1])
    if leaf_keyword in SKIP_TEXT_KEYWORDS:
        return FilterHit("code_field", text, detail=leaf_keyword)

    vr = str(item.vr or "").upper()
    if vr in DIGITS_ONLY_VRS and len(text) <= 3:
        return FilterHit("short_coded_string", text, detail=vr)

    # Script-owned date tags only — not IS/DS/CS that happen to look like YYYYMMDD.
    if item.is_date or vr in DATE_VRS:
        return FilterHit("date", text, detail=vr or "datetime")

    if vr == "UI" or is_dicom_uid_text(text):
        return FilterHit("uid", text, detail=vr or "UI")

    if vr and vr not in TEXT_VRS and vr not in INTEGER_AND_CODE_STRING_VRS:
        if vr in (_NON_PROSE_VR_CORE | DATE_VRS):
            return FilterHit("non_prose_vr", text, detail=vr)

    if text in anon:
        return FilterHit("anonymized", text, detail="equals_header_surface")

    if not any(ch.isalnum() for ch in text):
        return FilterHit("no_alnum", text, detail=vr or "heuristic")

    return None


def caret_to_space_for_ner(text: str) -> str:
    """Same-length PersonName caret (^) → space so NER sees prose, not PN syntax.

    Offsets stay aligned with the original cell (including carets) for remap.
    Collapsing spaces would break offset mapping — do not strip here.

    Args:
        text: Cell value (may include DICOM PN carets).

    Returns:
        Copy with every '^' replaced by ' '.
    """
    return str(text or "").replace("^", " ")


def wrap_field_for_ner(field_name: str, value: str) -> tuple[str, int, int]:
    """Wrap a metadata cell as Field Name: value. for OpenMed chunk context."""
    name = str(field_name or "").strip()
    if not name or name in {"item", "value", "-"}:
        ner = f"{value}."
        return ner, 0, len(value)
    prefix = f"{name}: "
    ner = f"{prefix}{value}."
    start = len(prefix)
    return ner, start, start + len(value)


# Back-compat alias used inside this module.
_wrap_field_for_ner = wrap_field_for_ner


def _find_all(text: str, needle: str) -> list[tuple[int, int]]:
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


def _log_mask_hits(context: str, hits: Sequence[FilterHit]) -> None:
    prefix = f"radiology_filter[{context}]"
    if not hits:
        logger.info("%s: no pre-NER masks", prefix)
        return
    logger.info("%s: masked %d span(s) before NER", prefix, len(hits))
    for hit in hits:
        extra = f" ({hit.detail})" if hit.detail else ""
        logger.info(
            "%s:   %s %r%s",
            prefix,
            hit.reason,
            _short(hit.text),
            extra,
        )


def _log_metadata_prepare(
    context: str,
    *,
    skips: Sequence[tuple[MetadataNerItem, FilterHit]],
    prepared: Sequence[PreparedMetadataSegment],
) -> None:
    prefix = f"radiology_filter[{context}]"
    logger.info(
        "%s: prepare NER segments keep=%d skip=%d",
        prefix,
        len(prepared),
        len(skips),
    )
    for item, hit in skips:
        field = str(item.field_name or "").strip() or "(no field)"
        extra = f" ({hit.detail})" if hit.detail else ""
        logger.info(
            "%s:   skip %-12s field=%s text=%r%s",
            prefix,
            hit.reason,
            field,
            _short(hit.text),
            extra,
        )
    for seg in prepared:
        field = seg.field_name or "(no field)"
        logger.info(
            "%s:   keep field=%s ner=%r",
            prefix,
            field,
            _short(seg.ner_text),
        )


def _short(text: str, limit: int = 80) -> str:
    raw = str(text or "").replace("\n", "\\n")
    if len(raw) <= limit:
        return raw
    return raw[: limit - 3] + "..."
