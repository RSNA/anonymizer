"""Run product PDF detect with injectable EasyOCR + OpenMed pipeline kwargs."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from pydicom import dcmread

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunParams:
    """API knobs only (EasyOCR readtext + OpenMed/HF token-classification)."""

    easyocr: dict[str, Any] = field(default_factory=dict)
    aggregation_strategy: str = "max"
    min_score: float = 0.0

    def key(self) -> str:
        parts = [f"agg={self.aggregation_strategy}", f"min_score={self.min_score}"]
        for k in sorted(self.easyocr):
            parts.append(f"{k}={self.easyocr[k]!r}")
        return " ".join(parts)


@dataclass
class PredHit:
    page_index: int
    label: str
    text: str
    source: str
    rect: tuple[float, float, float, float]
    start: int | None = None
    end: int | None = None


@dataclass
class RunResult:
    params: RunParams
    hits: list[PredHit]
    pdf_bytes: bytes


def _pdf_bytes_from_fixture(path: Path) -> bytes:
    path = path.expanduser().resolve()
    if path.suffix.lower() == ".pdf":
        return path.read_bytes()
    ds = dcmread(path)
    from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import (
        encapsulated_pdf_bytes,
    )

    raw = encapsulated_pdf_bytes(ds)
    if not raw:
        raise ValueError(f"No Encapsulated PDF in {path}")
    return raw


def _make_ocr_reader():
    from easyocr import Reader

    from anonymizer.controller.ai.embedded_phi.pixel.cache import OCR_LANGS, OCR_MODEL_DIR

    return Reader(
        lang_list=list(OCR_LANGS),
        model_storage_directory=str(OCR_MODEL_DIR),
        verbose=False,
    )


@contextmanager
def _inject_params(params: RunParams) -> Iterator[None]:
    """Patch report EasyOCR overrides + OpenMed pipeline load for one run."""
    import anonymizer.controller.ai.embedded_phi.ner.cache as ner_cache
    import anonymizer.controller.ai.embedded_phi.ner.detect_phi as detect_phi_mod
    import anonymizer.controller.ai.embedded_phi.ner.openmed as openmed_mod
    import anonymizer.controller.ai.embedded_phi.pixel.detect_text as detect_text_mod

    from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
        REPORT_PIXEL_EASYOCR_OVERRIDES,
    )

    prev_overrides = dict(REPORT_PIXEL_EASYOCR_OVERRIDES)
    merged = {**prev_overrides, **params.easyocr}
    REPORT_PIXEL_EASYOCR_OVERRIDES.clear()
    REPORT_PIXEL_EASYOCR_OVERRIDES.update(merged)

    orig_load = ner_cache.load_token_classification_pipeline
    orig_analyze = openmed_mod.OpenMedEngine.analyze
    min_score = params.min_score
    agg = params.aggregation_strategy

    def load_pipe(model_id: str):
        from transformers import (
            AutoModelForTokenClassification,
            AutoTokenizer,
            pipeline,
        )

        lfo = ner_cache.local_files_only()
        tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=lfo)
        model = AutoModelForTokenClassification.from_pretrained(
            model_id, local_files_only=lfo
        )
        return pipeline(
            "token-classification",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy=agg,
        )

    def analyze(self, text: str, *, locale: str = "en_US"):
        spans = orig_analyze(self, text, locale=locale)
        if min_score <= 0:
            return spans
        return [s for s in spans if float(s.score or 0.0) >= min_score]

    ner_cache.load_token_classification_pipeline = load_pipe  # type: ignore[assignment]
    openmed_mod.OpenMedEngine.analyze = analyze  # type: ignore[method-assign]
    # Force fresh HybridEngine + OpenMed pipe for this aggregation strategy.
    detect_phi_mod._ENGINE = None

    try:
        yield
    finally:
        REPORT_PIXEL_EASYOCR_OVERRIDES.clear()
        REPORT_PIXEL_EASYOCR_OVERRIDES.update(prev_overrides)
        ner_cache.load_token_classification_pipeline = orig_load  # type: ignore[assignment]
        openmed_mod.OpenMedEngine.analyze = orig_analyze  # type: ignore[method-assign]
        detect_phi_mod._ENGINE = None
        # Drop cached pipe on any lingering engines
        _ = detect_text_mod  # keep import used for side-effect clarity


def run_detect(fixture: Path, params: RunParams, *, locale: str = "en_US") -> RunResult:
    """Detect PDF PHI hits with the given API params."""
    from anonymizer.controller.ai.embedded_phi.report.pdf_ocr import detect_pdf_hits

    pdf_bytes = _pdf_bytes_from_fixture(fixture)
    reader = _make_ocr_reader()
    with _inject_params(params):
        _layouts, hits = detect_pdf_hits(pdf_bytes, reader, locale=locale)
    pred = [
        PredHit(
            page_index=h.page_index,
            label=h.label,
            text=h.text or "",
            source=h.source,
            rect=tuple(h.rect),  # type: ignore[arg-type]
            start=h.start,
            end=h.end,
        )
        for h in hits
    ]
    logger.info("report_phi run %s → %d hits", params.key(), len(pred))
    return RunResult(params=params, hits=pred, pdf_bytes=pdf_bytes)
