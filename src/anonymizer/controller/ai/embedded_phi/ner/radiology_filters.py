"""Pre-NER text filters (Metadata / Report).
OpenMed expects clinical-report-style prose. Before NER:
* **Metadata cells** — prepare_metadata_ner_segments: skip UID / date /
  anonymizer / non-prose / DICOM code fields; same-length mask of anon

Public API
----------
DEFAULT_WHITELIST_SIMILARITY
    Default whitelist similarity (0.75).

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

mask_text_for_ner(text: str, *, whitelist: Sequence[str]=(), anon_values: Set[str] | None=None, similarity: float=DEFAULT_WHITELIST_SIMILARITY, min_length_ratio: float=..., log_context: str='report') -> MaskResult
    Same-length mask of anon surfaces, UIDs, dates/clock-times, whitelist terms.

prepare_metadata_ner_segments(items: Sequence[MetadataNerItem], *, whitelist: Sequence[str]=(), anon_values: Set[str] | None=None, similarity: float=DEFAULT_WHITELIST_SIMILARITY, min_length_ratio: float=..., log_context: str='metadata') -> list[PreparedMetadataSegment]
    Select prose Content cells for NER and wrap them with field-name context.

remap_ner_entities_to_original(entities: Sequence[Entity], prepared: PreparedMetadataSegment) -> list[Entity]
    Keep NER spans fully inside the value region; remap to original_text.

is_dicom_uid_text(text: str) -> bool
    True when text is (or is only) a DICOM UID.

is_compact_dicom_datetime(text: str) -> bool
    True for compact DA (YYYYMMDD) or TM (HHMMSS[.frac]) only.

looks_like_prose_carrier(text: str) -> bool
    True when the cell looks like language (not a bare code / number).

wrap_field_for_ner(field_name: str, value: str) -> tuple[str, int, int]
    Wrap a metadata cell as Field Name: value. for OpenMed chunk context.
"""
import logging
import re
from collections.abc import Iterable, Sequence, Set
from dataclasses import dataclass

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.extract import DATE_VRS, SKIP_TEXT_KEYWORDS, TEXT_VRS
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.term_similarity import similarity_term_match

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Default similarity (aligned with OCR modality whitelist STANDARD preset).
DEFAULT_WHITELIST_SIMILARITY = 0.75
DEFAULT_WHITELIST_MIN_LENGTH_RATIO = 0.7

# DICOM keywords whose current (anonymized) values must not be re-scored by NER.
_ANON_SURFACE_KEYWORDS = (
    "PatientName",
    "PatientID",
    "AccessionNumber",
    "StudyDate",
    "PatientBirthDate",
    "StudyID",
)

# VRs that never carry clinical free-text PHI for NER (dates added at use-site
# from metadata.extract.DATE_VRS — lazy import avoids package cycle).
_NON_PROSE_VR_CORE = frozenset(
    {
        "UI",
        "CS",
        "IS",
        "DS",
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
_COMPACT_TIME_RE = re.compile(r"\b\d{6}(?:\.\d{1,6})?\b")
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


def mask_text_for_ner(
    text: str,
    *,
    whitelist: Sequence[str] = (),
    anon_values: Set[str] | None = None,
    similarity: float = DEFAULT_WHITELIST_SIMILARITY,
    min_length_ratio: float = DEFAULT_WHITELIST_MIN_LENGTH_RATIO,
    log_context: str = "report",
) -> MaskResult:
    """
    Same-length mask of anon surfaces, UIDs, dates/clock-times, whitelist terms.

    Offsets into the returned string match the original, so NER spans remain
    valid against the unmasked body used for study-PHI matching / UI.
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

    for match in _UID_RE.finditer(body):
        _claim(match.start(), match.end(), "uid", match.group(0))

    for match in _COMPACT_DATE_RE.finditer(body):
        _claim(match.start(), match.end(), "date", match.group(0), detail="DA")

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
    Select prose Content cells for NER and wrap them with field-name context.

    Skipped cells are logged with reason; keepers become Field Name: value.
    (or bare value. when the name is empty/structural).

    whitelist terms are masked out of the value (same-length, via
    mask_text_for_ner with similarity / min_length_ratio) before
    the model runs — the same pre-NER veto the pixel path applies. A cell
    left with no alphabetic text after masking is skipped, not sent.
    """
    anon = frozenset(str(v).strip() for v in (anon_values or ()) if str(v).strip())
    prepared: list[PreparedMetadataSegment] = []
    skips: list[tuple[MetadataNerItem, FilterHit]] = []
    seen: set[str] = set()

    for item in items:
        text = str(item.text or "")
        stripped = text.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)

        reason = _metadata_skip_reason(item, text=stripped, anon=anon)
        if reason is not None:
            skips.append((item, reason))
            continue

        # Same-length in-cell mask (anon / UID / date / whitelist) so offsets map back.
        masked = mask_text_for_ner(
            stripped,
            whitelist=whitelist,
            anon_values=anon,
            similarity=similarity,
            min_length_ratio=min_length_ratio,
            log_context=f"{log_context}.cell",
        )
        if not any(ch.isalpha() for ch in masked.text):
            reason = (
                "whitelist"
                if any(hit.reason == "whitelist" for hit in masked.hits)
                else "masked_empty"
            )
            skips.append((item, FilterHit(reason, stripped, detail="no_text_after_mask")))
            continue
        ner_text, value_start, value_end = _wrap_field_for_ner(
            item.field_name, masked.text
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


def looks_like_prose_carrier(text: str) -> bool:
    """True when the cell looks like language (not a bare code / number)."""
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if not any(ch.isalpha() for ch in stripped):
        return False
    if " " in stripped or "\n" in stripped or "\t" in stripped:
        return True
    # Single token with mixed case / length can still be a name or description.
    if len(stripped) >= 8 and any(ch.islower() for ch in stripped):
        return True
    # PersonName caret form
    return "^" in stripped and any(ch.isalpha() for ch in stripped)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _metadata_skip_reason(
    item: MetadataNerItem,
    *,
    text: str,
    anon: Set[str],
) -> FilterHit | None:
    if item.is_anonymizer_field:
        return FilterHit("anonymizer", text, detail=item.field_name or item.tag)

    leaf_keyword = re.sub(r"\[\d+\]$", "", str(item.tag_path or "").rsplit(".", 1)[-1])
    if leaf_keyword in SKIP_TEXT_KEYWORDS:
        return FilterHit("code_field", text, detail=leaf_keyword)

    # Lazy: metadata.extract is SSOT for TEXT_VRS / DATE_VRS (avoid import cycle).

    vr = str(item.vr or "").upper()
    if item.is_date or vr in DATE_VRS or is_compact_dicom_datetime(text):
        return FilterHit("date", text, detail=vr or "datetime")

    if vr == "UI" or is_dicom_uid_text(text):
        return FilterHit("uid", text, detail=vr or "UI")

    if vr and vr not in TEXT_VRS and vr in (_NON_PROSE_VR_CORE | DATE_VRS):
        return FilterHit("non_prose_vr", text, detail=vr)

    if text in anon:
        return FilterHit("anonymized", text, detail="equals_header_surface")

    if not looks_like_prose_carrier(text):
        return FilterHit("non_prose", text, detail=vr or "heuristic")

    return None


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
