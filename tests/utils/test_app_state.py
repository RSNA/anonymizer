"""Tests for workstation app state persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonymizer.controller.ai.tseg.config import (
    apply_ai_features_preferences,
    clear_segmentation_mode_cache,
    get_ct_segmentation_mode,
    get_mr_segmentation_mode,
    merge_ai_features_into_state,
    persist_ai_features_preferences,
    set_ct_segmentation_mode,
    set_mr_segmentation_mode,
)
from anonymizer.utils import app_state


@pytest.fixture
def isolated_app_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from anonymizer.controller.analytics_prefs import clear_analytics_preferences_cache

    state_path = tmp_path / ".anonymizer_state.json"
    monkeypatch.setattr(app_state, "get_app_state_path", lambda: state_path)
    clear_segmentation_mode_cache()
    clear_analytics_preferences_cache()
    yield state_path
    clear_segmentation_mode_cache()
    clear_analytics_preferences_cache()


def test_persist_and_apply_ai_features_preferences(isolated_app_state: Path) -> None:
    set_ct_segmentation_mode("1.5mm")
    set_mr_segmentation_mode("6mm")
    persist_ai_features_preferences()

    data = json.loads(isolated_app_state.read_text(encoding="utf-8"))
    assert data["ai_features"] == {
        "ct_segmentation_mode": "1.5mm",
        "mr_segmentation_mode": "6mm",
    }

    clear_segmentation_mode_cache()
    assert get_ct_segmentation_mode() == "3mm"
    assert get_mr_segmentation_mode() == "3mm"

    apply_ai_features_preferences()
    assert get_ct_segmentation_mode() == "1.5mm"
    assert get_mr_segmentation_mode() == "6mm"


def test_persist_and_apply_analytics_preferences(isolated_app_state: Path) -> None:
    from anonymizer.controller.analytics_prefs import (
        apply_analytics_preferences,
        clear_analytics_preferences_cache,
        get_organ_bin_width_pct,
        get_selected_board_widgets,
        get_selected_organs,
        merge_analytics_into_state,
        set_organ_bin_width_pct,
        set_selected_board_widgets,
        set_selected_organs,
    )
    from anonymizer.utils.app_state import ANALYTICS_SECTION, ORGAN_BIN_WIDTH_PCT_KEY

    clear_analytics_preferences_cache()
    set_selected_organs(["brain", "liver"])
    set_selected_board_widgets(["sex", "age"])
    set_organ_bin_width_pct(5.0)

    data = json.loads(isolated_app_state.read_text(encoding="utf-8"))
    assert data[ANALYTICS_SECTION] == {
        "selected_organs": ["brain", "liver"],
        "selected_board_widgets": ["sex", "age"],
        ORGAN_BIN_WIDTH_PCT_KEY: 5.0,
    }

    clear_analytics_preferences_cache()
    assert get_selected_organs() is None
    assert get_selected_board_widgets() is None
    assert get_organ_bin_width_pct() is None

    apply_analytics_preferences()
    assert get_selected_organs() == ["brain", "liver"]
    assert get_selected_board_widgets() == ["sex", "age"]
    assert get_organ_bin_width_pct() == pytest.approx(5.0)

    merged = merge_analytics_into_state({"language": "en_US"})
    assert merged["language"] == "en_US"
    assert merged[ANALYTICS_SECTION]["selected_organs"] == ["brain", "liver"]

    # Clear organs → empty list persists; unset board widgets / bin width drops keys.
    set_selected_organs([])
    set_selected_board_widgets(None)
    set_organ_bin_width_pct(None)
    data = json.loads(isolated_app_state.read_text(encoding="utf-8"))
    assert data[ANALYTICS_SECTION]["selected_organs"] == []
    assert "selected_board_widgets" not in data[ANALYTICS_SECTION]
    assert ORGAN_BIN_WIDTH_PCT_KEY not in data[ANALYTICS_SECTION]


def test_merge_ai_features_preserves_other_state_keys() -> None:
    merged = merge_ai_features_into_state(
        {
            "language": "de",
            "recent_project_dirs": ["/tmp/project"],
            "current_open_project_dir": "/tmp/project",
        }
    )
    assert merged["language"] == "de"
    assert merged["recent_project_dirs"] == ["/tmp/project"]
    assert merged["ai_features"]["ct_segmentation_mode"] == get_ct_segmentation_mode()
    assert merged["ai_features"]["mr_segmentation_mode"] == get_mr_segmentation_mode()


def test_apply_ai_features_ignores_invalid_modes(isolated_app_state: Path) -> None:
    isolated_app_state.write_text(
        json.dumps(
            {
                "ai_features": {
                    "ct_segmentation_mode": "bogus",
                    "mr_segmentation_mode": "6 mm",
                }
            }
        ),
        encoding="utf-8",
    )
    clear_segmentation_mode_cache()
    apply_ai_features_preferences()
    assert get_ct_segmentation_mode() == "3mm"
    assert get_mr_segmentation_mode() == "6mm"
