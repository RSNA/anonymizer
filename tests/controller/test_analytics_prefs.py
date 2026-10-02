"""Analytics preferences persistence (real app_state file; no mocks)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonymizer.controller.analytics.prefs import (
    apply_analytics_preferences,
    board_widget_display_name,
    clear_analytics_preferences_cache,
    current_analytics_preferences,
    get_organ_bin_width_pct,
    get_selected_board_widgets,
    get_selected_organs,
    intersect_board_widget_selection,
    intersect_organ_selection,
    merge_analytics_into_state,
    organ_bin_width_pct_label,
    persist_analytics_preferences,
    set_organ_bin_width_pct,
    set_selected_board_widgets,
    set_selected_organs,
)
from anonymizer.utils import app_state
from anonymizer.utils.app_state import ANALYTICS_SECTION, ORGAN_BIN_WIDTH_PCT_KEY


@pytest.fixture
def isolated_analytics_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_path = tmp_path / ".anonymizer_state.json"
    monkeypatch.setattr(app_state, "get_app_state_path", lambda: state_path)
    clear_analytics_preferences_cache()
    yield state_path
    clear_analytics_preferences_cache()


def test_analytics_prefs_persist_and_apply(isolated_analytics_state: Path) -> None:
    set_selected_organs(["brain", "liver"])
    set_selected_board_widgets(["sex", "age"])
    set_organ_bin_width_pct(7.5)
    persist_analytics_preferences()

    data = json.loads(isolated_analytics_state.read_text(encoding="utf-8"))
    assert data[ANALYTICS_SECTION]["selected_organs"] == ["brain", "liver"]
    assert data[ANALYTICS_SECTION]["selected_board_widgets"] == ["sex", "age"]
    assert data[ANALYTICS_SECTION][ORGAN_BIN_WIDTH_PCT_KEY] == pytest.approx(7.5)

    clear_analytics_preferences_cache()
    assert get_selected_organs() is None
    apply_analytics_preferences()
    assert get_selected_organs() == ["brain", "liver"]
    assert get_selected_board_widgets() == ["sex", "age"]
    assert get_organ_bin_width_pct() == pytest.approx(7.5)

    prefs = current_analytics_preferences()
    assert prefs["selected_organs"] == ["brain", "liver"]
    merged = merge_analytics_into_state({"language": "en_US"})
    assert merged["language"] == "en_US"
    assert merged[ANALYTICS_SECTION]["selected_organs"] == ["brain", "liver"]


def test_intersect_and_labels(isolated_analytics_state: Path) -> None:
    assert board_widget_display_name("sex")
    assert organ_bin_width_pct_label(5.0)
    assert intersect_organ_selection(["brain", "zzz"], {"brain", "liver"}) == {"brain"}
    assert intersect_board_widget_selection(["sex", "nope"], {"sex", "age"}) == {"sex"}
