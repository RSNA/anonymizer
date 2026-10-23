"""Named modality exclude zones (normalized rects next to project whitelists).

Public API
----------
normalize_user_rects(rects: Sequence[UserRectangle], *, width: int, height: int) -> list[dict]
    Convert pixel UserRectangles to 0–1 fractions of width × height.

user_rects_from_normalized(rects: Sequence[dict], *, width: int, height: int) -> list[UserRectangle]
    Scale normalized 0–1 rects to pixel UserRectangles.

modality_exclude_rects_for_series(project_dir: Path | None, modality: str | None, *, width: int, height: int) -> list[UserRectangle]
    Load saved exclude areas for modality and scale to pixels.

filter_ocr_for_remove_mode(detections: Sequence[OCRText], *, remove_mode: object, whitelist: Sequence[str], whitelist_match_settings=None, exclude_rects: Sequence[UserRectangle] | None=None) -> list[OCRText]
    WYSIWYG / remove set: exclude zones, whitelist veto, then remove scope.
"""
from collections.abc import Sequence
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    filter_ocr_outside_exclude_rects,
    filter_ocr_whitelist_only,
)
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


def filter_ocr_for_remove_mode(
    detections: Sequence[OCRText],
    *,
    remove_mode: object,
    whitelist: Sequence[str],
    whitelist_match_settings=None,
    exclude_rects: Sequence[UserRectangle] | None = None,
) -> list[OCRText]:
    """WYSIWYG / remove set: exclude zones, whitelist veto, then remove scope.

    All text is the only scope that ignores the whitelist; every other
    scope keeps whitelisted boxes even when NER labelled them (a false
    positive must not erase a protected keeper, e.g. AXILLA as NAME).
    """
    kept = filter_ocr_outside_exclude_rects(detections, exclude_rects)
    mode = getattr(remove_mode, "value", str(remove_mode))
    if mode == "all_text":
        return kept
    if whitelist:
        kept = filter_ocr_whitelist_only(
            kept,
            whitelist=whitelist,
            whitelist_match_settings=whitelist_match_settings,
        )
    if mode == "phi_only":
        return [item for item in kept if (item.phi_label or "").strip()]
    return kept
