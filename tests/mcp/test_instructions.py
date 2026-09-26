"""MCP InitializeResult.instructions + typed tool JSON Schema."""

from __future__ import annotations

import asyncio
import json
import re

from anonymizer.mcp.api import MCP_TOOL_NAMES, TOOL_INPUT_MODELS, ZERO_ARG_TOOLS
from anonymizer.mcp.instructions import load_server_instructions
from anonymizer.mcp.server import create_server

_BANNED_SCHEMA_FIELDS = frozenset(
    {
        "modality_hint",
        "frame_index",
        "site_id",
        "uid_root",
        "image_format",
        "require_pixel_phi_scanned",
        "size",
        "removal_mode",
    }
)


def test_instructions_asset_is_positive_api_howto() -> None:
    load_server_instructions.cache_clear()
    text = load_server_instructions()
    assert "arguments" in text
    assert "END_TOOL_RESULT" in text  # ban inventing client result markers
    assert "TOOL_RESULT" in text
    assert "create_project" in text
    assert "import_directory" in text
    assert "list_inventory" in text
    assert "list_projects" in text
    assert "harmonize_studies" in text
    assert "export_series_preview" in text
    assert "configure_remote" in text
    assert "pacs_find" in text
    assert "pacs_move" in text
    assert "patient_index" in text
    assert '"series":"all"' in text.replace(" ", "") or '"series": "all"' in text
    assert "TSV" in text
    assert "patient_name" in text  # negative: do not invent
    assert "Never invent filesystem paths" in text or "never invent filesystem paths" in text.lower()
    assert "/absolute/path" not in text  # placeholders that models copy as real paths
    assert "TOOL_REQUEST" not in text  # do not teach client-specific request wrappers
    assert "read_user_manual" not in text
    assert "01-start-here" not in text
    assert "tool_code" not in text
    assert "resolve_series" not in text


def test_instructions_lists_every_advertised_tool() -> None:
    load_server_instructions.cache_clear()
    text = load_server_instructions()
    for name in MCP_TOOL_NAMES:
        assert f"`{name}`" in text or name in text, f"instructions missing {name}"
    # Backtick tool names in instructions should be a subset of advertised + none extras
    mentioned = set(re.findall(r"`([a-z][a-z0-9_]*)`", text))
    tool_like = {n for n in mentioned if n in set(MCP_TOOL_NAMES) or n == "resolve_series"}
    assert "resolve_series" not in tool_like
    assert set(MCP_TOOL_NAMES) <= mentioned | set(MCP_TOOL_NAMES)
    for name in MCP_TOOL_NAMES:
        assert name in mentioned


def test_tool_input_models_match_advertised_names() -> None:
    assert set(MCP_TOOL_NAMES) == set(TOOL_INPUT_MODELS)


def test_wire_text_inventory_is_plain_tsv_not_json_array() -> None:
    from anonymizer.mcp.api import parse_wire_text, wire_text

    payload = {
        "ok": True,
        "count": 1,
        "series": [
            {
                "patient_index": 1,
                "study_index": 1,
                "series_index": 1,
                "anon_patient_id": "ANON-1",
                "modality": "CR",
                "study_description": "XR Chest",
                "study_harmonized": False,
                "series_description": "PA",
                "series_harmonized": False,
                "pixel_phi_scanned": True,
            }
        ],
        "table": (
            "patient_index\tstudy_index\tseries_index\tanon_patient_id\tmodality\t"
            "study_description\tstudy_harmonized\tseries_description\tseries_harmonized\t"
            "pixel_phi_scanned\n"
            "1\t1\t1\tANON-1\tCR\tXR Chest\tN\tPA\tN\tY"
        ),
        "project": {"project_name": "Demo", "storage_dir": "/secret"},
    }
    text = wire_text(payload)
    assert text.startswith("count=1\n")
    assert "patient_index\t" in text
    assert '"ok"' not in text
    assert "inventory" not in text
    assert "storage_dir" not in text
    assert "series_path" not in text
    parsed = parse_wire_text(text)
    assert parsed["ok"] is True
    assert parsed["count"] == 1
    assert parsed["series"][0]["anon_patient_id"] == "ANON-1"
    assert parsed["series"][0]["pixel_phi_scanned"] is True


def test_wire_text_error_and_compact_json() -> None:
    from anonymizer.mcp.api import wire_text

    assert wire_text({"ok": False, "error": "no project"}) == "error: no project"
    compact = wire_text({"ok": True, "project": {"project_name": "X", "storage_dir": "/nope"}})
    assert compact.startswith("{")
    assert "\n" not in compact
    assert "storage_dir" not in compact
    assert "project_name" in compact


def test_wire_text_preview_omits_base64() -> None:
    from anonymizer.mcp.api import wire_text

    text = wire_text(
        {
            "ok": True,
            "caption": "P — CXR",
            "mime_type": "image/png",
            "preview_base64": "AAAA",
            "modality": "CR",
        }
    )
    assert "preview_base64" not in text
    assert '"image":"attached"' in text
    assert "CXR" in text


def test_create_server_uses_asset_instructions() -> None:
    load_server_instructions.cache_clear()
    server = create_server()
    assert server.instructions == load_server_instructions()


def test_create_server_has_no_help_resources_or_prompts() -> None:
    server = create_server()

    async def _drive() -> None:
        tools = {t.name for t in await server.list_tools()}
        assert "read_user_manual" not in tools
        assert "create_project" in tools
        assert "configure_remote" in tools
        assert "pacs_find" in tools
        assert "pacs_move" in tools
        assert "resolve_series" not in tools
        assert tools == set(MCP_TOOL_NAMES)

        resources = await server.list_resources()
        assert not any("help" in str(r.uri) for r in resources)

        prompts = await server.list_prompts()
        assert len(prompts) == 0

    asyncio.run(_drive())


def test_tool_input_schema_includes_field_descriptions() -> None:
    server = create_server()

    def _schema(tool: object) -> dict:
        schema = getattr(tool, "parameters", None) or getattr(tool, "input_schema", None)
        assert isinstance(schema, dict), tool
        return schema

    async def _drive() -> None:
        tools = {t.name: t for t in await server.list_tools()}
        create = tools["create_project"]
        props = _schema(create)["properties"]
        assert "Project display name" in props["project_name"]["description"]
        assert "project_name" in _schema(create).get("required", [])
        assert "site_id" not in props
        assert "uid_root" not in props

        remove = tools["remove_pixel_phi"]
        rprops = _schema(remove)["properties"]
        assert "all" in rprops["series"]["description"]
        assert "patient_index" in rprops["patient"]["description"]
        assert "Create a new empty anonymizer project" in (create.description or "")
        assert create.annotations is not None
        assert create.annotations.title == "Create project"

        for name, tool in tools.items():
            schema = _schema(tool)
            assert schema.get("additionalProperties") is False, name
            assert "$ref" not in json.dumps(schema), f"{name} still has $ref"
            for banned in _BANNED_SCHEMA_FIELDS:
                assert banned not in schema.get("properties", {}), f"{name} has {banned}"
            if name in ZERO_ARG_TOOLS:
                assert schema.get("properties") == {} or not schema.get("properties"), name

        pacs = _schema(tools["pacs_find"])["properties"]
        assert "modality" in pacs
        assert "patient_id" in pacs

        role = _schema(tools["configure_remote"])["properties"]["role"]
        assert "enum" in role
        assert "QUERY" in role["enum"]

        move_items = _schema(tools["pacs_move"])["properties"]["studies"]["items"]
        assert "study_instance_uid" in move_items.get("properties", {})

    asyncio.run(_drive())
