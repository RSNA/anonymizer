"""Unit tests for every MCP tool API (one success + key failure per tool).

These call the tool modules directly (same functions registered in ``create_server``),
so coverage tracks the advertised LLM-facing API without requiring a live HTTP server.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydicom.dataset import Dataset

from anonymizer.mcp.server import create_server
from anonymizer.mcp.session import SESSION
from anonymizer.mcp.tools import MCP_TOOL_NAMES
from anonymizer.mcp import tools as mcp_tools
from anonymizer.model.project import ProjectModel
from anonymizer.utils.translate import set_language_code

DAVIDSON = (
    Path(__file__).resolve().parent.parent
    / "controller"
    / "assets"
    / "test_dcm_files"
    / "davidson_cxr"
)
DAVIDSON_DCM = next(DAVIDSON.glob("*.dcm"))

EXPECTED_MCP_TOOLS = frozenset(MCP_TOOL_NAMES)


@pytest.fixture(autouse=True)
def _isolated_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_language_code("en_US")
    monkeypatch.setattr(ProjectModel, "base_dir", staticmethod(lambda: tmp_path / "RSNA Anonymizer"))
    SESSION.close()
    yield
    SESSION.close()


def _create_open(name: str = "ApiProj") -> dict:
    result = mcp_tools.create_project(project_name=name, overwrite=True)
    assert result["ok"] is True
    return result


def _import_davidson() -> dict:
    result = mcp_tools.import_file(str(DAVIDSON_DCM))
    assert result["ok"] is True
    assert result["succeeded"] == 1
    return result


# --- Catalog / registration -------------------------------------------------


def test_create_server_registers_every_advertised_tool():
    server = create_server()
    listed = getattr(server, "_tool_manager", None)
    assert listed is not None
    names = {info.name for info in listed.list_tools()}
    assert names == EXPECTED_MCP_TOOLS


# --- list_projects ----------------------------------------------------------


def test_api_list_projects_empty_store():
    result = mcp_tools.list_projects()
    assert result["ok"] is True
    assert result["count"] == 0
    assert result["projects"] == []
    assert "base_dir" in result


def test_api_list_projects_after_create():
    _create_open("Listed")
    SESSION.close()
    result = mcp_tools.list_projects()
    assert result["ok"] is True
    assert result["count"] >= 1
    assert any(p["project_name"] == "Listed" for p in result["projects"])


# --- create_project ---------------------------------------------------------


def test_api_create_project_ok():
    result = mcp_tools.create_project(project_name="Created", site_id="SITE1")
    assert result["ok"] is True
    assert result["project"]["project_name"] == "Created"
    assert result["project"]["site_id"] == "SITE1"
    assert result["project"]["totals"]["patients"] == 0
    assert SESSION.is_open


def test_api_create_project_rejects_empty_name():
    result = mcp_tools.create_project(project_name="  ")
    assert result["ok"] is False
    assert "required" in result["error"].lower() or "project_name" in result["error"].lower()


# --- project_open -----------------------------------------------------------


def test_api_project_open_ok():
    _create_open("ToOpen")
    SESSION.close()
    assert not SESSION.is_open
    result = mcp_tools.project_open(project_name="ToOpen")
    assert result["ok"] is True
    assert result["project"]["project_name"] == "ToOpen"
    assert SESSION.is_open


def test_api_project_open_missing_returns_error():
    result = mcp_tools.project_open(project_name="DoesNotExist")
    assert result["ok"] is False
    assert result["error"]


# --- project_info -----------------------------------------------------------


def test_api_project_info_ok():
    _create_open("InfoMe")
    result = mcp_tools.project_info()
    assert result["ok"] is True
    assert result["project"]["project_name"] == "InfoMe"
    assert "imported_modalities" in result["project"]
    assert "modalities" in result["project"]
    assert "totals" in result["project"]


def test_api_project_info_without_session():
    result = mcp_tools.project_info()
    assert result["ok"] is False
    assert "no project" in result["error"].lower()


# --- import_file / import_directory -----------------------------------------


def test_api_import_file_ok():
    _create_open()
    result = mcp_tools.import_file(str(DAVIDSON_DCM))
    assert result["ok"] is True
    assert result["files_seen"] == 1
    assert result["succeeded"] == 1
    assert result["project"]["totals"]["instances"] >= 1
    assert result["project"]["imported_modalities"]


def test_api_import_file_without_session():
    result = mcp_tools.import_file(str(DAVIDSON_DCM))
    assert result["ok"] is False


def test_api_import_directory_ok():
    _create_open()
    result = mcp_tools.import_directory(str(DAVIDSON))
    assert result["ok"] is True
    assert result["succeeded"] >= 1
    assert result["failed"] == 0


def test_api_import_directory_without_session():
    result = mcp_tools.import_directory(str(DAVIDSON))
    assert result["ok"] is False


# --- list_inventory ---------------------------------------------------------


def test_api_list_inventory_ok():
    _create_open()
    _import_davidson()
    result = mcp_tools.list_inventory()
    assert result["ok"] is True
    assert result["count"] >= 1
    row = result["series"][0]
    assert row["anon_patient_id"]
    assert row["patient_index"] == 1
    assert row["study_index"] == 1
    assert row["series_index"] == 1
    assert row["row_index"] == 1
    assert "series_description" in row
    assert "study_description" in row
    assert isinstance(row["study_description"], str)
    assert isinstance(row["series_description"], str)
    # Davidson CXR carries a study description into the ORM / inventory.
    assert row["study_description"].strip() != ""
    assert "study_description" in result["table"].splitlines()[0]
    assert row["study_description"] in result["table"]
    assert "study_harmonized" in row
    assert "series_harmonized" in row
    assert "pixel_phi_scanned" in row
    assert isinstance(result.get("table"), str)
    assert "patient_index" in result["table"].splitlines()[0]
    assert "\t" in result["table"]
    assert "patient_name" not in row
    assert "series_path" not in row
    assert "anon_series_uid" not in row
    assert "anon_study_uid" not in row
    project = result.get("project") or {}
    assert "images_dir" not in project
    assert "storage_dir" not in project


def test_api_list_inventory_without_session():
    result = mcp_tools.list_inventory()
    assert result["ok"] is False


# --- remove_pixel_phi -------------------------------------------------------


def test_api_remove_pixel_phi_ok_mocked():
    _create_open()
    _import_davidson()
    fake_handle = MagicMock()
    fake_handle.reader = MagicMock()

    class _Outcome:
        status = "complete"
        message = "No burnt-in text detected"

    with (
        patch.object(SESSION, "ensure_ocr_reader", return_value=fake_handle),
        patch(
            "anonymizer.mcp.ops.apply_remove_pixel_phi_series",
            return_value=_Outcome(),
        ),
        patch.object(
            SESSION.controller.anonymizer.model,
            "series_pixel_phi_scanned",
            return_value=True,
        ),
    ):
        result = mcp_tools.remove_pixel_phi(modality_hint="cxr")

    assert result["ok"] is True
    assert result["status"] == "complete"
    assert result["pixel_phi_scanned"] is True
    assert result["anon_series_uid"]


def test_api_remove_pixel_phi_without_session():
    result = mcp_tools.remove_pixel_phi()
    assert result["ok"] is False


# --- harmonize_studies ------------------------------------------------------


def test_api_harmonize_studies_ok_mocked():
    from anonymizer.controller.ai.harmonize import HarmonizeStudiesSummary

    _create_open()
    _import_davidson()
    with patch.object(
        SESSION.controller,
        "harmonize_studies",
        return_value=HarmonizeStudiesSummary(processed=1, applied=1, skipped=0, failed=0),
    ) as mock_h:
        with patch(
            "anonymizer.mcp.ops.auto_apply_best_study_descriptions",
            return_value=[],
        ) as mock_study:
            result = mcp_tools.harmonize_studies()
    assert result["ok"] is True
    assert result["study_count"] == 1
    assert result["applied"] == 1
    assert result["study_descriptions_applied"] == 0
    mock_h.assert_called_once()
    mock_study.assert_called_once()
    studies_arg = mock_h.call_args.args[0]
    assert len(studies_arg) == 1
    assert all(isinstance(t, tuple) and len(t) == 2 for t in studies_arg)


def test_api_harmonize_studies_patient_all_mocked():
    from anonymizer.controller.ai.harmonize import HarmonizeStudiesSummary

    _create_open()
    _import_davidson()
    with patch.object(
        SESSION.controller,
        "harmonize_studies",
        return_value=HarmonizeStudiesSummary(processed=1, applied=1, skipped=0, failed=0),
    ) as mock_h:
        with patch("anonymizer.mcp.ops.auto_apply_best_study_descriptions", return_value=[]):
            result = mcp_tools.harmonize_studies(patient="all")
    assert result["ok"] is True
    assert result["study_count"] == 1
    mock_h.assert_called_once()


def test_api_harmonize_studies_patient_selector_mocked():
    from anonymizer.controller.ai.harmonize import HarmonizeStudiesSummary

    _create_open()
    _import_davidson()
    with patch.object(
        SESSION.controller,
        "harmonize_studies",
        return_value=HarmonizeStudiesSummary(processed=1, applied=1, skipped=0, failed=0),
    ) as mock_h:
        with patch("anonymizer.mcp.ops.auto_apply_best_study_descriptions", return_value=[]):
            result = mcp_tools.harmonize_studies(patient="1", study="1")
    assert result["ok"] is True
    assert result["study_count"] == 1
    mock_h.assert_called_once()


def test_api_harmonize_studies_without_session():
    result = mcp_tools.harmonize_studies()
    assert result["ok"] is False


# --- resolve_series / friendly selectors ------------------------------------


def test_api_resolve_series_rejects_relative_selectors():
    _create_open()
    _import_davidson()
    result = mcp_tools.resolve_series(patient="latest", series="1")
    assert result["ok"] is False
    assert "not supported" in (result.get("error") or "").lower()


def test_api_resolve_series_patient_index():
    _create_open()
    _import_davidson()
    result = mcp_tools.resolve_series(patient="1", series="cxr")
    assert result["ok"] is True
    assert result.get("anon_patient_id")
    assert result.get("caption")
    assert "—" in result["caption"]
    assert "series_path" not in result


def test_api_resolve_series_patient_by_inventory_index():
    """patient=N matches list_inventory patient_index (1-based)."""
    _create_open()
    _import_davidson()
    inv = mcp_tools.list_inventory()
    assert inv["ok"] is True
    pid = inv["series"][0]["anon_patient_id"]
    idx = inv["series"][0]["patient_index"]
    result = mcp_tools.resolve_series(patient=str(idx), series="1")
    assert result["ok"] is True
    assert result["anon_patient_id"] == pid
    result_first = mcp_tools.resolve_series(patient="1", series="1")
    assert result_first["ok"] is True
    assert result_first["anon_patient_id"] == pid


def test_api_export_series_preview_patient_index():
    _create_open()
    _import_davidson()
    result = mcp_tools.export_series_preview(
        patient="1",
        series="1",
        require_pixel_phi_scanned=False,
    )
    assert result["ok"] is True
    assert result.get("caption")
    assert result.get("anon_patient_id")
    assert result["width"] == 448


def test_api_resolve_series_without_session():
    result = mcp_tools.resolve_series(patient="1")
    assert result["ok"] is False


# --- export_series_preview --------------------------------------------------


def test_api_export_series_preview_ok_gate_off():
    _create_open()
    _import_davidson()
    result = mcp_tools.export_series_preview(
        modality_hint="cxr",
        require_pixel_phi_scanned=False,
    )
    assert result["ok"] is True
    import base64

    raw = base64.b64decode(result["preview_base64"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert result["mime_type"] == "image/png"
    assert result["byte_length"] == len(raw)
    assert "preview_path" not in result
    assert result["width"] > 0
    assert result["height"] > 0
    assert result["format"] == "png"
    assert result.get("anon_patient_id")
    assert "series_description" in result
    assert result["width"] == 448
    assert result["height"] == 448
    assert result.get("size") == 448


def test_api_export_series_preview_without_session():
    result = mcp_tools.export_series_preview(require_pixel_phi_scanned=False)
    assert result["ok"] is False


# --- configure_remote -------------------------------------------------------


def test_api_configure_remote_query_ok():
    _create_open()
    result = mcp_tools.configure_remote("10.1.2.3", 104, "PACS_AE", role="QUERY")
    assert result["ok"] is True
    assert result["role"] == "QUERY"
    assert result["remote"]["ip"] == "10.1.2.3"
    assert result["remote"]["aet"] == "PACS_AE"
    assert "QUERY" in result["project"]["remote_scps"]


def test_api_configure_remote_export_ok():
    _create_open()
    result = mcp_tools.configure_remote("10.1.2.4", 11112, "EXPORT_AE", role="EXPORT")
    assert result["ok"] is True
    assert result["role"] == "EXPORT"
    assert "EXPORT" in result["project"]["remote_scps"]


def test_api_configure_remote_bad_role():
    _create_open()
    result = mcp_tools.configure_remote("1.1.1.1", 104, "AE", role="NOPE")
    assert result["ok"] is False
    assert "role" in result["error"].lower()


def test_api_configure_remote_without_session():
    result = mcp_tools.configure_remote("1.1.1.1", 104, "AE")
    assert result["ok"] is False


# --- pacs_find --------------------------------------------------------------


def test_api_pacs_find_ok_mocked():
    _create_open()
    assert mcp_tools.configure_remote("127.0.0.1", 4242, "ORTHANC")["ok"]

    ds = Dataset()
    ds.StudyInstanceUID = "1.2.3"
    ds.PatientID = "PT1"
    ds.PatientName = "SECRET^NAME"
    ds.StudyDate = "20240101"
    ds.StudyDescription = "CXR"
    ds.ModalitiesInStudy = "CR"
    ds.AccessionNumber = "A1"
    ds.NumberOfStudyRelatedSeries = "1"
    ds.NumberOfStudyRelatedInstances = "1"

    SESSION.controller.find_studies = MagicMock(return_value=[ds])
    result = mcp_tools.pacs_find(modality="CR")
    assert result["ok"] is True
    assert result["count"] == 1
    study = result["studies"][0]
    assert study["study_instance_uid"] == "1.2.3"
    assert "PatientName" not in study
    assert "patient_name" not in study
    assert "SECRET" not in str(result)


def test_api_pacs_find_requires_remote():
    _create_open()
    # New projects ship with a default QUERY SCP; clear it to exercise the guard.
    SESSION.controller.model.remote_scps.clear()
    result = mcp_tools.pacs_find()
    assert result["ok"] is False
    assert "configure_remote" in result["error"].lower() or "remote" in result["error"].lower()


def test_api_pacs_find_without_session():
    result = mcp_tools.pacs_find()
    assert result["ok"] is False


# --- pacs_move --------------------------------------------------------------


def test_api_pacs_move_ok_mocked():
    from anonymizer.controller.project import SeriesUIDHierarchy

    _create_open()
    assert mcp_tools.configure_remote("127.0.0.1", 4242, "ORTHANC")["ok"]

    def _fake_hierarchies(_scp, hierarchies, instance_level=False):
        for study in hierarchies:
            study.series = {
                "1.2.3.4": SeriesUIDHierarchy(uid="1.2.3.4", modality="CR", instance_count=1)
            }
            study.last_error_msg = None

    SESSION.ensure_scp = MagicMock()
    SESSION.controller.get_study_uid_hierarchies = MagicMock(side_effect=_fake_hierarchies)
    SESSION.controller._manage_move = MagicMock()

    result = mcp_tools.pacs_move(
        studies=[{"study_instance_uid": "1.2.3", "patient_id": "PT1"}],
        level="SERIES",
    )
    assert result["ok"] is True
    assert result["dest_aet"]
    assert len(result["studies"]) == 1
    SESSION.controller._manage_move.assert_called_once()


def test_api_pacs_move_empty_studies():
    _create_open()
    assert mcp_tools.configure_remote("127.0.0.1", 4242, "ORTHANC")["ok"]
    result = mcp_tools.pacs_move(studies=[])
    assert result["ok"] is False
    assert "empty" in result["error"].lower()


def test_api_pacs_move_without_session():
    result = mcp_tools.pacs_move(studies=[{"study_instance_uid": "1.2.3", "patient_id": "x"}])
    assert result["ok"] is False


# --- Parametrized: every session-bound tool rejects missing project ---------


@pytest.mark.parametrize(
    "call",
    [
        lambda: mcp_tools.project_info(),
        lambda: mcp_tools.list_inventory(),
        lambda: mcp_tools.resolve_series(patient="1"),
        lambda: mcp_tools.remove_pixel_phi(),
        lambda: mcp_tools.harmonize_studies(),
        lambda: mcp_tools.export_series_preview(require_pixel_phi_scanned=False),
        lambda: mcp_tools.import_file(str(DAVIDSON_DCM)),
        lambda: mcp_tools.import_directory(str(DAVIDSON)),
        lambda: mcp_tools.configure_remote("1.1.1.1", 104, "AE"),
        lambda: mcp_tools.pacs_find(),
        lambda: mcp_tools.pacs_move([{"study_instance_uid": "1", "patient_id": "p"}]),
    ],
    ids=[
        "project_info",
        "list_inventory",
        "resolve_series",
        "remove_pixel_phi",
        "harmonize_studies",
        "export_series_preview",
        "import_file",
        "import_directory",
        "configure_remote",
        "pacs_find",
        "pacs_move",
    ],
)
def test_api_tools_require_open_project(call):
    result = call()
    assert result["ok"] is False
    assert result.get("error")
