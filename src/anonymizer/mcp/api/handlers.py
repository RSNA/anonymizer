"""MCP tool handlers — behavior only; schemas/descriptions live in ``catalog`` / ``schemas``.

Signatures stay flat (one MCP argument per parameter). ``register_tools`` overlays
Pydantic ``inputSchema`` from the catalog so Field text is not duplicated here.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from anonymizer.mcp import ops
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
from anonymizer.mcp.ops import (
    HeadlessOpsError,
    PacsMoveLevel,
    RemoteScpRole,
)
from anonymizer.mcp.session import SESSION, ProjectSessionError
from anonymizer.mcp.snapshots import (
    public_inventory_payload,
    public_project_info,
    strip_path_fields,
)


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **strip_path_fields(payload)}


def _err(exc: BaseException, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), **extra}


def _parse(model_cls: type, data: dict[str, Any]):
    """Validate tool kwargs; return (model, None) or (None, error_dict)."""
    try:
        return model_cls.model_validate(data), None
    except ValidationError as exc:
        msgs = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            msgs.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
        return None, _err(ValueError("; ".join(msgs) or str(exc)))


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
    _parse(EmptyArgs, {})
    return _ok(ops.list_projects())


def create_project(
    project_name: str,
    storage_dir: str | None = None,
    overwrite: bool = False,
    modalities: list[str] | str | None = None,
) -> dict[str, Any]:
    args, err = _parse(
        CreateProjectArgs,
        {
            "project_name": project_name,
            "storage_dir": storage_dir,
            "overwrite": overwrite,
            "modalities": modalities,
        },
    )
    if err is not None:
        return err
    name = args.project_name.strip()
    if SESSION.is_open and name and not args.overwrite:
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
                    args.project_name,
                    storage_dir=args.storage_dir,
                    overwrite=args.overwrite,
                    modalities=args.modalities,
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def project_open(
    project_name: str | None = None,
    storage_dir: str | None = None,
    modalities: list[str] | str | None = None,
) -> dict[str, Any]:
    args, err = _parse(
        ProjectOpenArgs,
        {
            "project_name": project_name,
            "storage_dir": storage_dir,
            "modalities": modalities,
        },
    )
    if err is not None:
        return err
    try:
        return _ok(
            _with_public_project(
                ops.project_open(
                    SESSION,
                    project_name=args.project_name or "",
                    storage_dir=args.storage_dir,
                    modalities=args.modalities,
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def project_info() -> dict[str, Any]:
    _parse(EmptyArgs, {})
    try:
        return _ok({"project": public_project_info(_controller())})
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def list_inventory() -> dict[str, Any]:
    _parse(EmptyArgs, {})
    try:
        raw = ops.list_inventory(_controller())
        public = public_inventory_payload(raw)
        public["project"] = public_project_info(_controller())
        for row in public.get("series") or []:
            if isinstance(row, dict):
                row.setdefault("study_description", "")
                row.setdefault("series_description", "")
        return _ok(public)
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def import_directory(directory: str) -> dict[str, Any]:
    args, err = _parse(ImportDirectoryArgs, {"directory": directory})
    if err is not None:
        return err
    try:
        return _ok(_with_public_project(ops.import_directory(_controller(), args.directory)))
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def import_file(file_path: str) -> dict[str, Any]:
    args, err = _parse(ImportFileArgs, {"file_path": file_path})
    if err is not None:
        return err
    try:
        return _ok(_with_public_project(ops.import_file(_controller(), args.file_path)))
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def configure_remote(
    ip: str,
    port: int,
    aet: str,
    role: RemoteScpRole = RemoteScpRole.QUERY,
) -> dict[str, Any]:
    args, err = _parse(
        ConfigureRemoteArgs, {"ip": ip, "port": port, "aet": aet, "role": role}
    )
    if err is not None:
        return err
    try:
        return _ok(
            ops.configure_remote(
                _controller(),
                ip=args.ip,
                port=args.port,
                aet=args.aet,
                role=args.role,
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def pacs_find(
    patient_name: str | None = None,
    patient_id: str | None = None,
    accession: str | None = None,
    study_date: str | None = None,
    modality: str | None = None,
) -> dict[str, Any]:
    args, err = _parse(
        PacsFindArgs,
        {
            "patient_name": patient_name,
            "patient_id": patient_id,
            "accession": accession,
            "study_date": study_date,
            "modality": modality,
        },
    )
    if err is not None:
        return err
    try:
        return _ok(
            ops.pacs_find(
                _controller(),
                patient_name=args.patient_name or "",
                patient_id=args.patient_id or "",
                accession=args.accession or "",
                study_date=args.study_date or "",
                modality=args.modality or "",
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def pacs_move(
    studies: list[dict[str, str]],
    level: PacsMoveLevel = PacsMoveLevel.SERIES,
) -> dict[str, Any]:
    args, err = _parse(PacsMoveArgs, {"studies": studies, "level": level})
    if err is not None:
        return err
    try:
        study_dicts = [s.model_dump() for s in args.studies]
        return _ok(
            ops.pacs_move(_controller(), SESSION, studies=study_dicts, level=args.level)
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def remove_pixel_phi(
    patient: str | None = None,
    study: str | None = None,
    series: str | None = None,
) -> dict[str, Any]:
    args, err = _parse(
        SeriesSelectorsArgs, {"patient": patient, "study": study, "series": series}
    )
    if err is not None:
        return err
    try:
        return _ok(
            _with_public_project(
                ops.remove_pixel_phi(
                    _controller(),
                    SESSION,
                    patient=args.patient or "",
                    study=args.study or "",
                    series=args.series or "",
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def export_series_preview(
    patient: str | None = None,
    study: str | None = None,
    series: str | None = None,
) -> dict[str, Any]:
    args, err = _parse(
        ExportPreviewArgs, {"patient": patient, "study": study, "series": series}
    )
    if err is not None:
        return err
    try:
        return _ok(
            _with_public_project(
                ops.export_series_preview(
                    _controller(),
                    patient=args.patient or "",
                    study=args.study or "",
                    series=args.series or "",
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def resolve_series(
    patient: str | None = None,
    study: str | None = None,
    series: str | None = None,
) -> dict[str, Any]:
    """Internal/test helper — not in TOOL_CATALOG / tools/list."""
    try:
        return _ok(
            strip_path_fields(
                ops.resolve_series(
                    _controller(),
                    patient=patient or "",
                    study=study or "",
                    series=series or "",
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def harmonize_studies(
    patient: str | None = None,
    study: str | None = None,
) -> dict[str, Any]:
    args, err = _parse(HarmonizeStudiesArgs, {"patient": patient, "study": study})
    if err is not None:
        return err
    try:
        result = ops.harmonize_studies(
            _controller(),
            patient=args.patient or "",
            study=args.study or "",
        )
        ok = not result.get("cancelled") and result.get("failed", 0) == 0
        return {"ok": ok, **strip_path_fields(_with_public_project(result))}
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)
