"""Context-only baseline: spaCy NER with no regex / pattern pack."""

from __future__ import annotations

import os

from prototyping.metadata_phi.locale_registry import get_locale_pack
from prototyping.metadata_phi.types import Span


class SpacyNerEngine:
    """General-domain spaCy entities only (PERSON / GPE / LOC / FAC / DATE)."""

    name = "spacy_ner"

    def __init__(self) -> None:
        self._nlp = None
        self._error: str | None = None
        self._model: str | None = None

    def is_available(self) -> bool:
        try:
            import spacy  # noqa: F401
        except ImportError:
            self._error = "spacy not installed (uv sync --group metadata-phi)"
            return False
        return True

    def _ensure(self, locale: str) -> None:
        if self._nlp is not None:
            return
        pack = get_locale_pack(locale)
        model = os.environ.get("METADATA_PHI_SPACY_MODEL", "").strip() or pack.spacy_model
        try:
            import spacy

            self._nlp = spacy.load(model)
            self._model = model
        except Exception as exc:  # noqa: BLE001
            self._error = f"Failed to load spaCy model {model}: {exc}"
            self._nlp = None

    def analyze(self, text: str, *, locale: str = "en_US") -> list[Span]:
        if not self.is_available():
            return []
        self._ensure(locale)
        if self._nlp is None:
            return []
        spans: list[Span] = []
        for ent in self._nlp(text).ents:
            if ent.label_ == "PERSON":
                spans.append(Span("NAME", ent.start_char, ent.end_char, 0.8, "PERSON"))
            elif ent.label_ in {"GPE", "LOC", "FAC"}:
                spans.append(Span("LOCATION", ent.start_char, ent.end_char, 0.7, ent.label_))
            elif ent.label_ == "DATE":
                spans.append(Span("DATE", ent.start_char, ent.end_char, 0.75, "DATE"))
        return spans
