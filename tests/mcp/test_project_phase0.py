"""Phase 0 MCP project session / tool tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.project import ProjectController
from anonymizer.mcp.session import SESSION, ProjectSession, ProjectSessionError
from anonymizer.mcp import tools as mcp_tools
from anonymizer.model.project import ProjectModel


@pytest.fixture(autouse=True)
def _isolated_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep SESSION clean and pin the default store under tmp_path."""
    monkeypatch.setattr(ProjectModel, "base_dir", staticmethod(lambda: tmp_path / "RSNA Anonymizer"))
    SESSION.close()
    yield
    SESSION.close()


def test_create_project_writes_model_and_opens_session(tmp_path: Path):
    result = mcp_tools.create_project(
        project_name="Research CT Head",
        site_id="SITE99",
        uid_root="1.2.3.4.5",
    )
    assert result["ok"] is True
    project = result["project"]
    assert project["project_name"] == "Research CT Head"
    assert project["site_id"] == "SITE99"
    assert project["uid_root"] == "1.2.3.4.5"
    assert project["totals"]["patients"] == 0
    assert "storage_dir" not in project
    assert "images_dir" not in project
    storage = tmp_path / "RSNA Anonymizer" / "Research CT Head"
    assert (storage / ProjectController.PROJECT_MODEL_FILENAME_JSON).is_file()
    assert SESSION.is_open


def test_create_project_requires_overwrite_to_replace():
    first = mcp_tools.create_project(project_name="One")
    assert first["ok"] is True
    SESSION.close()

    blocked = mcp_tools.create_project(project_name="One", overwrite=False)
    assert blocked["ok"] is False
    assert "overwrite" in blocked["error"].lower()

    overwritten = mcp_tools.create_project(project_name="One", overwrite=True)
    assert overwritten["ok"] is True
    assert overwritten["project"]["project_name"] == "One"


def test_create_project_with_existing_storage_dir(tmp_path: Path):
    custom = tmp_path / "custom_store" / "MyProj"
    custom.mkdir(parents=True)
    result = mcp_tools.create_project(project_name="MyProj", storage_dir=str(custom))
    assert result["ok"] is True
    assert result["project"]["project_name"] == "MyProj"
    assert "storage_dir" not in result["project"]
    assert (custom / ProjectController.PROJECT_MODEL_FILENAME_JSON).is_file()


def test_create_project_rejects_missing_storage_dir(tmp_path: Path):
    missing = tmp_path / "does_not_exist"
    result = mcp_tools.create_project(project_name="X", storage_dir=str(missing))
    assert result["ok"] is False
    assert "does not exist" in result["error"].lower()


def test_project_open_by_name():
    created = mcp_tools.create_project(project_name="Open Me")
    assert created["ok"] is True
    SESSION.close()

    opened = mcp_tools.project_open(project_name="Open Me")
    assert opened["ok"] is True
    assert opened["project"]["project_name"] == "Open Me"


def test_project_open_by_storage_dir(tmp_path: Path):
    custom = tmp_path / "open_by_path"
    custom.mkdir()
    assert mcp_tools.create_project(project_name="PathOpen", storage_dir=str(custom))["ok"]
    SESSION.close()

    opened = mcp_tools.project_open(storage_dir=str(custom))
    assert opened["ok"] is True
    assert opened["project"]["project_name"] == "PathOpen"


def test_project_info_without_open_returns_error():
    result = mcp_tools.project_info()
    assert result["ok"] is False
    assert "no project" in result["error"].lower()


def test_create_project_rejects_path_like_names_when_using_default_store():
    bad = mcp_tools.create_project(project_name="../escape")
    assert bad["ok"] is False
    assert "path segment" in bad["error"].lower() or "slash" in bad["error"].lower()


def test_project_info_after_create():
    assert mcp_tools.create_project(project_name="Info")["ok"]
    info = mcp_tools.project_info()
    assert info["ok"] is True
    assert info["project"]["project_name"] == "Info"
    assert info["project"]["imported_modalities"] == []
    assert isinstance(info["project"]["modalities"], list)
    assert len(info["project"]["modalities"]) >= 1


def test_list_projects_finds_created():
    assert mcp_tools.create_project(project_name="Alpha")["ok"]
    SESSION.close()
    assert mcp_tools.create_project(project_name="Beta")["ok"]
    listed = mcp_tools.list_projects()
    assert listed["ok"] is True
    names = {p["project_name"] for p in listed["projects"]}
    assert {"Alpha", "Beta"} <= names
    assert listed["count"] >= 2


def test_mcp_call_logging_middleware_logs(caplog: pytest.LogCaptureFixture):
    import asyncio

    from anonymizer.mcp.call_logging import McpCallLoggingMiddleware

    class _Ctx:
        method = "tools/call"
        params = {"name": "project_info", "arguments": {}}

    async def _next(_ctx):
        class _Result:
            isError = False
            content = [type("T", (), {"text": '{"ok": true}'})()]

        return _Result()

    with caplog.at_level("INFO", logger="anonymizer.mcp"):
        asyncio.run(McpCallLoggingMiddleware()(_Ctx(), _next))
    text = "\n".join(r.message for r in caplog.records)
    assert "MCP ← tools/call" in text
    assert "project_info" in text
    assert "MCP → tools/call" in text


def test_mcp_call_logging_logs_initialize_instructions(caplog: pytest.LogCaptureFixture):
    import asyncio

    from anonymizer.mcp.call_logging import McpCallLoggingMiddleware
    from anonymizer.mcp.instructions import load_server_instructions

    instructions = load_server_instructions()

    class _Ctx:
        method = "initialize"
        params = {}

    async def _next(_ctx):
        return type("InitResult", (), {"instructions": instructions})()

    with caplog.at_level("INFO", logger="anonymizer.mcp"):
        asyncio.run(McpCallLoggingMiddleware()(_Ctx(), _next))
    text = "\n".join(r.message for r in caplog.records)
    assert "MCP ← initialize" in text
    assert "MCP → initialize instructions returned to client" in text
    assert "create_project" in text
    assert "list_inventory" in text


def test_mcp_call_logging_logs_tools_list(caplog: pytest.LogCaptureFixture):
    import asyncio

    from anonymizer.mcp.call_logging import McpCallLoggingMiddleware

    class _Tool:
        def model_dump(self, by_alias: bool = False, exclude_none: bool = False):
            return {
                "name": "create_project",
                "description": "Create a new empty project.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "Project display name (required).",
                        }
                    },
                    "required": ["project_name"],
                },
            }

    class _Ctx:
        method = "tools/list"
        params = {}

    async def _next(_ctx):
        return type("ListResult", (), {"tools": [_Tool()]})()

    with caplog.at_level("INFO", logger="anonymizer.mcp"):
        asyncio.run(McpCallLoggingMiddleware()(_Ctx(), _next))
    text = "\n".join(r.message for r in caplog.records)
    assert "MCP ← tools/list" in text
    assert "MCP → tools/list returned to client" in text
    assert "create_project" in text
    assert "Project display name" in text
    assert "inputSchema" in text


def test_resolve_missing_path_raises(tmp_path: Path):
    session = ProjectSession()
    with pytest.raises(ProjectSessionError):
        session.open_path(tmp_path / "missing")


def test_run_mcp_keyboard_interrupt_exits_cleanly(monkeypatch: pytest.MonkeyPatch):
    """Ctrl-C after uvicorn shutdown must exit 130 without a traceback."""
    from anonymizer.mcp import server as mcp_server

    class _FakeServer:
        def run(self, **_kwargs):
            raise KeyboardInterrupt

    closed: list[bool] = []

    monkeypatch.setattr(mcp_server, "create_server", lambda: _FakeServer())
    monkeypatch.setattr(mcp_server, "init_logging", lambda: "/tmp/logs")
    monkeypatch.setattr(mcp_server, "_preserve_logging_across_uvicorn", lambda: None)
    monkeypatch.setattr(mcp_server.SESSION, "close", lambda: closed.append(True))

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.run_MCP(transport="streamable-http", port=0, init_logs=True)
    assert exc_info.value.code == 130
    assert closed == [True]


def test_uvicorn_log_config_patched_to_preserve_init_logging():
    from anonymizer.mcp.server import _preserve_logging_across_uvicorn

    _preserve_logging_across_uvicorn()
    import uvicorn

    cfg = uvicorn.Config(app=None, host="127.0.0.1", port=0, log_config={"version": 1})
    assert cfg.log_config is None
