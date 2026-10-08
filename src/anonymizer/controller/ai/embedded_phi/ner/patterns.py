"""Locale regex pack for PHONE only (ClinicalE5 owns other labels)."""

from __future__ import annotations

from anonymizer.controller.ai.embedded_phi.ner.locale_registry import get_locale_pack
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import Span


class PatternsEngine:
    """Phone numbers only — OpenMed phone recall is weak on eval."""

    name = "patterns"

    def is_available(self) -> bool:
        return True

    def analyze(self, text: str, *, locale: str = "en_US") -> list[Span]:
        pack = get_locale_pack(locale)
        id_mod = pack.id_patterns_module
        spans: list[Span] = []
        for m in id_mod.PHONE_RE.finditer(text):
            spans.append(Span("PHONE", m.start(), m.end(), 0.9, "PHONE_RE"))
        return spans
