"""Detect PHI spans in free text (ClinicalE5 + phone regex + radiology guard)."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

from anonymizer.controller.ai.embedded_phi.ner.locale_registry import (
    detect_locale_supported,
    get_locale_pack,
)
from anonymizer.controller.ai.embedded_phi.ner.openmed import OpenMedEngine
from anonymizer.controller.ai.embedded_phi.ner.patterns import PatternsEngine
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import SCORED_LABELS, PhiEntity, Span
from anonymizer.controller.ai.embedded_phi.ner.radiology_lexicon import (
    log_name_lexicon_guard,
    radiology_lexicon_name_guard,
)
from anonymizer.controller.ai.embedded_phi.report.content_text import TextSlot

logger = logging.getLogger(__name__)


class HybridEngine:
    """ClinicalE5 for NAME/LOCATION/ID/DATE/EMAIL; locale phone regex; bare TIME ignored."""

    name = "hybrid"

    def __init__(self) -> None:
        self._patterns = PatternsEngine()
        self._neural = OpenMedEngine()
        self._error: str | None = None

    def is_available(self) -> bool:
        return True

    def neural_ready(self) -> bool:
        return self._neural.is_available() and self._neural._error is None

    def analyze(self, text: str, *, locale: str = "en_US") -> list[Span]:
        spans = list(self._patterns.analyze(text, locale=locale))
        if self._neural.is_available():
            neural = self._neural.analyze(text, locale=locale)
            if self._neural._error:
                self._error = self._neural._error
            else:
                spans.extend(neural)
        return spans

_VIEW_CODES = frozenset({"ap", "pa", "lat", "ll", "rl", "oblique", "decub"})
_ANATOMY_BODY = frozenset(
    {
        "breast",
        "chest",
        "abdomen",
        "pelvis",
        "brain",
        "spine",
        "knee",
        "shoulder",
        "head",
        "neck",
        "ankle",
        "wrist",
        "liver",
        "lung",
        "heart",
    }
)
_MODALITY_TOKENS = frozenset({"mr", "mri", "ct", "xr", "dx", "cr", "us", "pt", "nm", "mg"})


def _window(text: str, start: int, end: int, radius: int = 40) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def _span_cf(text: str, span: Span) -> str:
    return text[span.start : span.end].casefold().strip()


def _is_modality_anatomy_name(span_text: str, full_text: str) -> bool:
    cf = span_text.casefold().strip()
    full_cf = full_text.casefold()
    if cf in _ANATOMY_BODY or cf in _MODALITY_TOKENS or cf in _VIEW_CODES:
        return True
    # "MR BREAST" as a whole or BREAST inside an MR/CT protocol line
    if any(p in full_cf for p in ("mr breast", "mri breast", "ct chest", "portable ap", "ap chest", "pa chest")):
        if cf in _ANATOMY_BODY or cf in _MODALITY_TOKENS or "breast" in cf or "chest" in cf:
            return True
    tokens = cf.split()
    return len(tokens) >= 2 and tokens[0] in _MODALITY_TOKENS and tokens[1] in _ANATOMY_BODY


def filter_spans(text: str, spans: list[Span], *, locale: str = "en_US") -> list[Span]:
    """Drop / re-label spans that fail radiology context checks."""
    pack = get_locale_pack(locale)
    id_mod = pack.id_patterns_module
    kept: list[Span] = []

    for span in spans:
        label = span.label
        frag = _span_cf(text, span)
        if not frag:
            continue
        ctx = _window(text, span.start, span.end)

        if label == "NAME":
            if frag in _VIEW_CODES:
                logger.info("NAME guard: dropped OpenMed NAME %r (view code)", frag)
                continue
            lex_hit = radiology_lexicon_name_guard(frag, locale=locale)
            if lex_hit is not None:
                log_name_lexicon_guard(lex_hit)
                continue
            if _is_modality_anatomy_name(frag, text):
                logger.info(
                    "NAME guard: dropped OpenMed NAME %r (modality/anatomy heuristic)",
                    frag,
                )
                continue
            # Short protocol / series description junk (OpenMed NAME fragments)
            if re.fullmatch(
                r"(?i)(?:angio|fluoro|ortho|reformats?|loop|standard|series(?:\s+\d+)?)\b.*",
                frag,
            ) or frag in {"or", "flu", "ang", "io", "bb", "do", "hi", "ar", "ate", "le", "cta", "illa", "luce", "basil", "swan", "ganz"}:
                continue
            if re.search(r"(?i)\b(?:angio|fluoro|ortho|reformats?|#\d+)\b", text) and len(text) <= 64:
                # Whole short field looks like a series/protocol label
                if re.fullmatch(r"(?i)[a-z0-9 #\-./]+", text.strip()):
                    continue
            # De-id redaction placeholders (Open-i XXXX, MIMIC ___)
            if re.fullmatch(r"(?:x{2,}|_{2,})(?:\s+(?:x{2,}|_{2,}))*", frag):
                continue
            if "xxxx" in frag or "___" in frag:
                continue
            # All-caps short anatomy/protocol tokens
            raw = text[span.start : span.end].strip()
            # Single-letter / dotted initials (``N``, ``N.``) when name context is present.
            initial_ok = bool(
                re.fullmatch(r"[A-Za-z]\.?", raw)
                and re.search(
                    r"(?i)\b(?:dr|mr|mrs|ms|prof|sir|dame)\b|"
                    r"(?:^|[\s,;:])[A-Za-z]\.\s*[A-Z][a-z]|"
                    r"[A-Z][a-z]+\s+[A-Za-z]\.?(?:\s|$)",
                    ctx,
                )
            )
            # Drop tiny OpenMed fragments (e.g. "B" from DOB) unless they are name initials.
            if len(raw) <= 2 and not initial_ok:
                continue
            if span.score < 0.75 and len(raw) <= 4 and not initial_ok:
                continue
            if raw.isupper() and len(raw) <= 24 and any(t in frag for t in _ANATOMY_BODY | _MODALITY_TOKENS):
                continue
            if any(
                tok in frag
                for tok in (
                    "hospital",
                    "street",
                    "avenue",
                    "drive",
                    "report",
                    "protocol",
                    "campus",
                    "center",
                    "clinic",
                    "general",
                    "suite",
                    "addendum",
                    "axial",
                    "coronal",
                    "sagittal",
                    "ssn",
                    "mrn",
                    "dob",
                    "pulmonary",
                    "emphysema",
                    "trachea",
                    "mediastinum",
                    "pneumothorax",
                    "atelectasis",
                    "mediport",
                    "nonsmoker",
                )
            ):
                continue
            # Drop spans that end with DOB/MRN cue fragments from spaCy over-reach
            if re.search(r"\b(?:dob|mrn|ssn)\b", frag):
                continue
            kept.append(span)
            continue

        if label == "DATE":
            raw = text[span.start : span.end].strip()
            # UID-shaped digit.dot runs are not dates (even if a date model fired).
            if id_mod.UID_RE.search(raw):
                continue
            # Suppress pure protocol-ish short numbers without date separators / month names
            if re.fullmatch(r"\d{1,3}", frag):
                continue
            # Bare clock times are not Safe Harbor DATE (leave TIME unlabeled).
            if re.fullmatch(r"\d{1,2}[:.]\d{2}(?:[:.]\d{2})?", frag):
                continue
            kept.append(span)
            continue

        if label == "LOCATION":
            if frag in _ANATOMY_BODY or frag in ("left", "right", "bilateral"):
                continue
            if _is_modality_anatomy_name(frag, text) or "mr breast" in frag or "ct chest" in frag:
                continue
            # Require address / facility cues (span or nearby context)
            cues = pack.cue_words.get("location", [])
            ctx_cf = ctx.casefold()
            facility_ok = re.search(
                r"\b(?:hospital|clinic|medical center|campus|center)\b",
                frag,
                re.I,
            )
            street_ok = re.search(
                r"\b(?:street|avenue|boulevard|drive|lane|road|blvd|ave|rd|ln)\b",
                frag,
                re.I,
            )
            # Bare "St"/"Dr" alone is too ambiguous in radiology (not street/doctor)
            street_ok = street_ok or re.search(
                r"\b\d{1,5}\s+\w+.*\b(?:st|dr)\b",
                frag,
                re.I,
            )
            city_zip_ok = re.search(r"[A-Za-z]+,\s*[A-Z]{2}\s*\d{5}", text[span.start : span.end])
            if not (
                facility_ok
                or street_ok
                or city_zip_ok
                or any(c in ctx_cf for c in cues)
            ):
                continue
            kept.append(span)
            continue

        if label == "ID":
            raw = text[span.start : span.end].strip()
            if id_mod.UID_RE.search(raw) or id_mod.UID_RE.search(ctx):
                continue
            if id_mod.TECHNIQUE_CONTEXT_RE.search(ctx) and not any(
                c in ctx.casefold() for c in pack.cue_words.get("patient_identifier", [])
            ):
                # bare technique-adjacent numbers
                if re.fullmatch(r"\d{1,4}", frag):
                    continue
            # Prefer PHONE when phone punctuation dominates
            if id_mod.PHONE_RE.fullmatch(raw) and "ssn" not in ctx.casefold():
                kept.append(
                    Span(
                        label="PHONE",
                        start=span.start,
                        end=span.end,
                        score=span.score,
                        raw_label=span.raw_label or "PHONE_FROM_ID",
                    )
                )
                continue
            kept.append(span)
            continue

        if label == "PHONE":
            raw = text[span.start : span.end].strip()
            if id_mod.UID_RE.search(raw) or id_mod.UID_RE.search(ctx):
                continue
            # Reject bare digit runs without phone punctuation (UID fragments)
            if not id_mod.PHONE_RE.fullmatch(raw):
                continue
            if re.fullmatch(r"\d{3}-\d{2}-\d{4}", raw) and "ssn" in ctx.casefold():
                kept.append(
                    Span(
                        label="ID",
                        start=span.start,
                        end=span.end,
                        score=span.score,
                        raw_label="SSN_FROM_PHONE",
                    )
                )
                continue
            kept.append(span)
            continue

        if label == "EMAIL":
            if "@" not in text[span.start : span.end]:
                continue
            kept.append(span)
            continue

        kept.append(span)

    return _dedupe(kept)


def _name_initial_gap(gap: str) -> bool:
    """True for gaps like ``.``, ``. ``, or spaces between an initial and a surname."""
    return bool(re.fullmatch(r"[\s.]*", gap)) and len(gap) <= 4


def _merge_adjacent(text: str, spans: list[Span]) -> list[Span]:
    """Join same-label spans separated by short whitespace or initial punctuation (``N. Molife``)."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    out = [ordered[0]]
    for span in ordered[1:]:
        prev = out[-1]
        gap = text[prev.end : span.start]
        same = span.label == prev.label
        contiguous = gap == ""
        soft_gap = gap.strip() == "" and len(gap) <= 3
        # NAME: keep ``N`` + ``Molife`` across ``. `` so initials survive filtering.
        name_gap = same and prev.label == "NAME" and _name_initial_gap(gap)
        if same and (contiguous or soft_gap or name_gap):
            out[-1] = Span(
                label=prev.label,
                start=prev.start,
                end=span.end,
                score=max(prev.score, span.score),
                raw_label=prev.raw_label or span.raw_label,
            )
        else:
            out.append(span)
    return out


def _dedupe(spans: list[Span]) -> list[Span]:
    seen: set[tuple[str, int, int]] = set()
    out: list[Span] = []
    for s in sorted(spans, key=lambda x: (x.start, -(x.end - x.start), -x.score)):
        key = (s.label, s.start, s.end)
        if key in seen:
            continue
        # Drop nested same-label spans
        if any(
            o.label == s.label and o.start <= s.start and s.end <= o.end and (o.start, o.end) != (s.start, s.end)
            for o in out
        ):
            continue
        seen.add(key)
        out.append(s)
    return out


_ENGINE: HybridEngine | None = None


def _engine() -> HybridEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = HybridEngine()
    return _ENGINE


def detect_phi(
    text: str,
    *,
    locale: str = "en_US",
    apply_guard: bool = True,
) -> list[PhiEntity]:
    """
    Find PHI in ``text``.

    Returns entities with ``label`` in SCORED_LABELS and character ``start``/``end``.
    Detect locale is the NER model locale (English ``en_US`` in this version), not the
    app UI language — so English NER stays available when the UI is de/es/fr.
    Unsupported detect locales return ``[]``.
    """
    if not text or not str(text).strip():
        return []
    if not detect_locale_supported(locale):
        logger.warning(
            "detect_phi: detect locale %r not supported (en_US only); returning no entities",
            locale,
        )
        return []
    eng = _engine()
    body = str(text)
    spans = eng.analyze(body, locale=locale)
    spans = _merge_adjacent(body, spans)
    if apply_guard:
        spans = filter_spans(body, spans, locale=locale)
    return [s for s in spans if s.label in SCORED_LABELS]


@dataclass(slots=True)
class SlotScan:
    slot: TextSlot
    entities: list[PhiEntity]


def scan_slots(slots: Iterable[TextSlot], *, locale: str = "en_US") -> list[SlotScan]:
    """Run ``detect_phi`` on each slot independently (spans never cross slots)."""
    return [SlotScan(slot, detect_phi(slot.text, locale=locale)) for slot in slots if slot.text.strip()]


def entity_counts(scans: Iterable[SlotScan]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for scan in scans:
        for ent in scan.entities:
            counts[ent.label] = counts.get(ent.label, 0) + 1
    return counts


def removed_texts(scans: Iterable[SlotScan]) -> list[str]:
    """PHI-only capture strings: the *original* entity text, de-duplicated, first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for scan in scans:
        for ent in scan.entities:
            frag = ent.text_of(scan.slot.text).strip()
            if frag and frag not in seen:
                seen.add(frag)
                out.append(frag)
    return out
