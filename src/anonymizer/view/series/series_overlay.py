"""Series-view segmentation overlay rendering."""

from __future__ import annotations

import cv2
import numpy as np

from anonymizer.controller.series_overlay import Segmentation

# Single-pixel opaque color stroke (no dark understroke — that exaggerates contour jaggedness).
COLORED_SEGMENTATION_OUTLINE_THICKNESS = 1
# Optional fill blend when ``Segmentation.filled`` is True (Series View uses outline-only).
ACTIVE_LABEL_FILL_BLEND = 0.35


def render_segmentations_overlay(
    height: int,
    width: int,
    segmentations: list[Segmentation],
    *,
    default_color_bgr: tuple[int, int, int],
) -> np.ndarray:
    """Draw segmentations into a BGR overlay buffer.

    When ``Segmentation.color_bgr`` is set: opaque 1px outline (optional light fill when
    ``filled``). When unset: solid ``fillPoly`` with ``default_color_bgr`` (Face Blur path).
    """
    combined = np.zeros((height, width, 3), dtype=np.uint8)
    if not segmentations:
        return combined

    outline_queue: list[tuple[np.ndarray, tuple[int, int, int], bool]] = []

    for segmentation in segmentations:
        if len(segmentation.points) < 3:
            continue
        points = np.array([(p.x, p.y) for p in segmentation.points], dtype=np.int32)
        color = segmentation.color_bgr
        if color is None:
            cv2.fillPoly(combined, [points], default_color_bgr)
            continue
        outline_queue.append((points, color, bool(segmentation.filled)))

    for points, color, filled in outline_queue:
        if filled:
            fill_layer = np.zeros_like(combined)
            cv2.fillPoly(fill_layer, [points], color)
            fill_mask = fill_layer.max(axis=2) > 0
            combined[fill_mask] = (
                combined[fill_mask].astype(np.float32) * (1.0 - ACTIVE_LABEL_FILL_BLEND)
                + fill_layer[fill_mask].astype(np.float32) * ACTIVE_LABEL_FILL_BLEND
            ).astype(np.uint8)
        # LINE_8 (not AA): AA softens into CT via composite and shifts hue (e.g. orange↔yellow).
        cv2.polylines(
            combined,
            [points],
            isClosed=True,
            color=color,
            thickness=COLORED_SEGMENTATION_OUTLINE_THICKNESS,
            lineType=cv2.LINE_8,
        )
    return combined
