"""Phase 1 MCP search tool tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydicom.dataset import Dataset

from anonymizer.mcp.session import SESSION
from anonymizer.mcp import tools as mcp_tools
from anonymizer.utils.translate import set_language_code

DAVIDSON = (
    Path(__file__).resolve().parent.parent
    / "controller"
    / "assets"
    / "test_dcm_files"
    / "davidson_cxr"
)


@pytest.fixture(autouse=True)
def _isolated_session():
    set_language_code("en_US")
    SESSION.close()
    yield
    SESSION.close()


def _open_temp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    from anonymizer.model.project import ProjectModel

    monkeypatch.setattr(ProjectModel, "base_dir", staticmethod(lambda: tmp_path / "RSNA Anonymizer"))
    result = mcp_tools.create_project(project_name="Phase1")
    assert result["ok"] is True
    return result


def test_import_directory_davidson(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _open_temp_project(tmp_path, monkeypatch)
    assert DAVIDSON.is_dir()
    result = mcp_tools.import_directory(str(DAVIDSON))
    assert result["ok"] is True
    assert result["files_seen"] >= 1
    assert result["succeeded"] >= 1
    assert result["failed"] == 0
    assert result["project"]["totals"]["patients"] >= 1
    assert result["project"]["totals"]["instances"] >= 1

    again = mcp_tools.import_directory(str(DAVIDSON))
    assert again["ok"] is True
    assert again["skipped"] >= 1
    assert again["succeeded"] == 0


def test_import_file_rejects_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _open_temp_project(tmp_path, monkeypatch)
    bad = mcp_tools.import_file(str(DAVIDSON))
    assert bad["ok"] is False
    assert "import_directory" in bad["error"]


def test_import_directory_rejects_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _open_temp_project(tmp_path, monkeypatch)
    dcm = next(DAVIDSON.glob("*.dcm"))
    bad = mcp_tools.import_directory(str(dcm))
    assert bad["ok"] is False
    assert "import_file" in bad["error"]


def test_import_file_davidson_dcm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _open_temp_project(tmp_path, monkeypatch)
    dcm = next(DAVIDSON.glob("*.dcm"))
    result = mcp_tools.import_file(str(dcm))
    assert result["ok"] is True
    assert result["files_seen"] == 1
    assert result["succeeded"] == 1
    assert result["project"]["totals"]["instances"] >= 1
    assert result["project"]["imported_modalities"]  # e.g. CR/DX from davidson
    info = mcp_tools.project_info()
    assert info["ok"] is True
    assert info["project"]["imported_modalities"] == result["project"]["imported_modalities"]


def test_configure_remote_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _open_temp_project(tmp_path, monkeypatch)
    result = mcp_tools.configure_remote("10.0.0.5", 11112, "PACS_AE", role="QUERY")
    assert result["ok"] is True
    assert result["remote"]["ip"] == "10.0.0.5"
    assert result["remote"]["port"] == 11112
    assert result["remote"]["aet"] == "PACS_AE"
    assert "QUERY" in result["project"]["remote_scps"]
    assert result["project"]["remote_scps"]["QUERY"]["aet"] == "PACS_AE"


def test_pacs_find_serializes_allowlisted_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _open_temp_project(tmp_path, monkeypatch)
    mcp_tools.configure_remote("127.0.0.1", 4242, "ORTHANC")

    ds = Dataset()
    ds.StudyInstanceUID = "1.2.3"
    ds.PatientID = "PHI-PT"
    ds.PatientName = "SECRET^NAME"
    ds.StudyDate = "20240101"
    ds.StudyDescription = "CT HEAD"
    ds.ModalitiesInStudy = "CT"
    ds.AccessionNumber = "ACC1"
    ds.NumberOfStudyRelatedSeries = "2"
    ds.NumberOfStudyRelatedInstances = "40"

    SESSION.controller.find_studies = MagicMock(return_value=[ds])
    result = mcp_tools.pacs_find(modality="CT")
    assert result["ok"] is True
    assert result["count"] == 1
    study = result["studies"][0]
    assert study["study_instance_uid"] == "1.2.3"
    assert study["patient_id"] == "PHI-PT"
    assert study["modalities_in_study"] == "CT"
    assert "patient_name" not in study
    assert "SECRET" not in str(result)


def test_pacs_move_requires_studies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _open_temp_project(tmp_path, monkeypatch)
    empty = mcp_tools.pacs_move([])
    assert empty["ok"] is False
    assert "empty" in empty["error"].lower()
