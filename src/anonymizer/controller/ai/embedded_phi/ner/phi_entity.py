"""PHI entity span and scored labels for Embedded PHI NER."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PhiEntity:
    """One PHI span: label + character offsets into the source string."""

    label: str
    start: int
    end: int
    score: float = 1.0
    raw_label: str = ""

    def text_of(self, source: str) -> str:
        return source[self.start : self.end]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Internal alias used by engines/guard (same shape as prototyping Span).
Span = PhiEntity

SCORED_LABELS = (
    "NAME",
    "LOCATION",
    "ID",
    "PHONE",
    "DATE",
    "EMAIL",
)

# Detect locales with a full pack + model. UI may be de/fr/es; English NER stays wired.
SUPPORTED_DETECT_LOCALES = frozenset({"en_US"})
