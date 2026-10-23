"""L1: replay scenario expected_trace via MCP tool handlers (no LLM, no live server)."""

from pathlib import Path

import pytest
import yaml

from anonymizer.mcp import api as mcp_tools
from anonymizer.mcp.session import SESSION
from anonymizer.model.project import ProjectModel
from anonymizer.utils.translate import set_language_code

SCENARIOS = Path(__file__).parent / "scenarios" / "mvp.yaml"
DAVIDSON_DCM = next(
    (
        Path(__file__).resolve().parent.parent
        / "controller"
        / "assets"
        / "test_dcm_files"
        / "davidson_cxr"
    ).glob("*.dcm")
)


@pytest.fixture(autouse=True)
def _isolated_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_language_code("en_US")
    monkeypatch.setattr(ProjectModel, "base_dir", staticmethod(lambda: tmp_path / "RSNA Anonymizer"))
    SESSION.close()
    yield
    SESSION.close()


def _load_scenarios() -> list[dict]:
    return yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


def _call_tool(name: str, arguments: dict):
    fn = getattr(mcp_tools, name)
    return fn(**arguments)


def test_scripted_setup_defaults_local_create():
    """Replay the defaults + two-phase local-create flow."""
    defaults = _call_tool("project_settings_defaults", {})
    assert defaults["ok"] is True
    assert "configuration_confirmation" in defaults["help"]

    prepared = _call_tool(
        "create_project",
        {"project_name": "DemoCXR", "confirm": False},
    )
    assert prepared["status"] == "confirmation_required"
    assert prepared["created"] is False

    created = _call_tool(
        "create_project",
        {
            "project_name": "DemoCXR",
            "confirm": True,
            "revision": prepared["revision"],
        },
    )
    assert created["ok"] is True
    assert created["status"] == "created"


def test_scripted_import_after_confirmed_create():
    """A confirmed project can import immediately; no plan/update is needed."""
    prepared = _call_tool("create_project", {"project_name": "GateDemo"})
    assert prepared["status"] == "confirmation_required"
    created = _call_tool(
        "create_project",
        {
            "project_name": "GateDemo",
            "confirm": True,
            "revision": prepared["revision"],
        },
    )
    assert created["ok"] is True

    ok = _call_tool("import_file", {"file_path": str(DAVIDSON_DCM)})
    assert ok["ok"] is True
    assert ok["succeeded"] == 1

    inv = _call_tool("list_inventory", {})
    assert inv["ok"] is True
    assert inv["count"] >= 1


def test_scripted_clinical_and_dimse_remote():
    defaults = _call_tool("project_settings_defaults", {})
    help_blob = str(defaults.get("help") or "")
    assert "confidentiality_options" in (defaults.get("help") or {})
    assert "113100" in help_blob

    prepared = _call_tool(
        "create_project",
        {
            "project_name": "ClinicalDemo",
            "confidentiality_options": [113100, 113107, 113108, 113111],
            "confirm": False,
        },
    )
    assert prepared["configuration"]["confidentiality_options"] == [113100, 113107, 113108, 113111]
    created = _call_tool(
        "create_project",
        {
            "project_name": "ClinicalDemo",
            "confirm": True,
            "revision": prepared["revision"],
        },
    )
    assert created["ok"] is True

    remote = _call_tool(
        "configure_remote",
        {
            "ip": "10.0.0.5",
            "port": 104,
            "aet": "ORTHANC",
            "role": "QUERY",
            "dicomweb": False,
        },
    )
    assert remote["ok"] is True
    assert remote["remote"]["dicomweb"] is False


def test_scenario_yaml_pack_is_creation_and_settings_only():
    """Default pack sticks to project creation / settings modification."""
    cases = {case["id"]: case for case in _load_scenarios()}
    assert len(cases) == 10
    tools_used = {
        step["tool"]
        for case in cases.values()
        for step in (case.get("expected_trace") or [])
        if step.get("tool")
    }
    assert tools_used <= {"create_project", "update_project_settings", "project_info"}
    confirmation = cases["create_defaults_then_confirm"]["expected_trace"]
    assert confirmation[0]["before_clarify"] is True
    assert confirmation[0]["arguments"]["confirm"] is False
    assert confirmation[1]["after_clarify"] is True
    assert confirmation[1]["arguments"]["confirm"] is True
    assert confirmation[1]["arguments"]["revision"] == 1
    revision = cases["create_custom_then_revise"]["expected_trace"]
    assert revision[1]["after_clarify"] is True
    assert revision[1]["arguments"]["confirm"] is False
    ask_path = Path(__file__).parent / "scenarios" / "ask_gate.yaml"
    ask = {s["id"]: s for s in yaml.safe_load(ask_path.read_text(encoding="utf-8"))["scenarios"]}
    case = ask["import_first_must_setup"]
    assert "forbidden_first_tools" in case
    assert "import_file" in case["forbidden_first_tools"]
