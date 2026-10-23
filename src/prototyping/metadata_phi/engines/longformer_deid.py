"""Long-context clinical DeID adapter (offline-pinnable via locale / env / cache)."""

from prototyping.metadata_phi.engines.label_map import to_scored_label
from prototyping.metadata_phi.engines.regex_spacy import RegexSpacyEngine
from prototyping.metadata_phi.model_cache import (
    load_token_classification_pipeline,
    resolve_model_id,
)
from prototyping.metadata_phi.types import Span


class LongformerDeidEngine:
    """
    Uses locale ``hf_longformer_model`` (currently OBI RoBERTa stand-in until a
    Longformer checkpoint is pinned). Supports the same cache/env overrides as
    ``obi_deid``.
    """

    name = "longformer_deid"

    def __init__(self) -> None:
        self._pipe = None
        self._error: str | None = None
        self._fallback = RegexSpacyEngine(use_spacy=False)

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
        model_id = resolve_model_id(locale, kind="longformer")
        try:
            self._pipe = load_token_classification_pipeline(model_id)
        except Exception as exc:
            self._error = f"Failed to load {model_id}: {exc}"
            self._pipe = None

    def analyze(self, text: str, *, locale: str = "en_US") -> list[Span]:
        # No pattern merge — keep clinical-model scores uncontaminated.
        if not self.is_available():
            return []
        self._ensure(locale)
        if self._pipe is None:
            return []

        spans: list[Span] = []
        window = 1800
        overlap = 100
        for start in range(0, max(len(text), 1), window - overlap):
            chunk = text[start : start + window]
            if not chunk:
                break
            for ent in self._pipe(chunk):
                raw = ent.get("entity_group") or ent.get("entity") or ""
                scored = to_scored_label(str(raw))
                if scored is None:
                    continue
                spans.append(
                    Span(
                        label=scored,
                        start=start + int(ent["start"]),
                        end=start + int(ent["end"]),
                        score=float(ent.get("score", 0.5)),
                        raw_label=str(raw),
                    )
                )
        return spans
