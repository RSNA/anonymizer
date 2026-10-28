"""Project create/open modalities (codes, aliases, natural language)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from anonymizer.mcp.modality_tokens import (
    extract_modality_tokens_from_text,
    resolve_project_modalities,
)
from anonymizer.mcp.ops import apply_project_modalities
from anonymizer.mcp.session import SESSION
from anonymizer.model.project import ProjectModel
from anonymizer.utils.dicom import DeidMethodCode


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
    controller.model.confidentiality_options = frozenset({DeidMethodCode.BASIC})
    mods = apply_project_modalities(controller, "defaults and ultrasound")
    assert "US" in mods
    for code in ProjectModel.default_modalities():
        assert code in mods
    controller.model.set_storage_classes_from_modalities.assert_called_once()
    controller.save_model.assert_called_once()
    controller.apply_confidentiality_options.assert_not_called()


def test_apply_project_modalities_resolves_aliases():
    """The live-project modality helper resolves aliases to DICOM codes."""
    controller = MagicMock()
    controller.model.modalities = list(ProjectModel.default_modalities())
    controller.model.confidentiality_options = frozenset({DeidMethodCode.BASIC})
    mods = apply_project_modalities(controller, ["defaults", "ultrasound"])
    assert "US" in mods
    assert mods == resolve_project_modalities(["defaults", "ultrasound"])
    controller.apply_confidentiality_options.assert_not_called()


def test_apply_project_modalities_auto_enables_clean_structured_for_sr():
    """Newly enabling SR enables Clean Structured Content and recompiles."""
    controller = MagicMock()
    controller.model.modalities = list(ProjectModel.default_modalities())
    controller.model.confidentiality_options = frozenset({DeidMethodCode.BASIC})
    mods = apply_project_modalities(controller, [*ProjectModel.default_modalities(), "SR"])
    assert "SR" in mods
    controller.apply_confidentiality_options.assert_called_once()
    applied = controller.apply_confidentiality_options.call_args.args[0]
    assert DeidMethodCode.CLEAN_STRUCTURED_CONTENT in applied
    assert DeidMethodCode.BASIC in applied
