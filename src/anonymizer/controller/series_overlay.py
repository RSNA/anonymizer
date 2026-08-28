"""Ephemeral series-view overlay payloads produced by controllers.

Not ORM/persistence — canvas annotation data for the current session.
Views render these via ``anonymizer.view.series.series_overlay``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


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
