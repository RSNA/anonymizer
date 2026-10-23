"""Shared types for metadata PHI detection."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Span:
    label: str
    start: int
    end: int
    score: float = 1.0
    raw_label: str = ""

    def text_of(self, source: str) -> str:
        return source[self.start : self.end]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TextChunk:
    text: str
    path: str = ""
    sop_uid: str = ""
    tag_or_path: str = ""
    locale: str = "en_US"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GoldExample:
    id: str
    text: str
    spans: list[Span] = field(default_factory=list)
    notes: str = ""
