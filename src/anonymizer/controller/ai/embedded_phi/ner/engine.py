"""Model-only PHI NER: unicode text in → labeled spans; blank or synthetic replace.
Uses OpenMed ClinicalE5 token-classification only (no lexicon / phone regex).
Product labels: FIRST_NAME, LAST_NAME, LOCATION, ID,
PHONE, DATE, EMAIL. Model spans are returned exactly as classified

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

detect_entities(text: str, *, locale: str='en_US') -> list[Entity]
    Run OpenMed token-classification on text.

detect_entities_in_segments(segments: Sequence[str], *, locale: str='en_US', max_chars: int=_DEFAULT_SEGMENT_MAX_CHARS, scan_fn: Callable[[str], list[Entity]] | None=None) -> list[list[Entity]]
    Run a text PHI scanner on **chunks of whole fields**.

replace_entities(text: str, entities: Sequence[Entity] | None=None, *, mode: ReplaceMode='blank', locale: str='en_US', project_id: str='default', anon_ptid: str='ANON0000') -> tuple[str, list[Entity]]
    Replace PHI spans in text right-to-left.

detect_locale_supported(locale: str) -> bool
    Return whether locale has a supported OpenMed detect pack.
"""
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pprint import pformat
from typing import Any, Literal

from anonymizer.controller.ai.embedded_phi.ner.cache import (
    load_token_classification_pipeline,
    ner_ready,
    resolve_model_id,
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Entity:
    """One PHI span: product label plus character offsets into the source string.

    score is the model's softmax confidence for raw_label (fine-grained HF
    class), not for the mapped product label. No score threshold is applied —
    see module README. UI hover shows label only.

    replacement: when set (metadata PHI tagged with a DICOM keyword as
    label), replace_entities always writes this string — the anonymized
    DICOM value — instead of blanking or generate_synthetic_phi.
    """

    label: str
    start: int
    end: int
    score: float = 1.0
    raw_label: str = ""
    replacement: str | None = None

    def text_of(self, source: str) -> str:
        """
        Return the substring of source covered by this entity.

        Args:
            source: Full source string into which start/end index.

        Returns:
            Slice source[start:end].
        """
        return source[self.start : self.end]

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize this entity to a plain dict.

        Returns:
            Mapping of field names to values (via dataclasses.asdict).
        """
        return asdict(self)


def detect_entities(text: str, *, locale: str = "en_US") -> list[Entity]:
    """
    Run OpenMed token-classification on text.

    Product-labeled entities with start/end into text. No lexicon,
    phone-regex, merging, or other post-filters — the model's spans are
    returned exactly as classified (label mapping only).

    Logging: **INFO** traces the key processing steps in order —
    step 1/4 input, step 2/4 model raw spans, step 3/4 label map
    (kept + dropped with reasons), step 4/4 tagged result.

    Args:
        text: Source unicode to scan.
        locale: NER locale pack (default en_US).

    Returns:
        List of Entity spans (may be empty if models missing or text blank).
    """
    body = str(text or "")
    logger.info(f"ner: step 1/4 input locale={locale} chars={len(body)}\n{_trace(body)}")

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
        f"{pformat(_raw_ents_for_log(raw_ents, body), sort_dicts=False)}"
    )

    mapped: list[Entity] = []
    dropped_rows: list[dict[str, Any]] = []
    for ent in raw_ents:
        raw = str(ent.get("entity_group") or ent.get("entity") or "")
        scored = _to_scored_label(raw)
        if scored is None or scored not in SCORED_LABELS:
            start, end = int(ent["start"]), int(ent["end"])
            dropped_rows.append(
                {
                    "text": body[start:end],
                    "start": start,
                    "end": end,
                    "score": _score_for_log(float(ent.get("score", 0.5))),
                    "raw_label": raw,
                    "reason": f"no product label for raw label {raw!r}",
                }
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
        f"(product labels={', '.join(SCORED_LABELS)})\n"
        f"kept={pformat(_entities_for_log(mapped, body), sort_dicts=False)}\n"
        f"dropped={pformat(dropped_rows, sort_dicts=False)}"
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
    pass detect_phi_in_text so study-PHI matching + NER share one join pass.

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
) -> tuple[str, list[Entity]]:
    """
    Replace PHI spans in text right-to-left.

    If entities is omitted, runs detect_entities first.
    Spans with Entity.replacement (report metadata PHI) always write that
    string. Remaining spans: blank clears; synth uses
    generate_synthetic_phi and offline pools.

    Args:
        text: Source unicode containing PHI spans.
        entities: Spans to replace; None triggers detect first.
        mode: blank or synth (NER spans only; metadata uses replacement).
        locale: Locale for detect (if needed) and synthetic pools.
        project_id: Seed namespace for synthetic values.
        anon_ptid: Anonymized patient id seed for synthetic values.

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
        logger.info("ner: replace result\n%s", _trace(body))
        return body, []

    meta_n = sum(1 for e in used if e.replacement is not None)
    logger.debug(
        "ner: replace apply %d span(s) right-to-left mode=%s "
        "(metadata_replacement=%d ner=%d)\n%s",
        len(used),
        mode,
        meta_n,
        len(used) - meta_n,
        pformat(_entities_for_log(used, body), sort_dicts=False),
    )
    ordinals: dict[str, int] = {}
    replacements: list[tuple[Entity, str]] = []
    for ent in sorted(used, key=lambda e: (e.start, e.end)):
        ord_i = ordinals.get(ent.label, 0)
        ordinals[ent.label] = ord_i + 1
        # Metadata PHI (DICOM keyword label): always write anonymized tag value.
        if ent.replacement is not None:
            replacements.append((ent, str(ent.replacement)))
            continue
        if mode == "blank":
            replacements.append((ent, ""))
            continue
        replacements.append(
            (
                ent,
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
    out = body
    for ent, repl in sorted(replacements, key=lambda x: x[0].start, reverse=True):
        out = out[: ent.start] + repl + out[ent.end :]
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
    logger.info("ner: replace result\n%s", _trace(out))
    return out, used


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


def _raw_ents_for_log(
    raw_ents: Sequence[dict[str, Any]], source: str = ""
) -> list[dict[str, Any]]:
    """
    Copy pipeline dicts for logging, adding the covered source text.

    Args:
        raw_ents: Raw Hugging Face token-classification entity dicts.
        source: Source unicode the span offsets index into (text is only
            added when both offsets are valid into it).

    Returns:
        Shallow copies suitable for pformat (originals unchanged), with
        scores rounded to two significant digits.
    """
    out: list[dict[str, Any]] = []
    for ent in raw_ents:
        row = dict(ent)
        if "score" in row:
            row["score"] = _score_for_log(row["score"])
        start, end = ent.get("start"), ent.get("end")
        if source and isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(source):
            row["text"] = source[start:end]
        out.append(row)
    return out


def _entities_for_log(entities: Sequence[Entity], source: str) -> list[dict[str, Any]]:
    """
    Serialize product entities for pformat logging (span text + rounded score).

    Args:
        entities: Product Entity spans.
        source: Source unicode for text slices.

    Returns:
        List of plain dicts for readable logs.
    """
    rows: list[dict[str, Any]] = []
    for ent in entities:
        row: dict[str, Any] = {
            "label": ent.label,
            "text": source[ent.start : ent.end],
            "start": ent.start,
            "end": ent.end,
            "score": _score_for_log(ent.score),
            "raw_label": ent.raw_label,
        }
        if ent.replacement is not None:
            row["replacement"] = ent.replacement
        rows.append(row)
    return rows


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


def _to_scored_label(raw: str) -> str | None:
    """
    Map a raw HF / OpenMed entity group string onto a product label.

    Args:
        raw: Model entity_group or entity string (may include B-/I- prefix).

    Returns:
        Product label in SCORED_LABELS, or None if unmapped / dropped (e.g. TIME).
    """
    key = raw.strip().upper().replace(" ", "_").replace("-", "_")
    if len(key) > 2 and key[1] in {"_", "-"} and key[0] in {"B", "I", "E", "S"}:
        key = key[2:]
    if key == "TIME":
        return None
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


