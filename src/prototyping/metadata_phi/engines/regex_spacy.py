"""Hybrid baseline: locale regex packs + optional spaCy NER."""

from __future__ import annotations

import os
import re

from prototyping.metadata_phi.locale_registry import get_locale_pack
from prototyping.metadata_phi.types import Span

# Title-bearing / labeled names when spaCy is unavailable.
_TITLED_PERSON_RE = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Prof)\.?\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z]+)?)\b"
)
_LABELED_NAME_RE = re.compile(
    r"\b(?:Patient|Pt|Name)\s*:\s*([A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z]+){0,2})\b"
)
_PATIENT_NAME_RE = re.compile(
    r"\b(?:[Pp]atient|[Pp]t)\s+(?!id\b)([A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z]+){0,2})\b"
)


def _spacy_enabled() -> bool:
    return os.environ.get("METADATA_PHI_USE_SPACY", "").strip().lower() in {"1", "true", "yes"}


class RegexSpacyEngine:
    """
    Locale regex pack is always on.

    spaCy NER is **opt-in** via ``METADATA_PHI_USE_SPACY=1`` — general-domain
    ``en_core_web_sm`` otherwise adds DATE/NAME false positives on radiology prose.
    """

    name = "regex_spacy"

    def __init__(self, *, use_spacy: bool | None = None) -> None:
        self._nlp = None
        self._spacy_tried = False
        self._use_spacy = _spacy_enabled() if use_spacy is None else use_spacy

    def is_available(self) -> bool:
        return True  # regex pack always works; spaCy optional

    def _ensure_spacy(self, model: str) -> None:
        if not self._use_spacy or self._spacy_tried:
            return
        self._spacy_tried = True
        try:
            import spacy

            self._nlp = spacy.load(model)
        except Exception:
            self._nlp = None

    def analyze(self, text: str, *, locale: str = "en_US") -> list[Span]:
        pack = get_locale_pack(locale)
        id_mod = pack.id_patterns_module
        date_mod = pack.date_patterns_module
        spans: list[Span] = []
        for m in date_mod.DATE_RE.finditer(text):
            spans.append(Span("DATE", m.start(), m.end(), 0.9, "DATE_RE"))

        for m in id_mod.EMAIL_RE.finditer(text):
            spans.append(Span("EMAIL", m.start(), m.end(), 0.95, "EMAIL_RE"))

        for m in id_mod.PHONE_RE.finditer(text):
            spans.append(Span("PHONE", m.start(), m.end(), 0.9, "PHONE_RE"))

        # US SSN: hyphenated always; 9-digit only with SSN cue nearby
        for m in re.finditer(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)", text):
            spans.append(Span("ID", m.start(), m.end(), 0.95, "US_SSN"))
        for m in re.finditer(r"(?<!\d)\d{9}(?!\d)", text):
            ctx = text[max(0, m.start() - 32) : m.end() + 8].casefold()
            if "ssn" in ctx or "social security" in ctx:
                spans.append(Span("ID", m.start(), m.end(), 0.9, "US_SSN_BARE"))

        for m in id_mod.MRN_VALUE_RE.finditer(text):
            spans.append(
                Span(
                    "ID",
                    m.start(1),
                    m.end(1),
                    0.9,
                    "MRN_CUE",
                )
            )

        for m in id_mod.ID_HASH_RE.finditer(text):
            spans.append(Span("ID", m.start(1), m.end(1), 0.85, "ID_HASH"))

        # LOCATION: street + optional suite + city/state/zip (longer street suffixes first)
        for m in re.finditer(
            r"\b\d{1,5}\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+"
            r"(?:Street|Avenue|Boulevard|Drive|Lane|Road|Blvd|Ave|Rd|Ln|Dr|St)\.?"
            r"(?:[,\s]+(?:Suite|Ste\.?|Apt\.?)\s+[A-Za-z0-9\-]+)?"
            r"(?:[,\s]+[A-Z][A-Za-z]+(?:,\s*[A-Z]{2})?(?:\s+\d{5}(?:-\d{4})?)?)?",
            text,
        ):
            spans.append(Span("LOCATION", m.start(), m.end(), 0.85, "ADDRESS_RE"))

        for m in re.finditer(
            r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
            r"(?:Medical Center|Hospital(?:\s+Center)?|Clinic)(?:\s+campus)?\b",
            text,
        ):
            spans.append(Span("LOCATION", m.start(), m.end(), 0.75, "FACILITY"))

        # Only emit city/state/zip when not already inside a longer ADDRESS_RE span
        addr_spans = [s for s in spans if s.label == "LOCATION"]
        for match in re.finditer(
            r"\b([A-Z][a-z]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\b",
            text,
        ):
            m_start, m_end = match.start(), match.end()
            if any(s.start <= m_start and m_end <= s.end for s in addr_spans):
                continue
            spans.append(Span("LOCATION", m_start, m_end, 0.8, "CITY_STATE_ZIP"))

        self._ensure_spacy(pack.spacy_model)
        if self._nlp is not None:
            doc = self._nlp(text)
            for ent in doc.ents:
                label = ent.label_
                if label == "PERSON":
                    spans.append(Span("NAME", ent.start_char, ent.end_char, 0.8, "PERSON"))
                elif label in {"GPE", "LOC", "FAC"}:
                    spans.append(Span("LOCATION", ent.start_char, ent.end_char, 0.7, label))
                elif label == "DATE":
                    spans.append(Span("DATE", ent.start_char, ent.end_char, 0.75, "DATE"))
        else:
            for m in _LABELED_NAME_RE.finditer(text):
                spans.append(Span("NAME", m.start(1), m.end(1), 0.75, "LABELED_NAME"))
            for m in _PATIENT_NAME_RE.finditer(text):
                spans.append(Span("NAME", m.start(1), m.end(1), 0.7, "NAME_CUE"))
            for m in _TITLED_PERSON_RE.finditer(text):
                spans.append(Span("NAME", m.start(1), m.end(1), 0.7, "TITLED_PERSON"))

        return spans
