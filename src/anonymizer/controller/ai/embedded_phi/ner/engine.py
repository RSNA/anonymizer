"""Model-only PHI NER: unicode text in → labeled spans; blank or synthetic replace.
Uses OpenMed ClinicalE5 token-classification only (no lexicon / phone regex).
Product labels: FIRST_NAME, LAST_NAME, LOCATION, ID,
PHONE, DATE, EMAIL. Pixel PHI may also keep TIME via include_time.
Unmapped model spans that are entirely a date or time pattern are kept.

Public API
----------
SCORED_LABELS
    Scored labels.

SUPPORTED_DETECT_LOCALES
    Supported detect locales.

ReplaceMode
    Replacemode.

REPLACE_MODE_VALUES
    Replace mode values.

SEGMENT_SEP
    Segment sep (default '\n\x1e\n').

Entity
    One PHI span: product label plus character offsets into the source string.

detect_entities(text: str, *, locale: str='en_US', include_time: bool=False) -> list[Entity]
    Run OpenMed token-classification on text. Pixel PHI sets include_time to keep TIME.
    Before dropping an unmapped label, keep the span when it is a date or time.

detect_entities_in_segments(segments: Sequence[str], *, locale: str='en_US', max_chars: int=_DEFAULT_SEGMENT_MAX_CHARS, scan_fn: Callable[[str], list[Entity]] | None=None) -> list[list[Entity]]
    Run a text PHI scanner on **chunks of whole fields**.

replace_entities(text: str, entities: Sequence[Entity] | None=None, *, mode: ReplaceMode='blank', locale: str='en_US', project_id: str='default', anon_ptid: str='ANON0000', log: bool=True) -> tuple[str, list[Entity]]
    Replace PHI spans in text right-to-left.

format_tagged_entities(text: str, entities: Sequence[Entity]) -> str
    Wrap entity spans as <LABEL>…</LABEL> for Clean Descriptors / NER logs.

expand_entities_for_remove(text: str, entities: Sequence[Entity]) -> list[Entity]
    Widen FIRST_NAME/LAST_NAME/ID spans for PN carets, leading "for ", and
    leading "Dr." before names.

detect_locale_supported(locale: str) -> bool
    Return whether locale has a supported OpenMed detect pack.
"""

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from anonymizer.controller.ai.embedded_phi.ner.cache import (
    load_token_classification_pipeline,
    ner_ready,
    resolve_model_id,
)
from anonymizer.controller.ai.embedded_phi.ner.entity import Entity as Entity
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import (
    date_time_pattern_entities,
)
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import generate_synthetic_phi

try:
    import torch  # noqa: F401
except ImportError:
    torch = None  # type: ignore[assignment,misc]
try:
    import transformers  # noqa: F401
except ImportError:
    transformers = None  # type: ignore[assignment,misc]
logger = logging.getLogger(__name__)

SCORED_LABELS = (
    "FIRST_NAME",
    "LAST_NAME",
    "LOCATION",
    "ID",
    "PHONE",
    "DATE",
    "EMAIL",
)

SUPPORTED_DETECT_LOCALES = frozenset({"en_US"})

ReplaceMode = Literal["blank", "synth"]
REPLACE_MODE_VALUES: tuple[ReplaceMode, ...] = ("blank", "synth")

# Join short Content / OCR fragments for one model pass (ASCII RS; rare in DICOM text).
SEGMENT_SEP = "\n\x1e\n"
# Stay under ClinicalE5 ~512-token window with headroom for WordPieces.
_DEFAULT_SEGMENT_MAX_CHARS = 1600

# Blank-mode span expansion: PN carets next to names; leading "for " before
# name/ID; leading "Dr." / "Dr " before names so titles are not left behind.
_NAME_LABELS = frozenset({"FIRST_NAME", "LAST_NAME"})
_NAME_OR_ID_LABELS = frozenset({"FIRST_NAME", "LAST_NAME", "ID"})
_FOR_BEFORE_RE = re.compile(r"(?<![A-Za-z0-9])for\s+$", re.IGNORECASE)
_DR_BEFORE_RE = re.compile(r"(?<![A-Za-z0-9])Dr\.?\s+$", re.IGNORECASE)

# Map OpenMed / HF entity_group strings onto product labels (model decides; no regex).
_TO_SCORED: dict[str, str] = {
    "FIRSTNAME": "FIRST_NAME",
    "FIRST_NAME": "FIRST_NAME",
    "LASTNAME": "LAST_NAME",
    "LAST_NAME": "LAST_NAME",
    "USERNAME": "ID",
    "USER_NAME": "ID",
    "DATE": "DATE",
    "DATE_TIME": "DATE",
    "AGE": "DATE",
    "DATE_OF_BIRTH": "DATE",
    "DATEOFBIRTH": "DATE",
    "DOB": "DATE",
    "LOCATION": "LOCATION",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
    "FAC": "LOCATION",
    "ADDRESS": "LOCATION",
    "HOSPITAL": "LOCATION",
    "CITY": "LOCATION",
    "STATE": "LOCATION",
    "COUNTRY": "LOCATION",
    "COUNTY": "LOCATION",
    "ZIP": "LOCATION",
    "ZIPCODE": "LOCATION",
    "STREET": "LOCATION",
    "STREET_ADDRESS": "LOCATION",
    "CITY_STATE": "LOCATION",
    "POSTCODE": "LOCATION",
    "ID": "ID",
    "IDNUM": "ID",
    "MEDICALRECORD": "ID",
    "MEDICAL_RECORD": "ID",
    "MEDICAL_RECORD_NUMBER": "ID",
    "MRN": "ID",
    "SSN": "ID",
    "US_SSN": "ID",
    "SOCIAL_SECURITY_NUMBER": "ID",
    "SOCIALSECURITYNUMBER": "ID",
    "NATIONAL_ID": "ID",
    "PATIENT_ID": "ID",
    "PATIENT_IDENTIFIER": "ID",
    "ACCOUNT": "ID",
    "ACCOUNT_NUMBER": "ID",
    "UNIQUE_ID": "ID",
    "CUSTOMER_ID": "ID",
    "EMPLOYEE_ID": "ID",
    "TAX_ID": "ID",
    "BIOID": "ID",
    "BIOMETRIC_IDENTIFIER": "ID",
    "HEALTHPLAN": "ID",
    "HEALTH_PLAN_BENEFICIARY_NUMBER": "ID",
    "DEVICE": "ID",
    "DEVICE_IDENTIFIER": "ID",
    "CREDIT_CARD": "ID",
    "CREDITCARDNUMBER": "ID",
    "CREDIT_DEBIT_CARD": "ID",
    "CERTIFICATE_LICENSE_NUMBER": "ID",
    "PHONE": "PHONE",
    "PHONE_NUMBER": "PHONE",
    "TELEPHONENUMBER": "PHONE",
    "FAX": "PHONE",
    "FAX_NUMBER": "PHONE",
    "EMAIL": "EMAIL",
    "EMAIL_ADDRESS": "EMAIL",
    "EMAILADDRESS": "EMAIL",
}

_PIPE = None
_PIPE_MODEL_ID: str | None = None
_PIPE_ERROR: str | None = None


# Clock raw labels from date_time_pattern_entities (colon and compact TM).
_DATE_TIME_CLOCK_RAW = frozenset({"colon_tm", "compact_tm"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_entities(
    text: str,
    *,
    locale: str = "en_US",
    include_time: bool = False,
) -> list[Entity]:
    """
    Run OpenMed token-classification on text.

    Product-labeled entities with start/end into text. No lexicon,
    phone-regex, or merging. An unmapped model label is kept when the span
    is entirely a date or time from date_time_pattern_entities.

    Logging: **INFO** traces the key processing steps in order —
    step 1/4 input, step 2/4 model raw spans, step 3/4 label map
    (kept + dropped with reasons), step 4/4 tagged result.

    Args:
        text: Source unicode to scan.
        locale: NER locale pack (default en_US).
        include_time: When True (pixel PHI), keep model TIME as product
            label TIME. Metadata / report paths leave this False.

    Returns:
        List of Entity spans (may be empty if models missing or text blank).
    """
    body = str(text or "")
    allowed_labels = _allowed_scored_labels(include_time=include_time)
    logger.info(
        f"ner: step 1/4 input locale={locale} include_time={include_time} "
        f"chars={len(body)}\n{_trace(body)}"
    )

    if not body.strip():
        logger.info("ner: skip — empty / whitespace-only text (steps 2-4 not run)")
        logger.info(f"ner: step 4/4 tagged result (no entities)\n{_trace('')}")
        return []
    if not detect_locale_supported(locale):
        logger.warning(f"ner: skip — locale {locale!r} not in {sorted(SUPPORTED_DETECT_LOCALES)}")
        logger.info(f"ner: step 4/4 tagged result (no entities)\n{_trace('')}")
        return []
    if not ner_ready():
        logger.warning("ner: skip — OpenMed weights not ready (download / probe)")
        logger.info(f"ner: step 4/4 tagged result (no entities)\n{_trace('')}")
        return []

    raw_ents = _run_pipeline(body, locale=locale)
    logger.info(
        f"ner: step 2/4 model raw spans count={len(raw_ents)}\n"
        f"{format_ner_raw_spans_for_log(raw_ents, body)}"
    )

    mapped: list[Entity] = []
    dropped_rows: list[tuple[str, float, str]] = []
    for ent in raw_ents:
        raw = str(ent.get("entity_group") or ent.get("entity") or "")
        scored = _to_scored_label(raw, include_time=include_time)
        if scored is None or scored not in allowed_labels:
            start, end = int(ent["start"]), int(ent["end"])
            word = body[start:end]
            score = float(ent.get("score", 0.5))
            # TIME gated off by include_time is a known label, not a misclass.
            if _to_scored_label(raw, include_time=True) is None:
                rescued = _date_time_label_for_span(word, include_time=include_time)
                if rescued is not None and rescued in allowed_labels:
                    mapped.append(
                        Entity(
                            label=rescued,
                            start=start,
                            end=end,
                            score=score,
                            raw_label=raw,
                        )
                    )
                    continue
            dropped_rows.append(
                (
                    word,
                    score,
                    f"no product label for raw label {raw!r}",
                )
            )
            continue
        mapped.append(
            Entity(
                label=scored,
                start=int(ent["start"]),
                end=int(ent["end"]),
                score=float(ent.get("score", 0.5)),
                raw_label=raw,
            )
        )
    logger.info(
        f"ner: step 3/4 label map kept={len(mapped)} dropped={len(dropped_rows)} "
        f"(product labels={', '.join(allowed_labels)})\n"
        f"kept=\n{format_ner_entities_for_log(mapped, body)}\n"
        f"dropped=\n{format_ner_drops_for_log(dropped_rows)}"
    )

    tagged = _format_entities_xml(body, mapped)
    logger.info(f"ner: step 4/4 tagged result entities={len(mapped)}\n{_trace(tagged)}")
    return mapped


def detect_entities_in_segments(
    segments: Sequence[str],
    *,
    locale: str = "en_US",
    max_chars: int = _DEFAULT_SEGMENT_MAX_CHARS,
    scan_fn: Callable[[str], list[Entity]] | None = None,
) -> list[list[Entity]]:
    """
    Run a text PHI scanner on **chunks of whole fields**.

    Joins non-empty segments with SEGMENT_SEP, packs into chunks up to
    max_chars, and maps spans back to per-field offsets. Chunk boundaries
    are always field boundaries (a field is never split mid-value). Spans that
    cross a field separator are dropped. Empty / whitespace-only segments yield
    [].

    Default scan_fn is detect_entities (NER only). Report View / Metadata
    pass detect_report_text_phi_in_text so study-PHI matching + NER share one join pass.

    Args:
        segments: Source strings (order preserved in the return value).
        locale: NER locale pack (used when scan_fn is omitted).
        max_chars: Soft cap per chunk (model context window); splits only between fields.
        scan_fn: text → list[Entity] with offsets into that text.

    Returns:
        Parallel list: entities for each input segment (offsets into that segment).
    """
    scan = scan_fn or (lambda body: detect_entities(body, locale=locale))
    bodies = [str(s or "") for s in segments]
    out: list[list[Entity]] = [[] for _ in bodies]
    work: list[tuple[int, str]] = [(i, b) for i, b in enumerate(bodies) if b.strip()]
    if not work:
        return out

    sep = SEGMENT_SEP
    sep_len = len(sep)
    cap = max(64, int(max_chars))
    chunks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    current_len = 0
    for idx, text in work:
        # Always append whole fields; never split mid-field.
        add = len(text) if not current else sep_len + len(text)
        if current and current_len + add > cap:
            chunks.append(current)
            current = []
            current_len = 0
            add = len(text)
        current.append((idx, text))
        current_len += add
    if current:
        chunks.append(current)

    logger.debug(
        "ner: segment detect start segments=%d nonempty=%d chunks=%d locale=%s",
        len(bodies),
        len(work),
        len(chunks),
        locale,
    )
    for chunk in chunks:
        parts = [text for _i, text in chunk]
        joined = sep.join(parts)
        ranges: list[tuple[int, int, int]] = []
        pos = 0
        for i, (_seg_i, text) in enumerate(chunk):
            if i:
                pos += sep_len
            start = pos
            end = pos + len(text)
            ranges.append((_seg_i, start, end))
            pos = end
        entities = scan(joined)
        for ent in entities:
            for seg_i, start, end in ranges:
                if ent.start >= start and ent.end <= end:
                    out[seg_i].append(
                        Entity(
                            label=ent.label,
                            start=ent.start - start,
                            end=ent.end - start,
                            score=ent.score,
                            raw_label=ent.raw_label,
                            replacement=ent.replacement,
                        )
                    )
                    break
            else:
                logger.debug(
                    "ner: drop span crossing field boundary [%d:%d)",
                    ent.start,
                    ent.end,
                )
    hit_segments = sum(1 for ents in out if ents)
    logger.debug(
        "ner: segment detect done chunks=%d segments_with_phi=%d",
        len(chunks),
        hit_segments,
    )
    return out


def replace_entities(
    text: str,
    entities: Sequence[Entity] | None = None,
    *,
    mode: ReplaceMode = "blank",
    locale: str = "en_US",
    project_id: str = "default",
    anon_ptid: str = "ANON0000",
    log: bool = True,
) -> tuple[str, list[Entity]]:
    """
    Replace PHI spans in text right-to-left.

    If entities is omitted, runs detect_entities first.
    Spans with Entity.replacement (report metadata PHI) always write that
    string. Remaining spans: blank clears; synth uses
    generate_synthetic_phi and offline pools.

    Blank mode expands FIRST_NAME/LAST_NAME spans to absorb adjacent PN
    carets (^), and expands FIRST_NAME/LAST_NAME/ID spans to absorb a
    leading "for " so description prepositions are not left behind.
    Protocol carets (e.g. Abdomen^24ACRIN) are left unchanged.

    Args:
        text: Source unicode containing PHI spans.
        entities: Spans to replace; None triggers detect first.
        mode: blank or synth (NER spans only; metadata uses replacement).
        locale: Locale for detect (if needed) and synthetic pools.
        project_id: Seed namespace for synthetic values.
        anon_ptid: Anonymized patient id seed for synthetic values.
        log: When False, skip INFO replace-result traces (batch consolidates).

    Returns:
        (new_text, entities_used).
    """
    body = str(text or "")
    detect_first = entities is None
    logger.debug(
        "ner: replace start mode=%s locale=%s detect_first=%s chars=%d",
        mode,
        locale,
        detect_first,
        len(body),
    )
    used = list(entities) if entities is not None else detect_entities(body, locale=locale)
    if not used:
        logger.debug("ner: replace skip — no entities to replace")
        if log:
            logger.info("ner: replace result\n%s", _trace(body))
        return body, []

    meta_n = sum(1 for e in used if e.replacement is not None)
    logger.debug(
        "ner: replace apply %d span(s) right-to-left mode=%s (metadata_replacement=%d ner=%d)\n%s",
        len(used),
        mode,
        meta_n,
        len(used) - meta_n,
        format_ner_entities_for_log(used, body),
    )
    ordinals: dict[str, int] = {}
    # Non-blank writes keep explicit (start, end, repl); blank ranges merge first.
    splice: list[tuple[int, int, str]] = []
    blank_ranges: list[tuple[int, int]] = []
    for ent in sorted(used, key=lambda e: (e.start, e.end)):
        ord_i = ordinals.get(ent.label, 0)
        ordinals[ent.label] = ord_i + 1
        # Metadata PHI (DICOM keyword label): always write anonymized tag value.
        if ent.replacement is not None:
            splice.append((ent.start, ent.end, str(ent.replacement)))
            continue
        if mode == "blank":
            blank_ranges.append(_expand_blank_range(body, ent))
            continue
        splice.append(
            (
                ent.start,
                ent.end,
                generate_synthetic_phi(
                    ent.label,
                    project_id=project_id,
                    anon_ptid=anon_ptid,
                    locale=locale,
                    ordinal=ord_i,
                    source_fragment=body[ent.start : ent.end],
                ),
            )
        )
    for start, end in _merge_ranges(blank_ranges):
        splice.append((start, end, ""))
    out = body
    for start, end, repl in sorted(splice, key=lambda x: x[0], reverse=True):
        out = out[:start] + repl + out[end:]
    if mode == "blank":
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r" ?\n ?", "\n", out).strip(" \t")
    logger.debug(
        "ner: replace done mode=%s entities=%d chars %d→%d",
        mode,
        len(used),
        len(body),
        len(out),
    )
    if log:
        logger.info("ner: replace result\n%s", _trace(out))
    return out, used


def format_tagged_entities(text: str, entities: Sequence[Entity]) -> str:
    """Wrap entity spans as <LABEL>…</LABEL> for Clean Descriptors / NER logs.

    Args:
        text: Source unicode.
        entities: Spans with offsets into text.

    Returns:
        Tagged unicode (same as ner step 4/4).
    """
    return _format_entities_xml(text, entities)


def expand_entities_for_remove(
    text: str,
    entities: Sequence[Entity],
) -> list[Entity]:
    """
    Widen FIRST_NAME/LAST_NAME/ID spans for PN carets, "for ", and "Dr.".

    Post-NER Clean Descriptors step: expand on original Content before
    remove so tagged logs and blanking agree. Protocol carets that are not
    next to a name label stay unchanged.

    Args:
        text: Original Content string.
        entities: Spans with offsets into text.

    Returns:
        New entity list with widened start/end where applicable.
    """
    body = str(text or "")
    out: list[Entity] = []
    for ent in entities:
        start, end = _expand_blank_range(body, ent)
        if start == ent.start and end == ent.end:
            out.append(ent)
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
    out.sort(key=lambda e: (e.start, e.end))
    return out


def detect_locale_supported(locale: str) -> bool:
    """
    Return whether locale has a supported OpenMed detect pack.

    Args:
        locale: Locale id (e.g. en_US).

    Returns:
        True when locale is in SUPPORTED_DETECT_LOCALES.
    """
    return locale in SUPPORTED_DETECT_LOCALES


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _expand_blank_range(body: str, ent: Entity) -> tuple[int, int]:
    """
    Widen a blank span for PN carets, leading "for ", and leading "Dr.".

    Args:
        body: Full source string (original offsets).
        ent: Entity being blanked.

    Returns:
        Inclusive-exclusive (start, end) into body.
    """
    start = max(0, int(ent.start))
    end = min(len(body), int(ent.end))
    if start > end:
        return start, start
    label = str(ent.label or "")
    if label in _NAME_LABELS:
        while start > 0 and body[start - 1] == "^":
            start -= 1
        while end < len(body) and body[end] == "^":
            end += 1
        match = _DR_BEFORE_RE.search(body[:start])
        if match is not None and match.end() == start:
            start = match.start()
    if label in _NAME_OR_ID_LABELS:
        match = _FOR_BEFORE_RE.search(body[:start])
        if match is not None and match.end() == start:
            start = match.start()
    return start, end


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    Merge overlapping or touching blank ranges (original-string coordinates).

    Args:
        ranges: (start, end) pairs.

    Returns:
        Sorted non-overlapping ranges.
    """
    if not ranges:
        return []
    ordered = sorted((int(s), int(e)) for s, e in ranges if int(e) > int(s))
    if not ordered:
        return []
    merged: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _trace(text: str) -> str:
    """Multi-line log body: segment sep → one newline; drop RS; keep real newlines."""
    body = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    body = body.replace(SEGMENT_SEP, "\n").replace("\x1e", "")
    return f"<<<\n{body}\n>>>"


def _score_for_log(score: float) -> float:
    """
    Round a model score to two significant digits for log output.

    Args:
        score: Raw confidence in [0, 1] (or nearby).

    Returns:
        Float with two significant digits.
    """
    return float(f"{float(score):.2g}")


def _ner_span_word(ent: Mapping[str, Any], source: str = "") -> str:
    """Best available surface form for a raw model span (source slice, else word)."""
    start, end = ent.get("start"), ent.get("end")
    if source and isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(source):
        return source[start:end]
    return str(ent.get("word") or "")


def format_ner_raw_spans_for_log(
    raw_ents: Sequence[dict[str, Any]],
    source: str = "",
) -> str:
    """
    Format model raw spans for logs (word, entity_group, and score).

    Args:
        raw_ents: Hugging Face token-classification entity dicts.
        source: Source unicode for span text when offsets are valid.

    Returns:
        Multi-line log body, or "none".
    """
    if not raw_ents:
        return "none"
    lines: list[str] = []
    for ent in raw_ents:
        word = _ner_span_word(ent, source)
        group = str(ent.get("entity_group") or ent.get("entity") or "")
        score = _score_for_log(float(ent.get("score", 0.0)))
        lines.append(f"  {word!r}  entity_group={group}  score={score}")
    return "\n".join(lines)


def format_ner_entities_for_log(entities: Sequence[Entity], source: str) -> str:
    """
    Format product Entity spans for logs (word + score only).

    Args:
        entities: Product Entity spans.
        source: Source unicode for text slices.

    Returns:
        Multi-line log body, or "none".
    """
    if not entities:
        return "none"
    lines: list[str] = []
    for ent in entities:
        word = source[ent.start : ent.end]
        score = _score_for_log(ent.score)
        lines.append(f"  {word!r}  score={score}")
    return "\n".join(lines)


def format_ner_drops_for_log(dropped: Sequence[tuple[str, float, str]]) -> str:
    """
    Format NER label-map drops for logs (word + score + reason).

    Args:
        dropped: (word, score, reason) rows from the product-label filter.

    Returns:
        Multi-line log body, or "none".
    """
    if not dropped:
        return "none"
    lines: list[str] = []
    for word, score, reason in dropped:
        lines.append(f"  {word!r}  score={_score_for_log(score)}  reason={reason}")
    return "\n".join(lines)


def _format_entities_xml(text: str, entities: Sequence[Entity]) -> str:
    """
    Build non-overlapping product tags for NER log output (longer spans win).

    Args:
        text: Source unicode.
        entities: Candidate spans (may overlap).

    Returns:
        text with <LABEL>…</LABEL> wrappers around chosen spans.
    """
    if not text:
        return ""
    ordered = sorted(
        (e for e in entities if e.end > e.start and 0 <= e.start < e.end <= len(text)),
        key=lambda e: (e.start, -(e.end - e.start)),
    )
    chosen: list[Entity] = []
    for ent in ordered:
        if any(not (ent.end <= c.start or ent.start >= c.end) for c in chosen):
            continue
        chosen.append(ent)
    chosen.sort(key=lambda e: e.start)
    parts: list[str] = []
    cursor = 0
    for ent in chosen:
        if ent.start > cursor:
            parts.append(text[cursor : ent.start])
        frag = text[ent.start : ent.end]
        parts.append(f"<{ent.label}>{frag}</{ent.label}>")
        cursor = ent.end
    if cursor < len(text):
        parts.append(text[cursor:])
    return "".join(parts)


def _date_time_label_for_span(span: str, *, include_time: bool) -> str | None:
    """
    Product label when span is entirely one date_time_pattern_entities hit.

    Args:
        span: Model span text.
        include_time: When True, a colon or compact clock maps to TIME.

    Returns:
        DATE, TIME, or None when the span is not wholly a date or time.
    """
    body = span.strip()
    if not body:
        return None
    for ent in date_time_pattern_entities(body):
        if ent.start != 0 or ent.end != len(body):
            continue
        if ent.raw_label in _DATE_TIME_CLOCK_RAW:
            return "TIME" if include_time else "DATE"
        return "DATE"
    return None


def _allowed_scored_labels(*, include_time: bool) -> tuple[str, ...]:
    """
    Product labels accepted for this detect call.

    Args:
        include_time: When True, allow pixel-PHI TIME alongside SCORED_LABELS.

    Returns:
        Ordered label tuple used by the product-label filter.
    """
    if include_time:
        return (*SCORED_LABELS, "TIME")
    return SCORED_LABELS


def _to_scored_label(raw: str, *, include_time: bool = False) -> str | None:
    """
    Map a raw HF / OpenMed entity group string onto a product label.

    Args:
        raw: Model entity_group or entity string (may include B-/I- prefix).
        include_time: When True, map TIME → TIME (pixel PHI). Otherwise drop TIME.

    Returns:
        Product label, or None if unmapped / dropped.
    """
    key = raw.strip().upper().replace(" ", "_").replace("-", "_")
    if len(key) > 2 and key[1] in {"_", "-"} and key[0] in {"B", "I", "E", "S"}:
        key = key[2:]
    if key == "TIME":
        return "TIME" if include_time else None
    return _TO_SCORED.get(key)


def _run_pipeline(text: str, *, locale: str) -> list[dict[str, Any]]:
    """
    Invoke the token-classification pipeline on text.

    Args:
        text: Non-empty source unicode.
        locale: Locale used to resolve / load the model.

    Returns:
        List of raw entity dicts from the pipeline (empty on failure).
    """
    pipe = _ensure_pipeline(locale)
    if pipe is None:
        return []
    try:
        result = pipe(text)
    except Exception as exc:  # noqa: BLE001
        logger.error("ner: pipeline failed: %s", exc)
        return []
    return [dict(ent) for ent in result]


def _ensure_pipeline(locale: str):
    """
    Load or reuse the global token-classification pipeline for locale.

    Args:
        locale: Locale used to resolve the model id / cache path.

    Returns:
        Hugging Face pipeline instance, or None if unavailable.
    """
    global _PIPE, _PIPE_MODEL_ID, _PIPE_ERROR
    model_id = resolve_model_id(locale)
    if _PIPE is not None and model_id == _PIPE_MODEL_ID:
        return _PIPE
    try:
        _PIPE = load_token_classification_pipeline(model_id)
        _PIPE_MODEL_ID = model_id
        _PIPE_ERROR = None
        logger.info("ner: loaded model %s", model_id)
    except Exception as exc:  # noqa: BLE001
        _PIPE_ERROR = f"Failed to load {model_id}: {exc}"
        logger.error("ner: %s", _PIPE_ERROR)
        _PIPE = None
        _PIPE_MODEL_ID = None
    return _PIPE
