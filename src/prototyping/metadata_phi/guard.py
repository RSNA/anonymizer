"""Radiology-context guard: suppress false positives for English (locale-keyed)."""

import re

from prototyping.metadata_phi.locale_registry import get_locale_pack, load_ocr_whitelist_terms
from prototyping.metadata_phi.types import Span

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
    whitelist = load_ocr_whitelist_terms(locale)
    id_mod = pack.id_patterns_module
    kept: list[Span] = []

    for span in spans:
        label = span.label
        frag = _span_cf(text, span)
        if not frag:
            continue
        ctx = _window(text, span.start, span.end)

        if label == "NAME":
            if frag in pack.radiology_deny or frag in whitelist or frag in _VIEW_CODES:
                continue
            if _is_modality_anatomy_name(frag, text):
                continue
            # De-id redaction placeholders (Open-i XXXX, MIMIC ___)
            if re.fullmatch(r"(?:x{2,}|_{2,})(?:\s+(?:x{2,}|_{2,}))*", frag):
                continue
            if "xxxx" in frag or "___" in frag:
                continue
            # All-caps short anatomy/protocol tokens
            raw = text[span.start : span.end].strip()
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
            # Accept locale calendar patterns OR longer month-name dates from NLP
            if pack.date_patterns_module.DATE_RE.fullmatch(raw):
                kept.append(span)
                continue
            if re.search(
                r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
                raw,
            ) and re.search(r"\d{4}|\d{1,2}", raw):
                kept.append(span)
                continue
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
