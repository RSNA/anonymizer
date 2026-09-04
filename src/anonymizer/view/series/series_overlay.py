"""Series-view segmentation overlay rendering."""

from __future__ import annotations

import cv2
import numpy as np

from anonymizer.controller.series_overlay import Segmentation

# Opaque solid outlines: dark understroke wider than the color stroke so edges stay readable on bone.
# Near-black (not 0,0,0): zero RGB is treated as empty by ImageViewer compositing.
COLORED_SEGMENTATION_OUTLINE_THICKNESS = 2
COLORED_SEGMENTATION_OUTLINE_UNDERLAY_THICKNESS = 4
COLORED_SEGMENTATION_OUTLINE_UNDERLAY_BGR = (16, 16, 16)


def render_segmentations_overlay(
    height: int,
    width: int,
    segmentations: list[Segmentation],
    *,
    default_color_bgr: tuple[int, int, int],
) -> np.ndarray:
    """Draw segmentations into a BGR overlay buffer.

    When ``Segmentation.color_bgr`` is set: opaque outline only (solid color stroke over a
    dark understroke; no fill, no transparency).
    When unset: solid ``fillPoly`` with ``default_color_bgr`` (Face Blur path).
    """
    combined = np.zeros((height, width, 3), dtype=np.uint8)
    if not segmentations:
        return combined

    outline_queue: list[tuple[np.ndarray, tuple[int, int, int]]] = []

    for segmentation in segmentations:
        if len(segmentation.points) < 3:
            continue
        points = np.array([(p.x, p.y) for p in segmentation.points], dtype=np.int32)
        color = segmentation.color_bgr
        if color is None:
            cv2.fillPoly(combined, [points], default_color_bgr)
            continue
        outline_queue.append((points, color))

    for points, color in outline_queue:
        # LINE_8 (not AA): AA softens into CT via composite and shifts hue (e.g. orange↔yellow).
        cv2.polylines(
            combined,
            [points],
            isClosed=True,
            color=COLORED_SEGMENTATION_OUTLINE_UNDERLAY_BGR,
            thickness=COLORED_SEGMENTATION_OUTLINE_UNDERLAY_THICKNESS,
            lineType=cv2.LINE_8,
        )
        cv2.polylines(
            combined,
            [points],
            isClosed=True,
            color=color,
            thickness=COLORED_SEGMENTATION_OUTLINE_THICKNESS,
            lineType=cv2.LINE_8,
        )
    return combined
