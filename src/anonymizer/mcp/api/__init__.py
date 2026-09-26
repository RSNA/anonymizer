"""MCP tool API surface.

``catalog``
    Authoritative tool list: names, titles, descriptions, MCP annotations, Pydantic models.
``schemas``
    Pydantic args models + validators (path safety, enums).
``schema_json``
    ``model_json_schema`` → flat MCP ``inputSchema``.
``handlers``
    Implementations (dict returns for unit tests).
``wire``
    Dict → plain-text MCP ``ToolResult`` (``output_schema=None`` for LLM free text).
"""

from __future__ import annotations

from typing import Any

from anonymizer.mcp.api import handlers
from anonymizer.mcp.api.catalog import (
    MCP_TOOL_NAMES,
    TOOL_CATALOG,
    TOOL_INPUT_MODELS,
    ZERO_ARG_TOOLS,
)
from anonymizer.mcp.api.handlers import (  # noqa: F401 — public API
    configure_remote,
    create_project,
    export_series_preview,
    harmonize_studies,
    import_directory,
    import_file,
    list_inventory,
    list_projects,
    pacs_find,
    pacs_move,
    project_info,
    project_open,
    remove_pixel_phi,
    resolve_series,
)
from anonymizer.mcp.api.schema_json import mcp_input_schema
from anonymizer.mcp.api.wire import as_plain_tool, parse_wire_text, wire_text


def register_tools(server: Any) -> None:
    """Register catalog tools on FastMCP with Pydantic ``inputSchema`` + annotations."""
    from fastmcp.tools import Tool

    for spec in TOOL_CATALOG:
        fn = getattr(handlers, spec.name)
        tool = Tool.from_function(
            as_plain_tool(fn),
            name=spec.name,
            title=spec.title,
            description=spec.description,
            annotations=spec.annotations(),
            output_schema=None,  # plain-text ToolResult for LLM free text
        )
        tool.parameters = mcp_input_schema(spec.args_model)
        server.add_tool(tool)


__all__ = [
    "MCP_TOOL_NAMES",
    "ZERO_ARG_TOOLS",
    "TOOL_INPUT_MODELS",
    "TOOL_CATALOG",
    "wire_text",
    "parse_wire_text",
    "register_tools",
    "list_projects",
    "create_project",
    "project_open",
    "project_info",
    "list_inventory",
    "import_directory",
    "import_file",
    "configure_remote",
    "pacs_find",
    "pacs_move",
    "remove_pixel_phi",
    "harmonize_studies",
    "export_series_preview",
    "resolve_series",
]
