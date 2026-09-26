"""Project create/open modalities (codes, aliases, natural language)."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.mcp.session import SESSION
from anonymizer.mcp import api as mcp_tools
from anonymizer.model.project import ProjectModel
from anonymizer.utils.modalities import (
    extract_modality_tokens_from_text,
    resolve_project_modalities,
)


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
    result = mcp_tools.create_project(
        project_name="WithUS",
        modalities="defaults and ultrasound",
        overwrite=True,
    )
    assert result["ok"] is True
    mods = result["project"]["modalities"]
    assert "US" in mods
    for code in ProjectModel.default_modalities():
        assert code in mods


def test_project_open_updates_modalities():
    assert mcp_tools.create_project(project_name="ModOpen", overwrite=True)["ok"]
    opened = mcp_tools.project_open(
        project_name="ModOpen",
        modalities=["defaults", "ultrasound"],
    )
    assert opened["ok"] is True
    assert "US" in opened["project"]["modalities"]
    # Persisted
    SESSION.close()
    again = mcp_tools.project_open(project_name="ModOpen")
    assert again["ok"] is True
    assert "US" in again["project"]["modalities"]
