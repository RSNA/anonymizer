"""MCP tool API surface.

catalog
    Authoritative tool list: names, titles, descriptions, MCP annotations, Pydantic models.
schemas
    Pydantic args models + validators (path safety, enums).
schema_json
    model_json_schema → flat MCP inputSchema.
handlers
    Implementations (dict returns for unit tests).
wire
    Dict → plain-text MCP ToolResult (output_schema=None for LLM free text).
"""

from typing import Any as Any

from fastmcp.tools import Tool as Tool

from anonymizer.mcp.api import handlers as handlers
from anonymizer.mcp.api.catalog import MCP_TOOL_NAMES as MCP_TOOL_NAMES
from anonymizer.mcp.api.catalog import TOOL_CATALOG as TOOL_CATALOG
from anonymizer.mcp.api.catalog import TOOL_INPUT_MODELS as TOOL_INPUT_MODELS
from anonymizer.mcp.api.catalog import ZERO_ARG_TOOLS as ZERO_ARG_TOOLS
from anonymizer.mcp.api.handlers import (
    anonymizer_usage as anonymizer_usage,
)
from anonymizer.mcp.api.handlers import (
    configure_remote as configure_remote,
)
from anonymizer.mcp.api.handlers import (
    create_project as create_project,
)
from anonymizer.mcp.api.handlers import (
    export_series_preview as export_series_preview,
)
from anonymizer.mcp.api.handlers import (
    harmonize_studies as harmonize_studies,
)
from anonymizer.mcp.api.handlers import (
    import_directory as import_directory,
)
from anonymizer.mcp.api.handlers import (
    import_file as import_file,
)
from anonymizer.mcp.api.handlers import (
    job_status as job_status,
)
from anonymizer.mcp.api.handlers import (
    list_inventory as list_inventory,
)
from anonymizer.mcp.api.handlers import (
    list_projects as list_projects,
)
from anonymizer.mcp.api.handlers import (
    pacs_find as pacs_find,
)
from anonymizer.mcp.api.handlers import (
    pacs_move as pacs_move,
)
from anonymizer.mcp.api.handlers import (
    project_info as project_info,
)
from anonymizer.mcp.api.handlers import (
    project_open as project_open,
)
from anonymizer.mcp.api.handlers import (
    project_settings_defaults as project_settings_defaults,
)
from anonymizer.mcp.api.handlers import (
    remove_pixel_phi as remove_pixel_phi,
)
from anonymizer.mcp.api.handlers import (
    resolve_series as resolve_series,
)
from anonymizer.mcp.api.handlers import (
    update_project_settings as update_project_settings,
)
from anonymizer.mcp.api.schema_json import mcp_input_schema as mcp_input_schema
from anonymizer.mcp.api.wire import as_plain_tool as as_plain_tool
from anonymizer.mcp.api.wire import parse_wire_text as parse_wire_text
from anonymizer.mcp.api.wire import wire_text as wire_text


def register_tools(server: Any) -> None:
    """Register catalog tools on FastMCP with Pydantic inputSchema + annotations."""

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


