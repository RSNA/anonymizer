"""MCP InitializeResult.instructions + typed tool JSON Schema."""

from __future__ import annotations

import asyncio

from anonymizer.mcp.instructions import load_server_instructions
from anonymizer.mcp.server import create_server


def test_instructions_asset_is_positive_api_howto() -> None:
    load_server_instructions.cache_clear()
    text = load_server_instructions()
    assert "create_project" in text
    assert "import_directory" in text
    assert "list_inventory" in text
    assert "harmonize_studies" in text
    assert '"series": "all"' in text
    assert "patient_index" in text
    assert "read_user_manual" not in text
    assert "01-start-here" not in text


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

        resources = await server.list_resources()
        assert not any("help" in str(r.uri) for r in resources)

        prompts = await server.list_prompts()
        assert len(prompts) == 0

    asyncio.run(_drive())


def test_tool_input_schema_includes_field_descriptions() -> None:
    server = create_server()

    async def _drive() -> None:
        tools = {t.name: t for t in await server.list_tools()}
        create = tools["create_project"]
        props = create.input_schema["properties"]
        assert "Project display name" in props["project_name"]["description"]
        assert "project_name" in create.input_schema.get("required", [])

        remove = tools["remove_pixel_phi"]
        rprops = remove.input_schema["properties"]
        assert "all" in rprops["series"]["description"]
        assert "patient_index" in rprops["patient"]["description"]
        assert "Create a new empty project" in (create.description or "")

    asyncio.run(_drive())
