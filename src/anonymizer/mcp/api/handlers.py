"""MCP tool handlers — behavior only; schemas/descriptions live in ``catalog`` / ``schemas``.

Signatures stay flat (one MCP argument per parameter). ``register_tools`` overlays
Pydantic ``inputSchema`` from the catalog so Field text is not duplicated here.
"""

from __future__ import annotations

import asyncio
from typing import Any

import anyio
from fastmcp.server.dependencies import get_context
from pydantic import ValidationError

from anonymizer.mcp import ops
from anonymizer.mcp.api.schemas import (
    CONFIGURE_REMOTE_EXTRA_HINT,
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
from anonymizer.mcp.ops import HeadlessOpsError, PacsMoveLevel, RemoteScpRole
from anonymizer.mcp.session import SESSION, ProjectSessionError
from anonymizer.mcp.snapshots import public_inventory_payload, public_project_info, strip_path_fields


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
        extra_forbidden = False
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            msgs.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
            if err.get("type") == "extra_forbidden":
                extra_forbidden = True
        text = "; ".join(msgs) or str(exc)
        if extra_forbidden and model_cls is ConfigureRemoteArgs:
            text = f"{text}. {CONFIGURE_REMOTE_EXTRA_HINT}"
        return None, _err(ValueError(text))


def _progress_callback() -> ops.ProgressCallback | None:
    """
    Bridge ops progress callbacks to the active MCP request context.

    Long-running batch/AI tools report per-item progress; clients that honor
    MCP progress notifications can extend their request timeout instead of
    cancelling at a fixed limit. Outside an MCP request (unit tests, direct
    handler calls) there is no context and reporting is disabled.

    Returns:
        Sync progress callback, or ``None`` when no MCP context is active.
    """
    try:
        ctx = get_context()
    except Exception:
        return None

    def _report(progress: float, total: float | None, message: str | None = None) -> None:
        try:
            anyio.from_thread.run(ctx.report_progress, progress, total, message)
        except Exception:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(ctx.report_progress(progress, total, message))

    return _report


def _start_job_pending(operation: str, work: Any) -> dict[str, Any]:
    """
    Start a background job and return the standard ``pending`` payload.

    Args:
        operation: Tool name, echoed so the client knows what is running.
        work: Callable taking a progress callback and returning the tool
            result dict; executed on the session's background job thread.

    Returns:
        ``{ok, status: "pending", job_id, operation, next_action}``.
    """
    job_id = SESSION.start_job(operation, work)
    return {
        "ok": True,
        "status": "pending",
        "job_id": job_id,
        "operation": operation,
        "message": (
            f"{operation} started in the background. It has not finished yet."
        ),
        "next_action": (
            f"Call job_status with job_id {job_id!r} until status is completed "
            "or failed, then present that result. Do not start this operation again."
        ),
    }


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


def anonymizer_usage() -> dict[str, Any]:
    _parse(EmptyArgs, {})
    return _ok(ops.anonymizer_usage())


def job_status(job_id: str) -> dict[str, Any]:
    """Poll one background job (see ``SESSION.start_job``)."""
    args, err = _parse(JobStatusArgs, {"job_id": job_id})
    if err is not None:
        return err
    try:
        job = SESSION.job_status(args.job_id)
    except ProjectSessionError as exc:
        return _err(exc)
    base = {
        "ok": True,
        "job_id": job["job_id"],
        "operation": job["operation"],
        "elapsed_seconds": job["elapsed_seconds"],
    }
    if job["status"] == "running":
        return {
            **base,
            "status": "running",
            "progress": job["progress"],
            "next_action": "Wait a few seconds, then call job_status again.",
        }
    if job["status"] == "failed":
        return {
            **base,
            "ok": False,
            "status": "failed",
            "error": str(job["error"] or "job failed without an error message"),
        }
    result = job["result"] or {}
    project = result.get("project")
    if isinstance(project, dict) and "storage_dir" in project:
        # Full project payloads get the same public rewrite as sync tools;
        # minimal import summaries pass through untouched.
        result = _with_public_project(result)
    # The job completed: per-item failures (e.g. files that failed to import)
    # are counts inside ``result``, not a tool-level failure. Reporting them
    # must not collapse the whole payload into a bare error.
    return {**base, "status": "completed", "result": strip_path_fields(result)}


def list_projects() -> dict[str, Any]:
    _parse(EmptyArgs, {})
    return _ok(ops.list_projects())


def project_settings_defaults() -> dict[str, Any]:
    _parse(EmptyArgs, {})
    return _ok(ops.project_settings_defaults())


def create_project(
    project_name: str,
    storage_dir: str | None = None,
    overwrite: bool = False,
    modalities: list[str] | None = None,
    site_id: str | None = None,
    uid_root: str | None = None,
    language_code: str | None = None,
    transfer_syntaxes: list[str] | None = None,
    scp: dict[str, Any] | None = None,
    network_timeouts: dict[str, Any] | None = None,
    anonymization_policy: str | None = None,
    confirm: bool = False,
    revision: int | None = None,
) -> dict[str, Any]:
    args, err = _parse(
        CreateProjectArgs,
        {
            "project_name": project_name,
            "storage_dir": storage_dir,
            "overwrite": overwrite,
            "modalities": modalities,
            "site_id": site_id,
            "uid_root": uid_root,
            "language_code": language_code,
            "transfer_syntaxes": transfer_syntaxes,
            "scp": scp,
            "network_timeouts": network_timeouts,
            "anonymization_policy": anonymization_policy,
            "confirm": confirm,
            "revision": revision,
        },
    )
    if err is not None:
        return err
    try:
        scp_dict = args.scp.model_dump(exclude_none=True) if args.scp is not None else None
        timeouts_dict = (
            args.network_timeouts.model_dump(exclude_none=True)
            if args.network_timeouts is not None
            else None
        )
        return _ok(
            _with_public_project(
                ops.create_project(
                    SESSION,
                    args.project_name,
                    storage_dir=args.storage_dir,
                    overwrite=args.overwrite,
                    modalities=args.modalities,
                    site_id=args.site_id,
                    uid_root=args.uid_root,
                    language_code=args.language_code,
                    transfer_syntaxes=args.transfer_syntaxes,
                    scp=scp_dict,
                    network_timeouts=timeouts_dict,
                    anonymization_policy=args.anonymization_policy,
                    confirm=args.confirm,
                    revision=args.revision,
                )
            )
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def project_open(
    project_name: str | None = None,
    storage_dir: str | None = None,
) -> dict[str, Any]:
    args, err = _parse(
        ProjectOpenArgs,
        {
            "project_name": project_name,
            "storage_dir": storage_dir,
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


def update_project_settings(
    modalities: list[str] | None = None,
    transfer_syntaxes: list[str] | None = None,
    scp: dict[str, Any] | None = None,
    network_timeouts: dict[str, Any] | None = None,
    anonymization_policy: str | None = None,
) -> dict[str, Any]:
    args, err = _parse(
        UpdateProjectSettingsArgs,
        {
            "modalities": modalities,
            "transfer_syntaxes": transfer_syntaxes,
            "scp": scp,
            "network_timeouts": network_timeouts,
            "anonymization_policy": anonymization_policy,
        },
    )
    if err is not None:
        return err
    try:
        scp_dict = args.scp.model_dump(exclude_none=True) if args.scp is not None else None
        timeouts_payload = (
            args.network_timeouts.model_dump(exclude_none=True)
            if args.network_timeouts is not None
            else None
        )
        return _ok(
            _with_public_project(
                ops.update_project_settings(
                    _controller(),
                    modalities=args.modalities,
                    transfer_syntaxes=args.transfer_syntaxes,
                    scp=scp_dict,
                    network_timeouts=timeouts_payload,
                    anonymization_policy=args.anonymization_policy,
                )
            )
        )
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
        controller = _controller()
        # Import ops already return a minimal, path-free project summary;
        # do not expand it into the full project snapshot.
        return _start_job_pending(
            "import_directory",
            lambda progress: ops.import_directory(
                controller, args.directory, progress=progress
            ),
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def import_file(file_path: str) -> dict[str, Any]:
    args, err = _parse(ImportFileArgs, {"file_path": file_path})
    if err is not None:
        return err
    try:
        _controller()
        # Import ops already return a minimal, path-free project summary;
        # do not expand it into the full project snapshot.
        return _ok(
            ops.import_file(_controller(), args.file_path, progress=_progress_callback())
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)


def configure_remote(
    ip: str,
    port: int,
    aet: str,
    role: RemoteScpRole = RemoteScpRole.QUERY,
    dicomweb: bool = False,
    http_port: int | None = None,
    http_path: str | None = None,
    use_https: bool = False,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    args, err = _parse(
        ConfigureRemoteArgs,
        {
            "ip": ip,
            "port": port,
            "aet": aet,
            "role": role,
            "dicomweb": dicomweb,
            "http_port": http_port,
            "http_path": http_path,
            "use_https": use_https,
            "username": username,
            "password": password,
        },
    )
    if err is not None:
        return err
    try:
        result = ops.configure_remote(
            _controller(),
            ip=args.ip,
            port=args.port,
            aet=args.aet,
            role=args.role,
            dicomweb=args.dicomweb,
            http_port=args.http_port,
            http_path=args.http_path,
            use_https=args.use_https,
            username=args.username,
            password=args.password,
        )
        return _ok(result)
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
        _controller()
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
        _controller()
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
        controller = _controller()
        return _start_job_pending(
            "remove_pixel_phi",
            lambda progress: ops.remove_pixel_phi(
                controller,
                SESSION,
                patient=args.patient or "",
                study=args.study or "",
                series=args.series or "",
                progress=progress,
            ),
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
        controller = _controller()
        return _start_job_pending(
            "harmonize_studies",
            lambda progress: ops.harmonize_studies(
                controller,
                patient=args.patient or "",
                study=args.study or "",
                progress=progress,
            ),
        )
    except (HeadlessOpsError, ProjectSessionError) as exc:
        return _err(exc)
