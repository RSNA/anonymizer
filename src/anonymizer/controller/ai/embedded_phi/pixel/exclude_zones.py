"""Named modality exclude zones (normalized rects next to project whitelists).

Public API
----------
normalize_user_rects(rects: Sequence[UserRectangle], *, width: int, height: int) -> list[dict]
    Convert pixel UserRectangles to 0–1 fractions of width × height.

user_rects_from_normalized(rects: Sequence[dict], *, width: int, height: int) -> list[UserRectangle]
    Scale normalized 0–1 rects to pixel UserRectangles.

modality_exclude_rects_for_series(project_dir: Path | None, modality: str | None, *, width: int, height: int) -> list[UserRectangle]
    Load saved exclude areas for modality and scale to pixels.

rects_intersect(a, b) -> bool
    True when two axis-aligned boxes overlap (inclusive edges).

filter_ocr_outside_exclude_rects(detections: Sequence[OCRText], exclude_rects: Sequence[UserRectangle] | None) -> list[OCRText]
    Drop OCR boxes that intersect any exclude rectangle.

filter_ocr_for_remove_mode(detections: Sequence[OCRText], *, remove_mode: OcrRemoveMode, match_mode: PhiMatchMode, exclude_rects: Sequence[UserRectangle] | None=None) -> list[OCRText]
    WYSIWYG / remove set: exclude zones, then Remove Scope via texts_for_remove_mode.
"""
from collections.abc import Sequence
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import PhiMatchMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrRemoveMode, texts_for_remove_mode
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import load_project_exclude_rects
from anonymizer.controller.series.series_overlay import OCRText, UserRectangle


def normalize_user_rects(
    rects: Sequence[UserRectangle],
    *,
    width: int,
    height: int,
) -> list[dict]:
    """Convert pixel UserRectangles to 0–1 fractions of width × height."""
    w = max(int(width), 1)
    h = max(int(height), 1)
    out: list[dict] = []
    for rect in rects:
        x1, y1, x2, y2 = rect.get_bounding_box()
        nx1, nx2 = sorted((x1 / w, x2 / w))
        ny1, ny2 = sorted((y1 / h, y2 / h))
        out.append(
            {
                "x1": max(0.0, min(1.0, nx1)),
                "y1": max(0.0, min(1.0, ny1)),
                "x2": max(0.0, min(1.0, nx2)),
                "y2": max(0.0, min(1.0, ny2)),
            }
        )
    return out


def user_rects_from_normalized(
    rects: Sequence[dict],
    *,
    width: int,
    height: int,
) -> list[UserRectangle]:
    """Scale normalized 0–1 rects to pixel UserRectangles."""
    w = max(int(width), 1)
    h = max(int(height), 1)
    out: list[UserRectangle] = []
    for rect in rects:
        x1 = int(round(float(rect["x1"]) * w))
        y1 = int(round(float(rect["y1"]) * h))
        x2 = int(round(float(rect["x2"]) * w))
        y2 = int(round(float(rect["y2"]) * h))
        if x1 == x2 or y1 == y2:
            continue
        out.append(UserRectangle(top_left=(min(x1, x2), min(y1, y2)), bottom_right=(max(x1, x2), max(y1, y2))))
    return out


def modality_exclude_rects_for_series(
    project_dir: Path | None,
    modality: str | None,
    *,
    width: int,
    height: int,
) -> list[UserRectangle]:
    """Load saved exclude areas for modality and scale to pixels."""
    if project_dir is None or not modality:
        return []
    return user_rects_from_normalized(
        load_project_exclude_rects(project_dir, modality),
        width=width,
        height=height,
    )


def rects_intersect(
    a: tuple[int, int, int, int] | OCRText | UserRectangle,
    b: tuple[int, int, int, int] | OCRText | UserRectangle,
) -> bool:
    """Return True when two axis-aligned boxes overlap (inclusive edges count as overlap)."""

    def as_box(item: tuple[int, int, int, int] | OCRText | UserRectangle) -> tuple[int, int, int, int]:
        if isinstance(item, tuple):
            return item
        return item.get_bounding_box()

    ax1, ay1, ax2, ay2 = as_box(a)
    bx1, by1, bx2, by2 = as_box(b)
    return not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)


def filter_ocr_outside_exclude_rects(
    detections: Sequence[OCRText],
    exclude_rects: Sequence[UserRectangle] | None,
) -> list[OCRText]:
    """Drop OCR boxes that intersect any exclude rectangle (spatial keepers)."""
    if not exclude_rects:
        return list(detections)
    kept: list[OCRText] = []
    for ocr_text in detections:
        if any(rects_intersect(ocr_text, rect) for rect in exclude_rects):
            continue
        kept.append(ocr_text)
    return kept


def filter_ocr_for_remove_mode(
    detections: Sequence[OCRText],
    *,
    remove_mode: OcrRemoveMode,
    match_mode: PhiMatchMode = PhiMatchMode.STANDARD,
    exclude_rects: Sequence[UserRectangle] | None = None,
) -> list[OCRText]:
    """WYSIWYG / remove set: exclude zones, then Remove Scope + PhiMatchMode."""
    kept = filter_ocr_outside_exclude_rects(detections, exclude_rects)
    return texts_for_remove_mode(kept, remove_mode, match_mode)
