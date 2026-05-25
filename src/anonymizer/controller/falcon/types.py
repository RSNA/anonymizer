"""Public result types for the FALCON controller API."""

from dataclasses import dataclass
from pathlib import Path

FALCON_BODY_PARTS = ("HeadNeck", "Chest", "Abdomen")


@dataclass(frozen=True)
class FalconEligibility:
    """Pre-inference eligibility check for a CT series directory."""

    series_directory: Path
    eligible: bool
    error: str | None = None


@dataclass(frozen=True)
class FalconPrediction:
    """Body-part and IV contrast prediction for a CT series directory."""

    series_directory: Path
    body_part: str | None = None
    body_part_confidence: float | None = None
    iv_contrast: bool | None = None
    iv_contrast_confidence: float | None = None
    error: str | None = None

    @classmethod
    def failure(cls, series_directory: Path, error: str) -> "FalconPrediction":
        return cls(series_directory=series_directory, error=error)

    @property
    def success(self) -> bool:
        return self.error is None
