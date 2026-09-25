"""MCP tool handlers. Typed signatures → MCP ``inputSchema``; docstrings → tool descriptions.

``MCP_TOOL_NAMES`` (top of this file) is the set advertised on ``tools/list``.
It matches ``assets/instructions.md``. Other callables here are for tests / later phases.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from pydantic import Field

from anonymizer.controller.ai.remove_pixel_phi import PixelPhiRemovalMode
from anonymizer.mcp import ops
from anonymizer.mcp.ops import (
    HeadlessOpsError,
    PacsMoveLevel,
    PreviewImageFormat,
    RemoteScpRole,
)
from anonymizer.mcp.session import SESSION, ProjectSessionError
from anonymizer.mcp.snapshots import (
    public_inventory_payload,
    public_project_info,
    strip_path_fields,
)

# Advertised on tools/list — keep in sync with assets/instructions.md
MCP_TOOL_NAMES: Final[tuple[str, ...]] = (
    "list_projects",
    "create_project",
    "project_open",
    "project_info",
    "import_directory",
    "import_file",
    "list_inventory",
    "resolve_series",
    "remove_pixel_phi",
    "harmonize_studies",
    "export_series_preview",
)

PatientSelector = Annotated[
    str,
    Field(
        description='From list_inventory: "all" | "<patient_index>" | "<anon_patient_id>" (e.g. "1").',
    ),
]
StudySelector = Annotated[
    str,
    Field(description='From list_inventory: "all" | "<study_index>" (e.g. "1").'),
]
SeriesSelector = Annotated[
    str,
    Field(
        description=(
            'From list_inventory: "all" | "<series_index>" | modality | description substring '
            '(e.g. "1", "cxr").'
        ),
    ),
]
ModalityHint = Annotated[
    str,
    Field(description='When series is empty, treat this as the series selector (e.g. "cxr", "CT").'),
]
ModalitiesArg = Annotated[
    list[str] | str | None,
    Field(
        description=(
            'Allowed ingest modalities. Examples: ["defaults","US"], "defaults and ultrasound", '
            '"CT, MR, US". Omit for project defaults (CR, DX, CT, MR).'
        ),
    ),
]


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **strip_path_fields(payload)}


def _err(exc: BaseException, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), **extra}


def _controller():
    return SESSION.controller


def _with_public_project(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if "project" in out:
        try:
            out["project"] = public_project_info(_controller())
        except Exception:
            proj = out.get("project")
            if isinstance(proj, dict):
                out["project"] = strip_path_fields(proj)
    return out


def list_projects() -> dict[str, Any]:
    """List project names under the default Anonymizer store."""
    return _ok(ops.list_projects())


def create_project(
    project_name: Annotated[str, Field(description="Project display name (required).")],
    storage_dir: Annotated[
        str | None,
        Field(
            description=(
                "Existing absolute directory for the project store. "
                "Omit to use ~/Documents/RSNA Anonymizer/<project_name>."
            ),
        ),
    ] = None,
    site_id: Annotated[
        str | None,
        Field(description="Site identifier. Omit to use ProjectModel default."),
    ] = None,
    uid_root: Annotated[
        str | None,
        Field(description="DICOM UID root. Omit to use ProjectModel default."),
    ] = None,
    overwrite: Annotated[
        bool,
        Field(description="Replace an existing project at the same location."),
    ] = False,
    modalities: ModalitiesArg = None,
) -> dict[str, Any]:
    """Create a new empty project and leave it open. Example: {"project_name": "MCP_MVP"}."""
    name = (project_name or "").strip()
    if SESSION.is_open and name and not overwrite:
        try:
            current = public_project_info(_controller())
            if (current.get("project_name") or "").strip() == name:
                return _ok({"project": current, "already_open": True})
        except Exception:
            pass
    try:
        return _ok(
            _with_public_project(
                ops.create_project(
                    SESSION,
                    project_name,
                    storage_dir=storage_dir,
                    site_id=site_id,
                    uid_root=uid_root,
                    overwrite=overwrite,
                    modalities=modalities,
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def project_open(
    project_name: Annotated[
        str,
        Field(description="Project name under the default store when storage_dir is omitted."),
    ] = "",
    storage_dir: Annotated[
        str | None,
        Field(description="Absolute project directory (or folder containing ProjectModel.json)."),
    ] = None,
    modalities: ModalitiesArg = None,
) -> dict[str, Any]:
    """Open an existing project. Example: {"project_name": "MCP_MVP"}."""
    try:
        return _ok(
            _with_public_project(
                ops.project_open(
                    SESSION,
                    project_name=project_name,
                    storage_dir=storage_dir,
                    modalities=modalities,
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def project_info() -> dict[str, Any]:
    """Return open-project metadata (name, modalities, totals). Use list_inventory for series."""
    try:
        return _ok({"project": public_project_info(_controller())})
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def list_inventory() -> dict[str, Any]:
    """Return inventory rows and TSV ``table`` including study_description and series_description."""
    try:
        raw = ops.list_inventory(_controller())
        public = public_inventory_payload(raw)
        public["project"] = public_project_info(_controller())
        # Guarantee description fields survive the public allowlist.
        for row in public.get("series") or []:
            if isinstance(row, dict):
                row.setdefault("study_description", "")
                row.setdefault("series_description", "")
        return _ok(public)
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def import_directory(
    directory: Annotated[
        str,
        Field(description="Absolute path to a DICOM study folder on this machine."),
    ],
) -> dict[str, Any]:
    """Import a host DICOM folder. Example: {"directory": "/absolute/path/to/folder"}."""
    try:
        return _ok(_with_public_project(ops.import_directory(_controller(), directory)))
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def import_file(
    file_path: Annotated[
        str,
        Field(description="Absolute path to one DICOM file on this machine."),
    ],
) -> dict[str, Any]:
    """Import one host DICOM file. Example: {"file_path": "/absolute/path/to/file.dcm"}."""
    try:
        return _ok(_with_public_project(ops.import_file(_controller(), file_path)))
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def configure_remote(
    ip: Annotated[str, Field(description="Remote host IP or hostname.")],
    port: Annotated[int, Field(description="Remote DICOM port.")],
    aet: Annotated[str, Field(description="Remote AE title.")],
    role: Annotated[
        RemoteScpRole,
        Field(description="Remote SCP role (QUERY or EXPORT)."),
    ] = RemoteScpRole.QUERY,
) -> dict[str, Any]:
    try:
        return _ok(ops.configure_remote(_controller(), ip=ip, port=port, aet=aet, role=role))
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def pacs_find(
    patient_name: Annotated[str, Field(description="PatientName query value.")] = "",
    patient_id: Annotated[str, Field(description="PatientID query value.")] = "",
    accession: Annotated[str, Field(description="AccessionNumber query value.")] = "",
    study_date: Annotated[str, Field(description="StudyDate query value (DICOM DA).")] = "",
    modality: Annotated[str, Field(description="Modality query value.")] = "",
) -> dict[str, Any]:
    try:
        return _ok(
            ops.pacs_find(
                _controller(),
                patient_name=patient_name,
                patient_id=patient_id,
                accession=accession,
                study_date=study_date,
                modality=modality,
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def pacs_move(
    studies: Annotated[
        list[dict[str, str]],
        Field(
            description=(
                'Studies from pacs_find: list of {"study_instance_uid": "...", "patient_id": "..."}.'
            ),
        ),
    ],
    level: Annotated[
        PacsMoveLevel,
        Field(description="C-MOVE level (STUDY, SERIES, or INSTANCE)."),
    ] = PacsMoveLevel.SERIES,
) -> dict[str, Any]:
    try:
        return _ok(ops.pacs_move(_controller(), SESSION, studies=studies, level=level))
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def remove_pixel_phi(
    patient: PatientSelector = "",
    study: StudySelector = "",
    series: SeriesSelector = "",
    removal_mode: Annotated[
        PixelPhiRemovalMode,
        Field(description="How to remove burnt-in text (blackout or inpaint)."),
    ] = PixelPhiRemovalMode.BLACKOUT,
    use_modality_whitelist: Annotated[
        bool,
        Field(description="Keep modality whitelist OCR terms (default true)."),
    ] = True,
    modality_hint: ModalityHint = "",
) -> dict[str, Any]:
    """Strip burnt-in text. All series: {"series": "all"}. One: {"patient": "1", "series": "1"}."""
    try:
        return _ok(
            _with_public_project(
                ops.remove_pixel_phi(
                    _controller(),
                    SESSION,
                    removal_mode=removal_mode,
                    use_modality_whitelist=use_modality_whitelist,
                    modality_hint=modality_hint,
                    patient=patient,
                    study=study,
                    series=series,
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def export_series_preview(
    patient: PatientSelector = "",
    study: StudySelector = "",
    series: SeriesSelector = "",
    frame_index: Annotated[
        int,
        Field(description="Zero-based frame index within the series (default 0)."),
    ] = 0,
    image_format: Annotated[
        PreviewImageFormat,
        Field(description="Output image format."),
    ] = PreviewImageFormat.PNG,
    require_pixel_phi_scanned: Annotated[
        bool,
        Field(description="Require pixel_phi_scanned on the series before export."),
    ] = False,
    modality_hint: ModalityHint = "",
    size: Annotated[
        int,
        Field(description="Square preview edge length in pixels (default 448)."),
    ] = 448,
) -> dict[str, Any]:
    """Export one series frame as preview_base64 + mime_type. Example: {"patient": "1", "series": "1"}."""
    try:
        return _ok(
            _with_public_project(
                ops.export_series_preview(
                    _controller(),
                    frame_index=frame_index,
                    image_format=image_format,
                    require_pixel_phi_scanned=require_pixel_phi_scanned,
                    modality_hint=modality_hint,
                    size=size,
                    patient=patient,
                    study=study,
                    series=series,
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def resolve_series(
    patient: PatientSelector = "",
    study: StudySelector = "",
    series: SeriesSelector = "",
    modality_hint: ModalityHint = "",
) -> dict[str, Any]:
    """Resolve one series. Example: {"patient": "1", "series": "1"}."""
    try:
        return _ok(
            strip_path_fields(
                ops.resolve_series(
                    _controller(),
                    patient=patient,
                    study=study,
                    series=series,
                    modality_hint=modality_hint or None,
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def harmonize_studies(
    patient: PatientSelector = "",
    study: StudySelector = "",
) -> dict[str, Any]:
    """Harmonize study/series descriptions. All: {}. One: {"patient": "1", "study": "1"}."""
    try:
        result = ops.harmonize_studies(_controller(), patient=patient, study=study)
        ok = not result.get("cancelled") and result.get("failed", 0) == 0
        return {"ok": ok, **strip_path_fields(_with_public_project(result))}
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def register_mcp_tools(server: Any) -> None:
    """Register ``MCP_TOOL_NAMES``; tool description = first line of the function docstring."""
    for name in MCP_TOOL_NAMES:
        fn = globals()[name]
        description = (fn.__doc__ or name).strip().split("\n", 1)[0].strip()
        server.add_tool(fn, name=name, description=description)
