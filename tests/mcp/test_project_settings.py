"""MCP project settings: defaults, validation ranges, create/update."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.mcp import api as mcp_tools
from anonymizer.mcp.session import SESSION
from anonymizer.model import settings_limits as lim
from anonymizer.model.project import ProjectModel
from anonymizer.model.settings_validate import (
    SettingsValidationError,
    validate_aet,
    validate_ip,
    validate_port,
    validate_project_name,
    validate_site_id,
    validate_uid_root,
)
from anonymizer.view.common import ux_fields


@pytest.fixture(autouse=True)
def _isolated_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ProjectModel, "base_dir", staticmethod(lambda: tmp_path / "RSNA Anonymizer"))
    SESSION.close()
    yield
    SESSION.close()


def test_ux_fields_reexports_settings_limits():
    assert ux_fields.ip_port_min == lim.IP_PORT_MIN
    assert ux_fields.ip_port_max == lim.IP_PORT_MAX
    assert ux_fields.aet_max_chars == lim.AET_MAX_CHARS
    assert ux_fields.ip_min_chars == lim.IP_MIN_CHARS


def test_validate_rejects_out_of_range():
    with pytest.raises(SettingsValidationError, match="project_name"):
        validate_project_name("AB")
    with pytest.raises(SettingsValidationError, match="site_id"):
        validate_site_id("12")
    with pytest.raises(SettingsValidationError, match="site_id"):
        validate_site_id("ABC")
    with pytest.raises(SettingsValidationError, match="uid_root"):
        validate_uid_root("1a.2")
    with pytest.raises(SettingsValidationError, match="port"):
        validate_port(103)
    with pytest.raises(SettingsValidationError, match="aet"):
        validate_aet("AB")
    with pytest.raises(SettingsValidationError, match="ip"):
        validate_ip("999.1.1.1")


def test_project_settings_defaults_ok():
    result = mcp_tools.project_settings_defaults()
    assert result["ok"] is True
    assert "defaults" in result
    assert "scp" in result["defaults"]
    assert "network_timeouts" in result["defaults"]
    assert "dimse_vs_dicomweb" in result["help"]
    assert "en_US" in result["language_codes"]


def test_create_with_custom_settings():
    result = mcp_tools.create_project(
        project_name="Custom Setup",
        site_id="778899",
        uid_root="1.2.3.4.5",
        language_code="es",
        modalities=["CT", "MR"],
        scp={"ip": "127.0.0.1", "port": 11112, "aet": "LOCALAE"},
        network_timeouts={"tcp_connection": 10, "acse": 60, "dimse": 60, "network": 120},
    )
    assert result["ok"] is True
    project = result["project"]
    assert project["site_id"] == "778899"
    assert project["uid_root"] == "1.2.3.4.5"
    assert project["language_code"] == "es"
    assert project["modalities"] == ["CT", "MR"]
    assert project["local_scp"]["port"] == 11112
    assert project["local_scp"]["aet"] == "LOCALAE"
    assert project["local_scu"]["port"] == 11112
    assert project["network_timeouts"]["tcp_connection"] == 10.0


def test_create_rejects_bad_port():
    result = mcp_tools.create_project(
        project_name="Bad Port",
        scp={"port": 50},
    )
    assert result["ok"] is False
    assert "port" in result["error"].lower()


def test_create_rejects_short_name():
    result = mcp_tools.create_project(project_name="AB")
    assert result["ok"] is False
    assert "project_name" in result["error"].lower()


def test_update_project_settings_language_and_scp():
    assert mcp_tools.create_project(project_name="Update Me")["ok"]
    result = mcp_tools.update_project_settings(
        language_code="fr",
        scp={"aet": "NEWLOCAL"},
        network_timeouts={"network": 300},
    )
    assert result["ok"] is True
    project = result["project"]
    assert project["language_code"] == "fr"
    assert project["local_scp"]["aet"] == "NEWLOCAL"
    assert project["local_scu"]["aet"] == "NEWLOCAL"
    assert project["network_timeouts"]["network"] == 300.0


def test_update_rejects_empty_payload():
    assert mcp_tools.create_project(project_name="Empty Upd")["ok"]
    result = mcp_tools.update_project_settings()
    assert result["ok"] is False


def test_update_rejects_identity_extra_fields():
    assert mcp_tools.create_project(project_name="No Identity")["ok"]
    # Schema forbids extras — handler/parse must reject project_name on update.
    from pydantic import ValidationError

    from anonymizer.mcp.api.schemas import UpdateProjectSettingsArgs

    with pytest.raises(ValidationError):
        UpdateProjectSettingsArgs.model_validate({"project_name": "Hacked"})


def test_configure_remote_rejects_low_port():
    assert mcp_tools.create_project(project_name="Remote Port")["ok"]
    result = mcp_tools.configure_remote("10.0.0.1", 80, "PACS_AE", role="QUERY")
    assert result["ok"] is False
    assert "port" in result["error"].lower()


def test_configure_remote_description_mentions_transport():
    from anonymizer.mcp.api.catalog import TOOL_CATALOG

    spec = next(s for s in TOOL_CATALOG if s.name == "configure_remote")
    text = (spec.description or "").lower()
    assert "dimse" in text
    assert "dicomweb" in text


def test_project_info_includes_settings_fields():
    assert mcp_tools.create_project(project_name="Info Rich")["ok"]
    info = mcp_tools.project_info()
    assert info["ok"] is True
    project = info["project"]
    assert "language_code" in project
    assert "network_timeouts" in project
    assert "local_scu" in project
    assert "transfer_syntaxes" in project
    assert "storage_dir" not in project
