"""Per-series Harmonize wall-time stage measurements."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class HarmonizeStageTimings:
    """Wall times in seconds for one Harmonize series run."""

    series_directory: str
    geometry_sec: float = 0.0
    nifti_sec: float = 0.0
    anatomy_sec: float = 0.0
    contrast_sec: float = 0.0
    merge_sec: float = 0.0
    total_sec: float = 0.0
    single_pass: bool = False
    body_parts_present: str = ""
    contrast_phase: str = ""
    radlex_series_description: str = ""
    error: str | None = None

    def as_log_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class HarmonizeTimingCollector:
    """Collects stage timings across a ``harmonize_series`` call."""

    results: list[HarmonizeStageTimings] = field(default_factory=list)

    def add(self, timing: HarmonizeStageTimings) -> None:
        self.results.append(timing)
