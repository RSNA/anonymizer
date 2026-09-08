"""Unit tests for spatial OCR exclude rectangles."""

from __future__ import annotations

from anonymizer.controller.ai.remove_pixel_phi import (
    filter_ocr_outside_exclude_rects,
    rects_intersect,
)
from anonymizer.controller.series_overlay import OCRText, UserRectangle


def _ocr(text: str, x1: int, y1: int, x2: int, y2: int) -> OCRText:
    return OCRText(text=text, top_left=(x1, y1), bottom_right=(x2, y2), prob=0.9)


def _rect(x1: int, y1: int, x2: int, y2: int) -> UserRectangle:
    return UserRectangle(top_left=(x1, y1), bottom_right=(x2, y2))


def test_rects_intersect_overlap_and_touching_edges() -> None:
    assert rects_intersect((0, 0, 10, 10), (5, 5, 15, 15))
    assert rects_intersect((0, 0, 10, 10), (10, 0, 20, 10))  # shared edge
    assert not rects_intersect((0, 0, 10, 10), (11, 0, 20, 10))


def test_rects_intersect_full_containment() -> None:
    assert rects_intersect((0, 0, 100, 100), (20, 20, 40, 40))
    assert rects_intersect(_ocr("x", 20, 20, 40, 40), _rect(0, 0, 100, 100))


def test_filter_ocr_outside_exclude_rects_drops_intersecting() -> None:
    panel = _rect(100, 200, 300, 400)
    detections = [
        _ocr("PHI", 10, 10, 50, 30),
        _ocr("Dist", 120, 220, 180, 250),
        _ocr("LIVER", 150, 260, 220, 290),
        _ocr("outside", 310, 10, 360, 40),
    ]
    kept = filter_ocr_outside_exclude_rects(detections, [panel])
    texts = [t.text for t in kept]
    assert texts == ["PHI", "outside"]


def test_filter_ocr_outside_exclude_rects_empty_passthrough() -> None:
    detections = [_ocr("keep", 1, 1, 5, 5)]
    assert filter_ocr_outside_exclude_rects(detections, None) == detections
    assert filter_ocr_outside_exclude_rects(detections, []) == detections


def test_filter_ocr_outside_exclude_rects_multiple_zones() -> None:
    detections = [
        _ocr("a", 0, 0, 10, 10),
        _ocr("b", 50, 50, 60, 60),
        _ocr("c", 100, 100, 110, 110),
    ]
    kept = filter_ocr_outside_exclude_rects(
        detections,
        [_rect(0, 0, 20, 20), _rect(90, 90, 120, 120)],
    )
    assert [t.text for t in kept] == ["b"]
