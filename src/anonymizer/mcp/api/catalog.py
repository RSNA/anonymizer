"""Authoritative MCP tool catalog: descriptions, annotations, Pydantic args.

tools/list and initialize instructions are derived from this registry.
Handlers implement behavior only — they do not own schema text.
"""

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
    JobStatusArgs,
    PacsFindArgs,
    PacsMoveArgs,
    ProjectOpenArgs,
    SeriesSelectorsArgs,
    UpdateProjectSettingsArgs,
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
        name="anonymizer_usage",
        title="How to use the Anonymizer",
        description=(
            "Return the canonical plain-language instructions and example requests "
            "for using the Anonymizer. Call with arguments {} FIRST whenever the user "
            "asks how to use the Anonymizer, how to create or configure a project, or "
            "what they should say — instead of deriving an explanation from the other "
            "tool definitions. The result is a complete finished answer: reproduce "
            "it exactly, word for word, as your entire reply. Do not summarize, "
            "reformat, add facts, examples, headings, or a closing invitation. "
            "Read-only; creates and changes nothing."
        ),
        args_model=EmptyArgs,
        read_only_hint=True,
        idempotent_hint=True,
    ),
    ToolSpec(
        name="job_status",
        title="Check a background job",
        description=(
            "Poll a background job started by a long-running tool. Call with "
            "{job_id} copied from a result with status=pending, and keep polling "
            "until status is completed or failed. When completed, present the "
            "nested result as the tool's answer; when failed, report the error. "
            "Read-only."
        ),
        args_model=JobStatusArgs,
        read_only_hint=True,
        idempotent_hint=True,
    ),
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
        name="project_settings_defaults",
        title="Project settings defaults",
        description=(
            "Return factory defaults, ranges, and clinician help for project settings. "
            "Call with arguments {} when the user asks how to configure a project, "
            "what settings can be changed, or what the defaults/ranges are. "
            "Read-only. Do not call this before create_project: create_project with "
            "confirm=false already returns the requested settings combined with defaults "
            "for confirmation."
        ),
        args_model=EmptyArgs,
        read_only_hint=True,
        idempotent_hint=True,
    ),
    ToolSpec(
        name="create_project",
        title="Create project",
        description=(
            "Prepare or confirm a new anonymizer project. First call: pass project_name "
            "and only settings the user supplied, with confirm=false. The server combines "
            "them with ProjectModel defaults and returns status=confirmation_required; "
            "nothing is created. Present that configuration and stop. If the user changes "
            "a setting, call again with confirm=false. Only after the user explicitly "
            "confirms in a later message, call again with project_name, confirm=true, and "
            "the returned revision. Never set confirm=true on the first call. After "
            "status=created the project is open — do not call project_open."
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
            "Does not import DICOM — for a file path use import_file with file_path "
            "on an already-open project. "
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
            "Return settings summary for the currently open project: language, modalities, "
            "transfer_syntaxes, network_timeouts, local_scp/local_scu, and remotes. "
            "Not the series inventory — for the series TSV table call list_inventory. "
            "Call with arguments {}. Requires an open project. Read-only. "
            "Use before update_project_settings when editing an existing project."
        ),
        args_model=EmptyArgs,
        read_only_hint=True,
        idempotent_hint=True,
    ),
    ToolSpec(
        name="update_project_settings",
        title="Update project settings",
        description=(
            "Change mutable settings on the open project: modalities, "
            "transfer_syntaxes, local scp, network_timeouts, confidentiality_options. "
            "language_code is chosen once at project creation and, like project_name, "
            "storage_dir, site_id, and uid_root, is fixed after create — refuse those. "
            "Changing confidentiality_options recompiles the anonymizer script — confirm first. "
            "Call only with values the clinician supplied."
        ),
        args_model=UpdateProjectSettingsArgs,
        idempotent_hint=True,
    ),
    ToolSpec(
        name="import_directory",
        title="Import DICOM directory",
        description=(
            "Import DICOM files from a host directory into the open project. "
            "Requires an already-open project. "
            "Call only with a real absolute directory path from the clinician. "
            "Never invent paths. If no path was given, ask — do not call this tool. "
            "Starts a background job and returns status=pending with a job_id; "
            "poll job_status until completed before reporting counts."
        ),
        args_model=ImportDirectoryArgs,
        open_world_hint=True,
    ),
    ToolSpec(
        name="import_file",
        title="Import DICOM file",
        description=(
            "Import one DICOM file into the already-open project. "
            "Argument is file_path (absolute path) — not project_open, not path. "
            "Requires an already-open project. "
            "Never invent paths. If none given, ask — do not call this tool."
        ),
        args_model=ImportFileArgs,
        open_world_hint=True,
    ),
    ToolSpec(
        name="configure_remote",
        title="Configure PACS remote",
        description=(
            "Save a PACS QUERY or EXPORT remote on the open project. "
            "Exact args — DIMSE: ip, port, aet, role=QUERY, dicomweb=false. "
            "DICOMweb: ip, port, aet, role=QUERY, dicomweb=true, http_port, http_path "
            "(optional use_https/username/password). "
            "Never invent host, hostname, address, protocol, path, aetitle, or query_type "
            "(use ip / aet / dicomweb / http_path / role). "
            "If the user has not said DIMSE vs DICOMweb and did not give HTTP details, "
            "ask first — do not call yet. "
            "Configure QUERY before pacs_find/pacs_move."
        ),
        args_model=ConfigureRemoteArgs,
        open_world_hint=True,
    ),
    ToolSpec(
        name="pacs_find",
        title="PACS find (C-FIND or QIDO-RS)",
        description=(
            "Query the open project's configured QUERY remote for studies "
            "(DIMSE C-FIND or DICOMweb QIDO-RS). If the user supplies or changes PACS "
            "details, call configure_remote role=QUERY first. "
            "Omit unused query keys. Never invent PatientIDs or UIDs."
        ),
        args_model=PacsFindArgs,
        read_only_hint=True,
        open_world_hint=True,
    ),
    ToolSpec(
        name="pacs_move",
        title="PACS import (C-MOVE/C-GET or WADO-RS)",
        description=(
            "Import studies from PACS into the open project (DIMSE retrieve or DICOMweb WADO-RS). "
            "Uses the open project's configured QUERY remote. "
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
            "List series in the open project as a plain TSV table (patient/study/series rows). "
            "Use for 'what is in the project?' / inventory / series list — not project_info "
            "(settings summary only). Call with arguments {}. Read-only. "
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
            "Example: {\"series\":\"all\"} or {\"patient\":\"1\",\"series\":\"1\"}. "
            "Starts a background job and returns status=pending with a job_id; "
            "poll job_status until completed before reporting counts."
        ),
        args_model=SeriesSelectorsArgs,
        destructive_hint=True,
    ),
    ToolSpec(
        name="harmonize_studies",
        title="Harmonize descriptions",
        description=(
            "Harmonize study/series descriptions in the open project. "
            "Pass {} for all, or patient/study selectors from list_inventory. "
            "Starts a background job and returns status=pending with a job_id; "
            "poll job_status until completed before reporting counts."
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
