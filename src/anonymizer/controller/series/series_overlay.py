"""Ephemeral series-view overlay payloads produced by controllers.

Public API
----------
LayerType
    LayerType type.

OcrEvidence
    EasyOCR confidence for one box (set by detect).

WhitelistEvidence
    Whitelist annotate result; score None means annotate not run yet.

NerEvidence
    NER annotate result; score None means annotate not run yet.

OCRText
    Burnt-in text box; nested ocr / whitelist / ner evidence only (no decision flags).

UserRectangle
    UserRectangle type.

PolygonPoint
    PolygonPoint type.

Segmentation
    Segmentation type.

OverlayData
    OverlayData type.
"""
from dataclasses import dataclass, field
from enum import Enum, auto


class LayerType(Enum):
    TEXT = auto()  # OCR text and rectangle coordinates
    USER_RECT = auto()  # User defined rectangle coordinates (pending blackout)
    EXCLUDE_RECT = auto()  # Regions excluded from Detect Text / Remove Text
    SEGMENTATIONS = auto()  # polygon vertices


@dataclass()
class OcrEvidence:
    """EasyOCR confidence for one box."""

    prob: float


@dataclass()
class WhitelistEvidence:
    """Whitelist annotate result; score None means annotate not run yet."""

    term: str | None = None
    score: float | None = None


@dataclass()
class NerEvidence:
    """NER annotate result; score None means annotate not run yet."""

    label: str | None = None
    entities: tuple[tuple[str, str], ...] = ()
    score: float | None = None


@dataclass()  # Mutable: user can edit boxes in ImageViewer
class OCRText:
    """Burnt-in text box; evidence only — callers decide with PhiMatchMode helpers."""

    text: str
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]
    ocr: OcrEvidence
    whitelist: WhitelistEvidence = field(default_factory=WhitelistEvidence)
    ner: NerEvidence = field(default_factory=NerEvidence)

    def get_bounding_box(self) -> tuple[int, int, int, int]:
        """Returns the bounding box as (x1, y1, x2, y2)."""
        return (self.top_left[0], self.top_left[1], self.bottom_right[0], self.bottom_right[1])

    def box_area(self) -> int:
        """Axis-aligned box area in pixels."""
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
    # ROI annotation (display metadata; voxels live in annotations/labels.nii.gz).
    label_id: int | None = None
    label_name: str | None = None
    source: str | None = None  # "ts" | "user" | "edited"
    editable: bool = False
    # When True with color_bgr set: light fill under outline (unused in Series View; outline-only).
    filled: bool = False


@dataclass
class OverlayData:
    ocr_texts: list[OCRText] = field(default_factory=list)
    user_rects: list[UserRectangle] = field(default_factory=list)
    exclude_rects: list[UserRectangle] = field(default_factory=list)
    segmentations: list[Segmentation] = field(default_factory=list)
