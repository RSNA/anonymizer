"""Unified PHI hits for Report View (native PDF text + OCR image regions)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

HitSource = Literal["native", "ocr"]

# Drop OCR hits that mostly cover the same page region as a native hit.
_OVERLAP_KEEP_FRAC = 0.35


@dataclass(slots=True)
class ReportHit:
    """One PHI span with page-space geometry for overlay / paint-out."""

    page_index: int
    text: str
    label: str
    # Page / frame space: (x0, y0, x1, y1) with origin top-left for display,
    # or PDF user-space bottom-left — callers convert consistently via layout helpers.
    rect: tuple[float, float, float, float]
    source: HitSource
    key: str
    # Optional native-text offsets into page layout text (for transcript rebuild).
    start: int | None = None
    end: int | None = None

    def as_pixel_rect(self) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = self.rect
        return int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))


def hit_key(page_index: int, source: HitSource, start: int, end: int, text: str) -> str:
    return f"{page_index}:{source}:{start}:{end}:{text[:32]}"


def _rect_area(rect: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = rect
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    return max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)


def rects_overlap_substantially(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    *,
    min_frac: float = _OVERLAP_KEEP_FRAC,
) -> bool:
    """True when intersection covers ``min_frac`` of the smaller rect."""
    inter = _intersection_area(a, b)
    if inter <= 0:
        return False
    smaller = min(_rect_area(a), _rect_area(b))
    return smaller > 0 and (inter / smaller) >= min_frac


def dedupe_overlapping_hits(hits: Sequence[ReportHit]) -> list[ReportHit]:
    """Prefer native-text hits when OCR covers the same page region (avoids double boxes)."""
    natives = [h for h in hits if h.source == "native"]
    ocrs = [h for h in hits if h.source == "ocr"]
    other = [h for h in hits if h.source not in {"native", "ocr"}]
    kept_ocr: list[ReportHit] = []
    for ocr in ocrs:
        if any(
            n.page_index == ocr.page_index and rects_overlap_substantially(n.rect, ocr.rect)
            for n in natives
        ):
            continue
        kept_ocr.append(ocr)
    return natives + kept_ocr + other
