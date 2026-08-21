"""Shared series-view overlay DTOs and segmentation render helpers.

Controllers produce these payloads; ImageViewer and other views consume them.
Not ORM/persistence — ephemeral canvas annotations for the current session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import cv2
import numpy as np


class LayerType(Enum):
    TEXT = auto()  # OCR text and rectangle coordinates
    USER_RECT = auto()  # User defined rectangle coordinates
    SEGMENTATIONS = auto()  # polygon vertices


@dataclass()  # Mutable: user can edit boxes in ImageViewer
class OCRText:
    text: str
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]
    prob: float

    def get_bounding_box(self) -> tuple[int, int, int, int]:
        """Returns the bounding box as (x1, y1, x2, y2)."""
        return (self.top_left[0], self.top_left[1], self.bottom_right[0], self.bottom_right[1])

    def box_area(self) -> int:
        x1, y1, x2, y2 = self.get_bounding_box()
        return max(0, x2 - x1) * max(0, y2 - y1)


@dataclass
class UserRectangle:
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]

    def get_bounding_box(self) -> tuple[int, int, int, int]:
        return self.top_left[0], self.top_left[1], self.bottom_right[0], self.bottom_right[1]


@dataclass
class PolygonPoint:
    x: int
    y: int


@dataclass
class Segmentation:
    points: list[PolygonPoint]
    color_bgr: tuple[int, int, int] | None = None
    structure_name: str | None = None


@dataclass
class OverlayData:
    ocr_texts: list[OCRText] = field(default_factory=list)
    user_rects: list[UserRectangle] = field(default_factory=list)
    segmentations: list[Segmentation] = field(default_factory=list)


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
