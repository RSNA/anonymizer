"""Analyze text or DICOM paths with an engine + radiology guard."""

from __future__ import annotations

from pathlib import Path

from prototyping.metadata_phi.engines.base import PhiEngine, get_engine
from prototyping.metadata_phi.extract import extract_from_file, is_uid_metadata_tag
from prototyping.metadata_phi.guard import filter_spans
from prototyping.metadata_phi.types import Span, TextChunk


def analyze_text(
    text: str,
    *,
    engine: str | PhiEngine = "regex_spacy",
    locale: str = "en_US",
    apply_guard: bool = True,
) -> list[Span]:
    eng = get_engine(engine) if isinstance(engine, str) else engine
    spans = eng.analyze(text, locale=locale)
    if apply_guard:
        spans = filter_spans(text, spans, locale=locale)
    return spans


def analyze_file(
    path: str | Path,
    *,
    engine: str | PhiEngine = "regex_spacy",
    locale: str = "en_US",
    apply_guard: bool = True,
) -> list[tuple[TextChunk, list[Span]]]:
    chunks = extract_from_file(path, locale=locale)
    eng = get_engine(engine) if isinstance(engine, str) else engine
    out: list[tuple[TextChunk, list[Span]]] = []
    for chunk in chunks:
        # Skip DICOM UID attributes — date/phone detectors must not run on them.
        if is_uid_metadata_tag(chunk.tag_or_path):
            out.append((chunk, []))
            continue
        spans = eng.analyze(chunk.text, locale=locale)
        if apply_guard:
            spans = filter_spans(chunk.text, spans, locale=locale)
        out.append((chunk, spans))
    return out
