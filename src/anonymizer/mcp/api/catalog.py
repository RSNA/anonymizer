"""Authoritative MCP tool catalog: descriptions, annotations, Pydantic args.

``tools/list`` and initialize instructions are derived from this registry.
Handlers implement behavior only — they do not own schema text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from mcp.types import ToolAnnotations
from pydantic import BaseModel

from anonymizer.mcp.api.schema_json import schema_fields_markdown
from anonymizer.mcp.api.schemas import (
    ConfigureRemoteArgs,
    CreateProjectArgs,
    EmptyArgs,
    ExportPreviewArgs,
    HarmonizeStudiesArgs,
    ImportDirectoryArgs,
    ImportFileArgs,
    PacsFindArgs,
    PacsMoveArgs,
    ProjectOpenArgs,
    SeriesSelectorsArgs,
)


@dataclass(frozen=True)
class ToolSpec:
    """One advertised MCP tool."""

    name: str
    title: str
    description: str
    args_model: type[BaseModel]
    read_only_hint: bool = False
    destructive_hint: bool = False
    idempotent_hint: bool = False
    open_world_hint: bool = False

    def annotations(self) -> ToolAnnotations:
        return ToolAnnotations(
            title=self.title,
            readOnlyHint=self.read_only_hint,
            destructiveHint=self.destructive_hint,
            idempotentHint=self.idempotent_hint,
            openWorldHint=self.open_world_hint,
        )


# Order = tools/list order. Keep in sync with assets/instructions behavior rules.
TOOL_CATALOG: Final[tuple[ToolSpec, ...]] = (
    ToolSpec(
        name="list_projects",
        title="List projects",
        description=(
            "List anonymizer projects in the default store. "
            "Call with arguments {}. Read-only. "
            "Use when the user asks what projects exist."
        ),
        args_model=EmptyArgs,
        read_only_hint=True,
        idempotent_hint=True,
    ),
    ToolSpec(
        name="create_project",
        title="Create project",
        description=(
            "Create a new empty anonymizer project and leave it open. "
            "Call only when the user asks to create a project. "
            "Requires project_name from the user. "
            "After success: the project is already open — reply in plain language and STOP. "
            "Do not call project_open, import_directory, import_file, or any other tool next "
            "unless the same user message explicitly asked for that next step too."
        ),
        args_model=CreateProjectArgs,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    ToolSpec(
        name="project_open",
        title="Open project",
        description=(
            "Open an existing anonymizer project by project_name or storage_dir. "
            "Do not call after create_project (create already opens). "
            "Use when the user asks to open/switch to an existing project."
        ),
        args_model=ProjectOpenArgs,
        idempotent_hint=True,
    ),
    ToolSpec(
        name="project_info",
        title="Project info",
        description=(
            "Return metadata for the currently open project. "
            "Call with arguments {}. Requires an open project. Read-only."
        ),
        args_model=EmptyArgs,
        read_only_hint=True,
        idempotent_hint=True,
    ),
    ToolSpec(
        name="import_directory",
        title="Import DICOM directory",
        description=(
            "Import DICOM files from a host directory into the open project. "
            "Call only when the user provided a real absolute directory path in this message "
            "(or a prior message in the same turn). "
            "Never invent paths or use documentation placeholders. "
            "If no absolute path was given, ask the user — do not call this tool."
        ),
        args_model=ImportDirectoryArgs,
        open_world_hint=True,
    ),
    ToolSpec(
        name="import_file",
        title="Import DICOM file",
        description=(
            "Import one DICOM file from an absolute host path into the open project. "
            "Call only when the user provided a real absolute file path. "
            "Never invent paths. If none given, ask — do not call this tool."
        ),
        args_model=ImportFileArgs,
        open_world_hint=True,
    ),
    ToolSpec(
        name="configure_remote",
        title="Configure PACS remote",
        description=(
            "Save a PACS QUERY or EXPORT remote (ip, port, aet) on the open project. "
            "Call only with host/port/AE values the user supplied. Never invent them."
        ),
        args_model=ConfigureRemoteArgs,
        open_world_hint=True,
    ),
    ToolSpec(
        name="pacs_find",
        title="PACS C-FIND",
        description=(
            "Query the configured QUERY remote for studies. "
            "Omit unused query keys. Requires configure_remote first when not already set."
        ),
        args_model=PacsFindArgs,
        read_only_hint=True,
        open_world_hint=True,
    ),
    ToolSpec(
        name="pacs_move",
        title="PACS C-MOVE import",
        description=(
            "C-MOVE studies from PACS into the open project. "
            "studies must come from pacs_find results (study_instance_uid + patient_id). "
            "Do not invent UIDs."
        ),
        args_model=PacsMoveArgs,
        open_world_hint=True,
    ),
    ToolSpec(
        name="list_inventory",
        title="List inventory",
        description=(
            "List series in the open project as a plain TSV table. "
            "Call with arguments {}. Read-only. "
            "Use returned patient_index/study_index/series_index for imaging tools."
        ),
        args_model=EmptyArgs,
        read_only_hint=True,
        idempotent_hint=True,
    ),
    ToolSpec(
        name="remove_pixel_phi",
        title="Remove pixel PHI",
        description=(
            "Strip burnt-in pixel text from series in the open project. "
            "Selectors (patient/study/series) must come from list_inventory. "
            "Example: {\"series\":\"all\"} or {\"patient\":\"1\",\"series\":\"1\"}."
        ),
        args_model=SeriesSelectorsArgs,
        destructive_hint=True,
    ),
    ToolSpec(
        name="harmonize_studies",
        title="Harmonize descriptions",
        description=(
            "Harmonize study/series descriptions in the open project. "
            "Pass {} for all, or patient/study selectors from list_inventory."
        ),
        args_model=HarmonizeStudiesArgs,
        destructive_hint=True,
    ),
    ToolSpec(
        name="export_series_preview",
        title="Export series preview",
        description=(
            "Return a preview of exactly one series (MCP image + short text caption/modality). "
            "If the user already gave patient/series indices, call this directly "
            '(e.g. patient="1", series="1"). Otherwise list_inventory with {} first, then '
            "pass that row's patient_index and series_index. Never patient=\"all\". Read-only."
        ),
        args_model=ExportPreviewArgs,
        read_only_hint=True,
        idempotent_hint=True,
    ),
)

TOOL_INPUT_MODELS: Final[dict[str, type[BaseModel]]] = {
    spec.name: spec.args_model for spec in TOOL_CATALOG
}

ZERO_ARG_TOOLS: Final[frozenset[str]] = frozenset(
    spec.name for spec in TOOL_CATALOG if spec.args_model is EmptyArgs
)

MCP_TOOL_NAMES: Final[tuple[str, ...]] = tuple(spec.name for spec in TOOL_CATALOG)

assert len(MCP_TOOL_NAMES) == len(set(MCP_TOOL_NAMES)), "duplicate tool names in TOOL_CATALOG"


def render_tools_api_markdown() -> str:
    """Authoritative tool API section for initialize instructions."""
    lines = [
        "## Tool API (authoritative — matches tools/list)",
        "",
        "Call each tool with JSON `arguments` matching its fields below. "
        "Unknown keys are rejected. Zero-argument tools use `{}`.",
        "",
    ]
    for spec in TOOL_CATALOG:
        lines.append(f"### `{spec.name}` — {spec.title}")
        lines.append(spec.description)
        lines.append("")
        lines.append("arguments:")
        lines.append(schema_fields_markdown(spec.args_model))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
