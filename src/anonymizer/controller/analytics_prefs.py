"""Workstation analytics UI preferences (Show / Volumes pickers)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from anonymizer.controller.analytics import (
    ORGAN_VOLUME_BIN_WIDTH_PCT_MAX,
    ORGAN_VOLUME_BIN_WIDTH_PCT_MIN,
)
from anonymizer.utils.app_state import (
    ANALYTICS_SECTION,
    ORGAN_BIN_WIDTH_PCT_KEY,
    SELECTED_BOARD_WIDGETS_KEY,
    SELECTED_ORGANS_KEY,
    analytics_from_state,
    read_app_state,
    write_app_state,
)
from anonymizer.utils.translate import _

# Must match ``BOARD_WIDGETS`` keys in view/shell/analytics_charts.py.
BOARD_WIDGET_KEYS: tuple[str, ...] = ("sex", "age", "modality", "ethnicity", "ai")

# Stepped coarseness choices (% of padded normative base span). None = JSON default.
ORGAN_BIN_WIDTH_PCT_CHOICES: tuple[float | None, ...] = (None, 2.0, 5.0, 10.0)

# None = preference not set (use defaults / top-N organs). Empty list = user cleared.
_selected_organs: list[str] | None = None
_selected_board_widgets: list[str] | None = None
# None = use per-organ JSON bin_width_ml; else % of base span (clamped).
_organ_bin_width_pct: float | None = None


def board_widget_display_name(key: str) -> str:
    """Localized label for a board widget key (Show picker)."""
    labels = {
        "sex": _("Sex"),
        "age": _("Age at study"),
        "modality": _("Modality"),
        "ethnicity": _("Ethnicity"),
        "ai": _("AI coverage"),
    }
    return labels.get(key, key.replace("_", " ").capitalize())


def organ_bin_width_pct_label(pct: float | None) -> str:
    """Localized label for a bin-width choice (Default / 2% / …)."""
    if pct is None:
        return _("Default")
    return _("{pct:g}%").format(pct=float(pct))


def _normalize_string_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    return [str(item) for item in value if str(item).strip()]


def _normalize_bin_width_pct(value: object) -> float | None:
    if value is None:
        return None
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return None
    if pct != pct or pct in (float("inf"), float("-inf")):
        return None
    return max(
        ORGAN_VOLUME_BIN_WIDTH_PCT_MIN,
        min(ORGAN_VOLUME_BIN_WIDTH_PCT_MAX, pct),
    )

def get_selected_organs() -> list[str] | None:
    """Persisted organ selection, or ``None`` when the user has not set one."""
    return None if _selected_organs is None else list(_selected_organs)


def get_selected_board_widgets() -> list[str] | None:
    """Persisted board-widget selection, or ``None`` for all relevant widgets."""
    return None if _selected_board_widgets is None else list(_selected_board_widgets)


def get_organ_bin_width_pct() -> float | None:
    """Persisted bin coarseness % of base span, or ``None`` for JSON default."""
    return _organ_bin_width_pct


def set_selected_organs(names: Iterable[str] | None, *, persist: bool = True) -> None:
    global _selected_organs
    _selected_organs = None if names is None else [str(n) for n in names]
    if persist:
        persist_analytics_preferences()


def set_selected_board_widgets(keys: Iterable[str] | None, *, persist: bool = True) -> None:
    global _selected_board_widgets
    if keys is None:
        _selected_board_widgets = None
    else:
        allowed = frozenset(BOARD_WIDGET_KEYS)
        _selected_board_widgets = [str(k) for k in keys if str(k) in allowed]
    if persist:
        persist_analytics_preferences()


def set_organ_bin_width_pct(pct: float | None, *, persist: bool = True) -> None:
    global _organ_bin_width_pct
    _organ_bin_width_pct = _normalize_bin_width_pct(pct)
    if persist:
        persist_analytics_preferences()


def current_analytics_preferences() -> dict[str, Any]:
    prefs: dict[str, Any] = {}
    if _selected_organs is not None:
        prefs[SELECTED_ORGANS_KEY] = list(_selected_organs)
    if _selected_board_widgets is not None:
        prefs[SELECTED_BOARD_WIDGETS_KEY] = list(_selected_board_widgets)
    if _organ_bin_width_pct is not None:
        prefs[ORGAN_BIN_WIDTH_PCT_KEY] = float(_organ_bin_width_pct)
    return prefs


def apply_analytics_preferences(prefs: dict[str, Any] | None = None) -> None:
    """Load Show/Volumes selections into module state from app state or ``prefs``."""
    global _selected_organs, _selected_board_widgets, _organ_bin_width_pct
    if prefs is None:
        prefs = analytics_from_state(read_app_state())
    if SELECTED_ORGANS_KEY in prefs:
        raw = prefs.get(SELECTED_ORGANS_KEY)
        _selected_organs = _normalize_string_list(raw) or [] if isinstance(raw, list) else None
    if SELECTED_BOARD_WIDGETS_KEY in prefs:
        raw = prefs.get(SELECTED_BOARD_WIDGETS_KEY)
        if isinstance(raw, list):
            allowed = frozenset(BOARD_WIDGET_KEYS)
            _selected_board_widgets = [str(k) for k in raw if str(k) in allowed]
        else:
            _selected_board_widgets = None
    if ORGAN_BIN_WIDTH_PCT_KEY in prefs:
        _organ_bin_width_pct = _normalize_bin_width_pct(prefs.get(ORGAN_BIN_WIDTH_PCT_KEY))


def persist_analytics_preferences() -> None:
    """Merge current analytics UI prefs into ``.anonymizer_state.json``."""
    state = read_app_state()
    existing = analytics_from_state(state)
    merged = dict(existing)
    merged.update(current_analytics_preferences())
    # Drop keys that are intentionally unset so omit semantics survive.
    if _selected_organs is None:
        merged.pop(SELECTED_ORGANS_KEY, None)
    if _selected_board_widgets is None:
        merged.pop(SELECTED_BOARD_WIDGETS_KEY, None)
    if _organ_bin_width_pct is None:
        merged.pop(ORGAN_BIN_WIDTH_PCT_KEY, None)
    state[ANALYTICS_SECTION] = merged
    write_app_state(state)


def merge_analytics_into_state(state: dict[str, Any]) -> dict[str, Any]:
    merged = dict(state)
    existing = analytics_from_state(merged)
    section = dict(existing)
    section.update(current_analytics_preferences())
    if _selected_organs is None:
        section.pop(SELECTED_ORGANS_KEY, None)
    if _selected_board_widgets is None:
        section.pop(SELECTED_BOARD_WIDGETS_KEY, None)
    if _organ_bin_width_pct is None:
        section.pop(ORGAN_BIN_WIDTH_PCT_KEY, None)
    if section:
        merged[ANALYTICS_SECTION] = section
    elif ANALYTICS_SECTION in merged and not existing:
        merged.pop(ANALYTICS_SECTION, None)
    return merged


def clear_analytics_preferences_cache() -> None:
    """Test helper: reset in-memory prefs without touching disk."""
    global _selected_organs, _selected_board_widgets, _organ_bin_width_pct
    _selected_organs = None
    _selected_board_widgets = None
    _organ_bin_width_pct = None


def intersect_organ_selection(
    selected: Sequence[str] | None,
    available: Iterable[str],
) -> set[str]:
    """Keep only organs still present in the snapshot."""
    available_set = set(available)
    if selected is None:
        return set()
    return {name for name in selected if name in available_set}


def intersect_board_widget_selection(
    selected: Sequence[str] | None,
    relevant: Iterable[str],
) -> set[str]:
    """Keep only board widgets that are relevant for the current snapshot.

    ``selected is None`` means the user has not customized — return all relevant.
    """
    relevant_set = {key for key in relevant if key in BOARD_WIDGET_KEYS}
    if selected is None:
        return set(relevant_set)
    return {key for key in selected if key in relevant_set}
