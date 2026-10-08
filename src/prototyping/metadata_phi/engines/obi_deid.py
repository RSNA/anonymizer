"""HuggingFace clinical DeID token classifier (offline-pinnable).

Default locale model: OpenMed ClinicalE5-Small (~33M). Override with
``METADATA_PHI_DEID_MODEL`` (e.g. ``obi/deid_roberta_i2b2``).
"""

from __future__ import annotations

import os

from prototyping.metadata_phi.engines.label_map import to_scored_label
from prototyping.metadata_phi.engines.regex_spacy import RegexSpacyEngine
from prototyping.metadata_phi.model_cache import (
    load_token_classification_pipeline,
    resolve_model_id,
)
from prototyping.metadata_phi.types import Span


def _merge_patterns() -> bool:
    """Off by default so fair evals are not polluted by regex hits."""
    return os.environ.get("METADATA_PHI_OBI_MERGE_PATTERNS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


class ObiDeidEngine:
    name = "obi_deid"

    def __init__(self, *, merge_patterns: bool | None = None) -> None:
        self._pipe = None
        self._error: str | None = None
        self._fallback = RegexSpacyEngine(use_spacy=False)
        self._model_id: str | None = None
        self._merge_patterns = _merge_patterns() if merge_patterns is None else merge_patterns

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            self._error = "transformers/torch not installed (uv sync --group metadata-phi)"
            return False
        return True

    def _ensure(self, locale: str) -> None:
        if self._pipe is not None:
            return
        self._model_id = resolve_model_id(locale, kind="deid")
        try:
            self._pipe = load_token_classification_pipeline(self._model_id)
        except Exception as exc:
            self._error = f"Failed to load {self._model_id}: {exc}"
            self._pipe = None

    def analyze(self, text: str, *, locale: str = "en_US") -> list[Span]:
        if not self.is_available():
            return self._fallback.analyze(text, locale=locale) if self._merge_patterns else []
        self._ensure(locale)
        if self._pipe is None:
            return self._fallback.analyze(text, locale=locale) if self._merge_patterns else []

        spans: list[Span] = []
        for ent in self._pipe(text):
            raw = ent.get("entity_group") or ent.get("entity") or ""
            scored = to_scored_label(str(raw))
            if scored is None:
                continue
            spans.append(
                Span(
                    label=scored,
                    start=int(ent["start"]),
                    end=int(ent["end"]),
                    score=float(ent.get("score", 0.5)),
                    raw_label=str(raw),
                )
            )
        if self._merge_patterns:
            spans.extend(self._fallback.analyze(text, locale=locale))
        return spans
