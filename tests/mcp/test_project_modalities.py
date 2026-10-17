"""Project create/open modalities (codes, aliases, natural language)."""

from __future__ import annotations

from pathlib import Path

import pytest

from unittest.mock import MagicMock

from anonymizer.mcp.modality_tokens import (
    extract_modality_tokens_from_text,
    resolve_project_modalities,
)
from anonymizer.mcp.ops import apply_project_modalities
from anonymizer.mcp.session import SESSION
from anonymizer.model.project import ProjectModel


@pytest.fixture(autouse=True)
def _isolated_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ProjectModel, "base_dir", staticmethod(lambda: tmp_path / "RSNA Anonymizer"))
    SESSION.close()
    yield
    SESSION.close()


def test_resolve_defaults_and_ultrasound_phrase():
    resolved = resolve_project_modalities("defaults and ultrasound")
    assert resolved == [*ProjectModel.default_modalities(), "US"]


def test_resolve_list_defaults_plus_us():
    assert resolve_project_modalities(["defaults", "US"]) == [
        *ProjectModel.default_modalities(),
        "US",
    ]


def test_extract_modality_tokens_from_text():
    assert "defaults" in extract_modality_tokens_from_text("defaults and ultrasound")
    assert "US" in extract_modality_tokens_from_text("defaults and ultrasound")
    assert extract_modality_tokens_from_text("CT, MR, US") == ["CT", "MR", "US"]


def test_create_project_with_defaults_and_ultrasound():
    """MCP create path applies modalities via ``apply_project_modalities``."""
    controller = MagicMock()
    controller.model.modalities = list(ProjectModel.default_modalities())
    mods = apply_project_modalities(controller, "defaults and ultrasound")
    assert "US" in mods
    for code in ProjectModel.default_modalities():
        assert code in mods
    controller.model.set_storage_classes_from_modalities.assert_called_once()
    controller.save_model.assert_called_once()


def test_project_open_updates_modalities():
    """MCP project_open uses the same modality resolver as create."""
    controller = MagicMock()
    controller.model.modalities = list(ProjectModel.default_modalities())
    mods = apply_project_modalities(controller, ["defaults", "ultrasound"])
    assert "US" in mods
    assert mods == resolve_project_modalities(["defaults", "ultrasound"])
