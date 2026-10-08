"""Encapsulated PDF text-layer PHI detect (no embedded-image OCR)."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Sequence

from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import (
    PdfPageLayout,
    extract_pdf_layout,
    rects_for_span,
)
from anonymizer.controller.ai.embedded_phi.report.hits import ReportHit, hit_key
from anonymizer.controller.ai.embedded_phi.report.report_ner import analyze_report_text

logger = logging.getLogger(__name__)

_LOG = "report_detect"

ProgressFn = Callable[[str], None]


def _hit_label_summary(hits: Sequence[ReportHit]) -> str:
    if not hits:
        return "none"
    counts = Counter(h.label for h in hits)
    return ", ".join(f"{lab}={counts[lab]}" for lab in sorted(counts))


def detect_native_pdf_hits(
    layouts: list[PdfPageLayout],
    *,
    locale: str = "en_US",
    progress: ProgressFn | None = None,
) -> list[ReportHit]:
    """Run report NER on each page's native text; map spans to page rects."""
    from anonymizer.utils.translate import _

    text_pages = sum(1 for layout in layouts if layout.text.strip())
    if progress is not None:
        progress(_("Detecting PHI in text (NER)…"))
    logger.info("%s: NER native text — begin (%d page layer(s))", _LOG, text_pages)

    hits: list[ReportHit] = []
    for layout in layouts:
        page_no = layout.page_index + 1
        if not layout.text.strip():
            logger.info("%s: NER native page %d — skip (empty text layer)", _LOG, page_no)
            continue
        if progress is not None:
            progress(_("Detecting PHI in text (NER)…") + f" — {_('page')} {page_no}")
        ents = analyze_report_text(
            layout.text, locale=locale, unit=f"page={layout.page_index}"
        )
        page_hits: list[ReportHit] = []
        for ent in ents:
            frag = layout.text[ent.start : ent.end]
            rects = rects_for_span(layout, ent.start, ent.end, top_left=True)
            if len(rects) > 1:
                logger.info(
                    "%s: native_ent multi_rect label=%s text=%r rects=%d",
                    _LOG,
                    ent.label,
                    frag,
                    len(rects),
                )
            for rect in rects:
                page_hits.append(
                    ReportHit(
                        page_index=layout.page_index,
                        text=frag,
                        label=ent.label,
                        rect=rect,
                        source="native",
                        key=hit_key(layout.page_index, "native", ent.start, ent.end, frag),
                        start=ent.start,
                        end=ent.end,
                    )
                )
        logger.info(
            "%s: NER native page %d → chars=%d ents=%d hits=%d (%s)",
            _LOG,
            page_no,
            len(layout.text),
            len(ents),
            len(page_hits),
            _hit_label_summary(page_hits),
        )
        hits.extend(page_hits)
    logger.info(
        "%s: NER native text complete — hits=%d (%s)",
        _LOG,
        len(hits),
        _hit_label_summary(hits),
    )
    return hits


def detect_pdf_hits(
    pdf_bytes: bytes,
    ocr_reader=None,  # unused; kept for call-site compatibility during transition
    *,
    locale: str = "en_US",
    progress: ProgressFn | None = None,
) -> tuple[list[PdfPageLayout], list[ReportHit]]:
    """Layout extract → native-text NER only (no embedded-image OCR)."""
    from anonymizer.utils.translate import _

    if ocr_reader is not None:
        logger.debug("%s: ocr_reader ignored (PDF text-only detect)", _LOG)
    if progress is not None:
        progress(_("Reading PDF layout…"))
    logger.info("%s: start pdf locale=%s (text-layer only)", _LOG, locale)
    layouts = extract_pdf_layout(pdf_bytes)
    logger.info(
        "%s: layout — pages=%d",
        _LOG,
        len(layouts),
    )
    hits = detect_native_pdf_hits(layouts, locale=locale, progress=progress)
    logger.info("%s: done — total_hits=%d (%s)", _LOG, len(hits), _hit_label_summary(hits))
    if progress is not None:
        progress(_("Detection complete"))
    return layouts, hits
