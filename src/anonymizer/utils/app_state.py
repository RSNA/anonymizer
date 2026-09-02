"""Workstation app state persisted in ``.anonymizer_state.json`` (under the logs directory)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

APP_STATE_FILENAME = ".anonymizer_state.json"
AI_FEATURES_SECTION = "ai_features"
CT_SEGMENTATION_MODE_KEY = "ct_segmentation_mode"
MR_SEGMENTATION_MODE_KEY = "mr_segmentation_mode"


def get_app_state_path() -> Path:
    from anonymizer.utils.logging import _get_logs_dir

    return Path(_get_logs_dir()) / APP_STATE_FILENAME


def read_app_state() -> dict[str, Any]:
    path = get_app_state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read app state from %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def write_app_state(data: dict[str, Any]) -> None:
    path = get_app_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ai_features_from_state(state: dict[str, Any]) -> dict[str, Any]:
    section = state.get(AI_FEATURES_SECTION)
    return section if isinstance(section, dict) else {}


def current_ai_features_preferences() -> dict[str, str]:
    from anonymizer.controller.ai.tseg.config import (
        get_ct_segmentation_mode,
        get_mr_segmentation_mode,
    )

    return {
        CT_SEGMENTATION_MODE_KEY: get_ct_segmentation_mode(),
        MR_SEGMENTATION_MODE_KEY: get_mr_segmentation_mode(),
    }


def apply_ai_features_preferences(prefs: dict[str, Any] | None = None) -> None:
    """Load CT/MR Harmonize resolution preferences into the runtime config module."""
    from anonymizer.controller.ai.tseg.config import (
        set_ct_segmentation_mode,
        set_mr_segmentation_mode,
    )

    if prefs is None:
        prefs = ai_features_from_state(read_app_state())
    if CT_SEGMENTATION_MODE_KEY in prefs:
        set_ct_segmentation_mode(prefs[CT_SEGMENTATION_MODE_KEY])
    if MR_SEGMENTATION_MODE_KEY in prefs:
        set_mr_segmentation_mode(prefs[MR_SEGMENTATION_MODE_KEY])


def persist_ai_features_preferences() -> None:
    """Merge current CT/MR segmentation modes into ``.anonymizer_state.json``."""
    state = read_app_state()
    state[AI_FEATURES_SECTION] = current_ai_features_preferences()
    write_app_state(state)


def merge_ai_features_into_state(state: dict[str, Any]) -> dict[str, Any]:
    merged = dict(state)
    merged[AI_FEATURES_SECTION] = current_ai_features_preferences()
    return merged
