"""Report PDF/SR text NER: OpenMed + phone regex only; clear in/out logs."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from anonymizer.controller.ai.embedded_phi.ner.detect_phi import detect_phi
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import PhiEntity, Span

logger = logging.getLogger(__name__)

_LOG = "report_ner"


def format_phi_xml(text: str, spans: Sequence[Span | PhiEntity]) -> str:
    """
    Render ``text`` with non-overlapping PHI tags (longer spans first).

    Example: ``Patient <NAME>Jane Doe</NAME> phone <PHONE>(404) 555-0162</PHONE>``
    """
    if not text:
        return ""
    ordered = sorted(
        (s for s in spans if s.end > s.start and 0 <= s.start < s.end <= len(text)),
        key=lambda s: (s.start, -(s.end - s.start)),
    )
    chosen: list[Span | PhiEntity] = []
    for span in ordered:
        if any(not (span.end <= c.start or span.start >= c.end) for c in chosen):
            continue
        chosen.append(span)
    chosen.sort(key=lambda s: s.start)
    parts: list[str] = []
    cursor = 0
    for span in chosen:
        if span.start > cursor:
            parts.append(text[cursor : span.start])
        frag = text[span.start : span.end]
        parts.append(f"<{span.label}>{frag}</{span.label}>")
        cursor = span.end
    if cursor < len(text):
        parts.append(text[cursor:])
    return "".join(parts)


def analyze_report_text(
    text: str,
    *,
    locale: str = "en_US",
    unit: str = "text",
) -> list[PhiEntity]:
    """
    Run HybridEngine (OpenMed + PHONE_RE) without radiology ``filter_spans``.

    Logs the exact NER input and an XML-tagged view of the output.
    """
    body = str(text or "")
    logger.info("%s: in %s\n<<<\n%s\n>>>", _LOG, unit, body)
    if not body.strip():
        logger.info("%s: out %s\n<<<\n>>>\n", _LOG, unit)
        return []
    ents = detect_phi(body, locale=locale, apply_guard=False)
    tagged = format_phi_xml(body, ents)
    logger.info("%s: out %s\n<<<\n%s\n>>>", _LOG, unit, tagged)
    return ents
