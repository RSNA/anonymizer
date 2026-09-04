"""Workstation app state persisted in ``.anonymizer_state.json`` (under the logs directory)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from anonymizer.utils.logging import _get_logs_dir

logger = logging.getLogger(__name__)

APP_STATE_FILENAME = ".anonymizer_state.json"
AI_FEATURES_SECTION = "ai_features"
CT_SEGMENTATION_MODE_KEY = "ct_segmentation_mode"
MR_SEGMENTATION_MODE_KEY = "mr_segmentation_mode"


def get_app_state_path() -> Path:
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
