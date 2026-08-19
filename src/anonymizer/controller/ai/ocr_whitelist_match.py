"""Per-modality OCR whitelist fuzzy-match presets and resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class OcrWhitelistMatchMode(StrEnum):
    EXACT = "exact"
    STRICT = "strict"
    STANDARD = "standard"
    LENIENT = "lenient"
    CUSTOM = "custom"


@dataclass(frozen=True)
class OcrWhitelistMatchSettings:
    match_mode: OcrWhitelistMatchMode = OcrWhitelistMatchMode.STANDARD
    similarity: float = 0.75
    min_length_ratio: float = 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_mode": self.match_mode.value,
            "similarity": self.similarity,
            "min_length_ratio": self.min_length_ratio,
        }

    @staticmethod
    def from_dict(data: dict[str, Any] | None) -> OcrWhitelistMatchSettings:
        if not data:
            return default_whitelist_match_settings()
        mode_raw = str(data.get("match_mode", OcrWhitelistMatchMode.STANDARD.value))
        try:
            match_mode = OcrWhitelistMatchMode(mode_raw)
        except ValueError:
            match_mode = OcrWhitelistMatchMode.STANDARD
        return OcrWhitelistMatchSettings(
            match_mode=match_mode,
            similarity=float(data.get("similarity", 0.75)),
            min_length_ratio=float(data.get("min_length_ratio", 0.7)),
        )


@dataclass(frozen=True)
class WhitelistMatchResult:
    matched: bool
    whitelist_term: str | None = None
    similarity: float = 0.0


_PRESET_VALUES: dict[OcrWhitelistMatchMode, tuple[float, float]] = {
    OcrWhitelistMatchMode.EXACT: (1.0, 1.0),
    OcrWhitelistMatchMode.STRICT: (0.90, 0.85),
    OcrWhitelistMatchMode.STANDARD: (0.75, 0.70),
    OcrWhitelistMatchMode.LENIENT: (0.65, 0.60),
}


def default_whitelist_match_settings() -> OcrWhitelistMatchSettings:
    return OcrWhitelistMatchSettings()


def resolve_whitelist_match(
    settings: OcrWhitelistMatchSettings | None,
) -> tuple[float, float]:
    """Return (similarity_threshold, min_length_ratio) for filtering."""
    if settings is None:
        settings = default_whitelist_match_settings()
    if settings.match_mode == OcrWhitelistMatchMode.CUSTOM:
        return settings.similarity, settings.min_length_ratio
    similarity, length_ratio = _PRESET_VALUES[settings.match_mode]
    return similarity, length_ratio


def describe_match_settings(settings: OcrWhitelistMatchSettings | None) -> str:
    """User-facing label for logs and batch preview."""
    from anonymizer.utils.translate import _

    if settings is None:
        settings = default_whitelist_match_settings()
    labels = {
        OcrWhitelistMatchMode.EXACT: _("Exact match only"),
        OcrWhitelistMatchMode.STRICT: _("Strict"),
        OcrWhitelistMatchMode.STANDARD: _("Standard"),
        OcrWhitelistMatchMode.LENIENT: _("Lenient"),
        OcrWhitelistMatchMode.CUSTOM: _("Custom"),
    }
    label = labels.get(settings.match_mode, _("Standard"))
    if settings.match_mode == OcrWhitelistMatchMode.CUSTOM:
        return f"{label} ({int(round(settings.similarity * 100))}%)"
    return label


def match_mode_menu_labels() -> dict[str, OcrWhitelistMatchMode]:
    """Map translated menu label -> mode (for Series View OptionMenu)."""
    from anonymizer.utils.translate import _

    return {
        _("Exact"): OcrWhitelistMatchMode.EXACT,
        _("Strict"): OcrWhitelistMatchMode.STRICT,
        _("Standard"): OcrWhitelistMatchMode.STANDARD,
        _("Lenient"): OcrWhitelistMatchMode.LENIENT,
    }


def match_mode_menu_label(mode: OcrWhitelistMatchMode) -> str:
    from anonymizer.utils.translate import _

    reverse = {
        OcrWhitelistMatchMode.EXACT: _("Exact"),
        OcrWhitelistMatchMode.STRICT: _("Strict"),
        OcrWhitelistMatchMode.STANDARD: _("Standard"),
        OcrWhitelistMatchMode.LENIENT: _("Lenient"),
    }
    return reverse.get(mode, reverse[OcrWhitelistMatchMode.STANDARD])


def match_mode_description(mode: OcrWhitelistMatchMode) -> str:
    from anonymizer.utils.translate import _

    descriptions = {
        OcrWhitelistMatchMode.EXACT: _("Only hide text identical to a whitelist entry."),
        OcrWhitelistMatchMode.STRICT: _("Allow only very small OCR differences."),
        OcrWhitelistMatchMode.STANDARD: _("Tolerates minor OCR errors (e.g. AXIL matches AXIAL)."),
        OcrWhitelistMatchMode.LENIENT: _("More tolerance for noisy OCR and short markers."),
        OcrWhitelistMatchMode.CUSTOM: _("Set match closeness manually."),
    }
    return descriptions.get(mode, "")
