"""Contract locks: setup wizard help, import gate, anonymization_policy, sibling tools."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from anonymizer.mcp import api as mcp_tools
from anonymizer.mcp.api.catalog import TOOL_CATALOG
from anonymizer.mcp.api.handlers import _parse
from anonymizer.mcp.api.schemas import (
    CONFIGURE_REMOTE_EXTRA_HINT,
    ConfigureRemoteArgs,
    ImportFileArgs,
)
from anonymizer.mcp.instructions import load_behavior_instructions, load_server_instructions
from anonymizer.mcp.ops import project_settings_defaults
from anonymizer.mcp.session import SESSION
from anonymizer.model.project import AnonymizationPolicy, ProjectModel
from anonymizer.utils.translate import set_language_code
from tests.mcp.project_create import confirm_create

DAVIDSON_DCM = next(
    (
        Path(__file__).resolve().parent.parent
        / "controller"
        / "assets"
        / "test_dcm_files"
        / "davidson_cxr"
    ).glob("*.dcm")
)

_REQUIRED_HELP = frozenset(
    {
        "usage",
        "configuration_confirmation",
        "anonymization_policy",
        "modalities",
        "transfer_syntaxes",
        "local_scp",
        "network_timeouts",
        "dimse_vs_dicomweb",
        "identity_locked",
    }
)


@pytest.fixture(autouse=True)
def _isolated_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_language_code("en_US")
    monkeypatch.setattr(ProjectModel, "base_dir", staticmethod(lambda: tmp_path / "RSNA Anonymizer"))
    SESSION.close()
    yield
    SESSION.close()


def test_mcp_defaults_merge_setup_help_keys():
    payload = project_settings_defaults()
    help_block = payload["help"]
    for key in _REQUIRED_HELP:
        assert key in help_block, key
    assert "setup_checklist" not in help_block
    assert "import_gate" not in help_block
    assert "confirm=false" in help_block["configuration_confirmation"]
    assert "confirm=true" in help_block["configuration_confirmation"]
    assert "DIMSE" in help_block["dimse_vs_dicomweb"]
    assert "DICOMweb" in help_block["dimse_vs_dicomweb"]


def test_instructions_confirmation_flow():
    load_server_instructions.cache_clear()
    text = load_server_instructions()
    assert "project_settings_defaults" in text
    assert "configuration_confirmation" in text or "confirmation_required" in text
    assert "confirm=false" in text
    assert "confirm=true" in text
    assert "import_plan" not in text
    assert "setup_checklist" not in text
    assert "anonymization_policy" in text
    assert "One tool per reply" in text or "one tool per" in text.lower()
    assert "DIMSE" in text and "DICOMweb" in text
    assert "do not assume DICOMweb" in text.lower() or "Do not assume DICOMweb" in text
    assert "import_file" in text and "import_directory" in text
    assert "AWS" in text or "desktop" in text.lower()
    for name in (
        "remove_pixel_phi",
        "harmonize_studies",
        "export_series_preview",
        "configure_remote",
        "pacs_find",
        "pacs_move",
    ):
        assert name in text


def test_create_with_clinical_policy():
    result = confirm_create(
        mcp_tools.create_project,
        project_name="ClinicalPol",
        anonymization_policy="clinical",
    )
    assert result["ok"] is True
    assert SESSION.controller.model.anonymization_policy is AnonymizationPolicy.CLINICAL
    assert "import_plan" not in result


def test_import_allowed_immediately_after_confirmed_create():
    assert confirm_create(mcp_tools.create_project, project_name="NoPlan")["ok"] is True
    imported = mcp_tools.import_file(str(DAVIDSON_DCM))
    assert imported["ok"] is True
    assert imported["succeeded"] == 1


def test_import_allowed_after_settings_update():
    assert confirm_create(mcp_tools.create_project, project_name="LatePlan")["ok"] is True
    assert mcp_tools.update_project_settings(modalities=["CR", "CT"])["ok"] is True
    imported = mcp_tools.import_file(str(DAVIDSON_DCM))
    assert imported["ok"] is True
    assert imported["succeeded"] == 1


def test_pacs_requires_query_remote_in_model():
    assert confirm_create(mcp_tools.create_project, project_name="PacsGate")["ok"] is True
    SESSION.controller.model.remote_scps.clear()
    blocked = mcp_tools.pacs_find()
    assert blocked["ok"] is False
    assert "query" in blocked["error"].lower() or "configure" in blocked["error"].lower()


def test_scenario_pack_loads():
    path = Path(__file__).parent / "scenarios" / "mvp.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenarios = data["scenarios"]
    assert len(scenarios) >= 8
    ids = {s["id"] for s in scenarios}
    assert "create_defaults_then_confirm" in ids
    assert "create_custom_then_revise" in ids
    assert "confirm_revised_configuration" in ids
    assert any(s.get("clarify") for s in scenarios)
    # Other-function scenarios live in functions.yaml.
    functions = yaml.safe_load(
        (Path(__file__).parent / "scenarios" / "functions.yaml").read_text(
            encoding="utf-8"
        )
    )["scenarios"]
    function_ids = {s["id"] for s in functions}
    assert "pacs_query_dimse_configure" in function_ids
    assert "pacs_naive_then_clarify_dimse" in function_ids
    assert "list_inventory" in str(functions)
    # Ask-vs-call pack is optional (not default NL).
    ask = yaml.safe_load(
        (Path(__file__).parent / "scenarios" / "ask_gate.yaml").read_text(encoding="utf-8")
    )["scenarios"]
    ask_ids = {s["id"] for s in ask}
    assert "import_first_must_setup" in ask_ids
    assert "pacs_ask_dimse_vs_dicomweb" in ask_ids


def _catalog_desc(name: str) -> str:
    return next(s for s in TOOL_CATALOG if s.name == name).description


def test_contract_configure_remote_arg_matrix():
    """Lock DIMSE vs DICOMweb field names — forbid host/protocol/path inventions."""
    desc = _catalog_desc("configure_remote").lower()
    assert "dicomweb=false" in desc
    assert "dicomweb=true" in desc
    assert "http_port" in desc and "http_path" in desc
    assert "never invent host" in desc or "never invent host," in desc
    assert "do not call yet" in desc

    props = ConfigureRemoteArgs.model_json_schema()["properties"]
    assert set(props) >= {"ip", "port", "aet", "dicomweb", "http_port", "http_path"}
    assert "host" not in props
    assert "protocol" not in props
    assert "path" not in props
    ip_desc = props["ip"]["description"].lower()
    assert "never host" in ip_desc or "not host" in ip_desc
    assert "protocol" in props["dicomweb"]["description"].lower()
    assert "http_path" in props["http_path"]["description"]
    assert "path" in props["http_path"]["description"].lower()


def test_contract_list_inventory_vs_project_info():
    inv = _catalog_desc("list_inventory").lower()
    info = _catalog_desc("project_info").lower()
    assert "series" in inv and "tsv" in inv
    assert "not project_info" in inv
    assert "settings" in info
    assert "list_inventory" in info
    assert "not the series inventory" in info or "series inventory" in info


def test_contract_import_file_vs_project_open():
    imp = _catalog_desc("import_file").lower()
    open_desc = _catalog_desc("project_open").lower()
    assert "file_path" in imp
    assert "project_open" in imp
    assert "does not import" in open_desc or "do not import" in open_desc
    assert "import_file" in open_desc

    props = ImportFileArgs.model_json_schema()["properties"]
    assert "file_path" in props
    assert "path" not in props
    assert "file_path" in props["file_path"]["description"]


def test_contract_create_requires_confirmation_callout():
    desc = _catalog_desc("create_project").lower()
    assert "confirm=false" in desc
    assert "confirm=true" in desc
    assert "confirmation_required" in desc
    assert "revision" in desc
    assert "import_plan" not in desc


def test_instructions_sibling_tools_and_pacs_ask():
    load_server_instructions.cache_clear()
    load_behavior_instructions.cache_clear()
    text = load_server_instructions()
    behavior = load_behavior_instructions()
    lower = text.lower()
    assert "sibling tools" in lower
    assert "list_inventory" in text and "project_info" in text
    assert "file_path" in text
    assert "do **not** call `configure_remote` yet" in text or "do not call `configure_remote` yet" in lower
    assert "dicomweb=false" in text and "dicomweb=true" in text
    # Early block must survive NL harness (behavior asset, not truncated Tool API).
    assert "Exact argument names" in behavior
    assert "hostname" in behavior and "aetitle" in behavior
    assert "what is in the project" in behavior.lower()


def test_configure_remote_reject_hints_known_synonyms():
    """Wrong keys return the shared retry hint (Qwen host/protocol failures)."""
    _, err = _parse(
        ConfigureRemoteArgs,
        {
            "hostname": "10.0.0.5",
            "port": 104,
            "aetitle": "ORTHANC",
            "protocol": "DIMSE",
        },
    )
    assert err is not None
    assert err["ok"] is False
    assert CONFIGURE_REMOTE_EXTRA_HINT in err["error"]
    assert "host" in err["error"].lower()
