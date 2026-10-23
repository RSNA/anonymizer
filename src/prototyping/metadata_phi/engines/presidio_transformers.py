"""Presidio analyzer for free-text metadata strings and radiology reports.

UID handling is **field / span shaped**, not “turn off date and phone globally”:
Presidio DATE_TIME and phone stay on for report-like text; DICOM UID tags are
not scanned, and UID-shaped spans are dropped after analysis.
"""

import os

from prototyping.metadata_phi.engines.label_map import to_scored_label
from prototyping.metadata_phi.engines.presidio_patterns import build_pattern_recognizers
from prototyping.metadata_phi.engines.regex_spacy import RegexSpacyEngine
from prototyping.metadata_phi.locale_registry import get_locale_pack
from prototyping.metadata_phi.types import Span


class PresidioTransformersEngine:
    """
    Presidio with DATE_TIME + phone + email enabled for free text / reports.

    Locale pattern pack supplements MRN/SSN cues. Regex pack fills value-accurate
    ID gaps. Set ``METADATA_PHI_SPACY_MODEL`` to override the spaCy model id.
    """

    name = "presidio_transformers"

    def __init__(self) -> None:
        self._analyzer = None
        self._error: str | None = None
        self._fallback = RegexSpacyEngine(use_spacy=False)
        self._built_locale: str | None = None

    def is_available(self) -> bool:
        try:
            import presidio_analyzer  # noqa: F401
        except ImportError:
            self._error = "presidio-analyzer not installed (uv sync --group metadata-phi)"
            return False
        return True

    def _build(self, locale: str) -> None:
        if self._analyzer is not None and self._built_locale == locale:
            return
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        pack = get_locale_pack(locale)
        model_candidates = [
            os.environ.get("METADATA_PHI_SPACY_MODEL", "").strip(),
            pack.spacy_model,
            "en_core_web_sm",
        ]
        nlp_engine = None
        last_exc: Exception | None = None
        for model_name in model_candidates:
            if not model_name:
                continue
            conf = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model_name}],
            }
            try:
                provider = NlpEngineProvider(nlp_configuration=conf)
                nlp_engine = provider.create_engine()
                break
            except Exception as exc:  # noqa: BLE001 — try next model
                last_exc = exc
                nlp_engine = None

        if nlp_engine is None:
            self._error = f"Presidio NLP engine unavailable: {last_exc}"
            self._analyzer = None
            return

        # Full English predefined set (includes DATE_TIME, phone, email, SSN, …)
        # plus locale cue patterns. UID *fields* are skipped upstream; UID-shaped
        # spans are dropped in analyze().
        registry = RecognizerRegistry()
        registry.load_predefined_recognizers(languages=["en"], nlp_engine=nlp_engine)
        for recognizer in build_pattern_recognizers(locale):
            registry.add_recognizer(recognizer)

        self._analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            registry=registry,
            supported_languages=["en"],
        )
        self._built_locale = locale

    def analyze(self, text: str, *, locale: str = "en_US") -> list[Span]:
        if not self.is_available():
            return self._fallback.analyze(text, locale=locale)
        self._build(locale)
        if self._analyzer is None:
            return self._fallback.analyze(text, locale=locale)

        pack = get_locale_pack(locale)
        uid_re = pack.id_patterns_module.UID_RE

        results = self._analyzer.analyze(text=text, language="en")
        spans: list[Span] = []
        for r in results:
            scored = to_scored_label(r.entity_type)
            if scored is None:
                continue
            frag = text[r.start : r.end]
            # Never treat a DICOM UID (or a hit wholly inside one) as PHI.
            if uid_re.search(frag):
                continue
            spans.append(
                Span(
                    label=scored,
                    start=r.start,
                    end=r.end,
                    score=float(r.score or 0.5),
                    raw_label=r.entity_type,
                )
            )
        # Locale regex pack for cue-accurate MRN / date / address forms.
        spans.extend(self._fallback.analyze(text, locale=locale))
        return spans
