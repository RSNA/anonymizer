"""MCP orchestration over existing ProjectController / AI controller APIs.

Selector resolve, inventory shaping, import, pixel-PHI, preview, PACS.
Structured results have no ``{"ok": ...}`` envelopes; raise ``HeadlessOpsError`` on failure.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np

from anonymizer.controller.ai.harmonize import auto_apply_best_study_descriptions
from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    normalize_pixel_phi_removal_mode,
)
from anonymizer.controller.ai_batch_process import apply_remove_pixel_phi_series
from anonymizer.controller.project import MoveStudiesRequest, ProjectController, StudyUIDHierarchy
from anonymizer.controller.runner import RemovePixelPhiRunner
from anonymizer.controller.series_io import load_series_frames
from anonymizer.mcp.session import HeadlessSessionError, ProjectSession
from anonymizer.mcp.snapshots import (
    abridged_path,
    serialize_dicom_node,
    serialize_find_study,
    serialize_inventory_series,
    serialize_move_study,
    serialize_project_info,
)
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.model.project import DICOMNode, ProjectModel
from anonymizer.utils.modalities import resolve_project_modalities
from anonymizer.utils.storage import get_dcm_files, list_import_directory_files
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

_MAX_IMPORT_SAMPLES = 25


class RemoteScpRole(StrEnum):
    QUERY = "QUERY"
    EXPORT = "EXPORT"


class PacsMoveLevel(StrEnum):
    STUDY = "STUDY"
    SERIES = "SERIES"
    INSTANCE = "INSTANCE"


class PreviewImageFormat(StrEnum):
    PNG = "png"
    JPEG = "jpeg"


_CXR_MODALITIES = frozenset({"CR", "DX", "DR", "XC"})


class HeadlessOpsError(Exception):
    """Domain / validation error for headless ops (mapped to MCP ok:false by the View)."""


def _query_scp_key() -> str:
    return _("QUERY")


def _export_scp_key() -> str:
    return _("EXPORT")


def resolve_named_project_dir(project_name: str) -> Path:
    name = project_name.strip()
    if not name:
        raise HeadlessOpsError("project_name is required")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise HeadlessOpsError("project_name must be a single path segment (no slashes)")
    return ProjectModel.base_dir() / name


def resolve_existing_storage_dir(storage_dir: str) -> Path:
    raw = storage_dir.strip()
    if not raw:
        raise HeadlessOpsError("storage_dir is empty")
    path = Path(raw).expanduser().resolve()
    if not path.is_absolute():
        raise HeadlessOpsError(f"storage_dir must be an absolute path: {path}")
    if not path.is_dir():
        raise HeadlessOpsError(f"storage_dir does not exist or is not a directory: {path}")
    return path


def resolve_project_storage(*, project_name: str, storage_dir: str | None) -> Path:
    if storage_dir is not None and str(storage_dir).strip():
        return resolve_existing_storage_dir(storage_dir)
    return resolve_named_project_dir(project_name)


def list_projects() -> dict[str, Any]:
    """List projects under the default Anonymizer store."""
    base = ProjectModel.base_dir()
    projects: list[dict[str, str]] = []
    if base.is_dir():
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            model_path = child / ProjectController.PROJECT_MODEL_FILENAME_JSON
            if model_path.is_file():
                projects.append(
                    {
                        "project_name": child.name,
                        "storage_dir": str(child.resolve()),
                    }
                )
    return {
        "base_dir": str(base.resolve()) if base.exists() else str(base),
        "count": len(projects),
        "projects": projects,
    }


def create_project(
    session: ProjectSession,
    project_name: str,
    storage_dir: str | None = None,
    site_id: str | None = None,
    uid_root: str | None = None,
    overwrite: bool = False,
    modalities: list[str] | str | None = None,
) -> dict[str, Any]:
    try:
        name = project_name.strip()
        if not name:
            raise HeadlessOpsError("project_name is required")
        storage = resolve_project_storage(project_name=name, storage_dir=storage_dir)
        controller = session.create(
            storage_dir=storage,
            project_name=name,
            site_id=site_id,
            uid_root=uid_root,
            overwrite=overwrite,
        )
        apply_project_modalities(controller, modalities)
    except HeadlessSessionError as exc:
        raise HeadlessOpsError(str(exc)) from exc
    return {"project": serialize_project_info(controller)}


def project_open(
    session: ProjectSession,
    project_name: str = "",
    storage_dir: str | None = None,
    modalities: list[str] | str | None = None,
) -> dict[str, Any]:
    try:
        if storage_dir is not None and str(storage_dir).strip():
            storage = resolve_existing_storage_dir(storage_dir)
        elif project_name.strip():
            storage = resolve_named_project_dir(project_name)
        else:
            raise HeadlessOpsError("Provide project_name or storage_dir")
        controller = session.open_path(storage)
        apply_project_modalities(controller, modalities)
    except HeadlessSessionError as exc:
        raise HeadlessOpsError(str(exc)) from exc
    return {"project": serialize_project_info(controller)}


def apply_project_modalities(
    controller: ProjectController,
    modalities: list[str] | str | None,
) -> list[str]:
    """Set allowed ingest modalities (and storage classes) when ``modalities`` is provided.

    ``None`` / empty leaves the project unchanged. Token ``defaults`` expands to
    ``ProjectModel.default_modalities()`` (CR, DX, CT, MR). Persists ProjectModel.json.
    """
    try:
        resolved = resolve_project_modalities(modalities)
    except ValueError as exc:
        raise HeadlessOpsError(str(exc)) from exc
    if resolved is None:
        return list(controller.model.modalities)
    controller.model.modalities = list(resolved)
    controller.model.set_storage_classes_from_modalities()
    controller.save_model()
    logger.info("Project modalities set to %s", resolved)
    return resolved


def project_info(controller: ProjectController) -> dict[str, Any]:
    return {"project": serialize_project_info(controller)}


def _orm_description(obj: Any) -> str:
    """Prefer harmonized description, else raw description (Dataset View convention)."""
    for value in (getattr(obj, "harmonized_description", None), getattr(obj, "description", None)):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _series_description(series) -> str:
    return _orm_description(series)


def _study_description(study) -> str:
    return _orm_description(study)


def _lookup_series_meta(controller: ProjectController, anon_series_uid: str, series_path: Path | None = None) -> dict[str, str]:
    anon_model = controller.anonymizer.model
    for phi in anon_model.load_phi_with_studies_series_no_instances():
        if phi.patient_id == AnonymizerModel.DEFAULT_PHI_PATIENT_ID_PK_VALUE:
            continue
        anon_patient_id = str(phi.anon_patient_id or "")
        for study in phi.studies or []:
            for series in study.series or []:
                if str(series.anon_series_uid or "") != anon_series_uid:
                    continue
                return {
                    "anon_patient_id": anon_patient_id,
                    "series_description": _series_description(series),
                    "modality": str(series.modality or ""),
                }
    anon_patient_id = ""
    if series_path is not None:
        try:
            rel = series_path.resolve().relative_to(controller.model.images_dir().resolve())
            if rel.parts:
                anon_patient_id = rel.parts[0]
        except ValueError:
            pass
    return {
        "anon_patient_id": anon_patient_id,
        "series_description": "",
        "modality": "",
    }


def list_inventory(controller: ProjectController) -> dict[str, Any]:
    images_dir = controller.model.images_dir()
    anon_model = controller.anonymizer.model
    series_rows: list[dict[str, Any]] = []

    patient_order: list[str] = []
    study_order_by_patient: dict[str, list[str]] = {}
    series_count_by_study: dict[tuple[str, str], int] = {}

    for phi in anon_model.load_phi_with_studies_series_no_instances():
        if phi.patient_id == AnonymizerModel.DEFAULT_PHI_PATIENT_ID_PK_VALUE:
            continue
        anon_patient_id = str(phi.anon_patient_id or "")
        if anon_patient_id and anon_patient_id not in patient_order:
            patient_order.append(anon_patient_id)
            study_order_by_patient[anon_patient_id] = []
        for study in phi.studies or []:
            anon_study_uid = str(study.anon_study_uid or "")
            studies = study_order_by_patient.setdefault(anon_patient_id, [])
            if anon_study_uid and anon_study_uid not in studies:
                studies.append(anon_study_uid)
            for series in study.series or []:
                anon_series_uid = str(series.anon_series_uid or "")
                series_path = images_dir / anon_patient_id / anon_study_uid / anon_series_uid
                instance_count = len(get_dcm_files(series_path)) if series_path.is_dir() else 0
                study_key = (anon_patient_id, anon_study_uid)
                series_count_by_study[study_key] = series_count_by_study.get(study_key, 0) + 1
                patient_index = patient_order.index(anon_patient_id) + 1 if anon_patient_id else 0
                study_index = studies.index(anon_study_uid) + 1 if anon_study_uid in studies else 0
                series_index = series_count_by_study[study_key]
                series_rows.append(
                    serialize_inventory_series(
                        anon_patient_id=anon_patient_id,
                        anon_study_uid=anon_study_uid,
                        anon_series_uid=anon_series_uid,
                        modality=str(series.modality or "") or None,
                        instance_count=instance_count,
                        pixel_phi_scanned=bool(series.pixel_phi_scanned),
                        study_description=_study_description(study),
                        series_description=_series_description(series),
                        series_harmonized=bool(
                            str(getattr(series, "harmonized_description", None) or "").strip()
                        ),
                        study_harmonized=bool(
                            str(getattr(study, "harmonized_description", None) or "").strip()
                        ),
                        patient_index=patient_index,
                        study_index=study_index,
                        series_index=series_index,
                        row_index=len(series_rows) + 1,
                    )
                )

    return {
        "count": len(series_rows),
        "series": series_rows,
        "table": _inventory_table(series_rows),
        "project": serialize_project_info(controller),
    }


_INVENTORY_TABLE_HEADER = (
    "patient_index\tstudy_index\tseries_index\tanon_patient_id\tmodality\t"
    "study_description\tstudy_harmonized\tseries_description\tseries_harmonized\t"
    "pixel_phi_scanned"
)


def _inventory_table(rows: list[dict[str, Any]]) -> str:
    """Compact TSV for the LLM — quote only real description fields."""
    lines = [_INVENTORY_TABLE_HEADER]
    for row in rows:
        lines.append(
            "\t".join(
                [
                    str(row.get("patient_index") or ""),
                    str(row.get("study_index") or ""),
                    str(row.get("series_index") or ""),
                    str(row.get("anon_patient_id") or ""),
                    str(row.get("modality") or ""),
                    str(row.get("study_description") or ""),
                    "Y" if row.get("study_harmonized") else "N",
                    str(row.get("series_description") or ""),
                    "Y" if row.get("series_harmonized") else "N",
                    "Y" if row.get("pixel_phi_scanned") else "N",
                ]
            )
        )
    return "\n".join(lines)


_RELATIVE_LAST = frozenset({"last", "latest", "newest", "recent"})
_RELATIVE_FIRST = frozenset({"first", "oldest", "earliest"})
_SERIES_CXR = frozenset({"cxr", "xr", "radiograph", "chest", "chestxray", "chest_xray"})


def _norm_selector(value: str | int | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _patient_order(rows: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    for row in rows:
        pid = str(row.get("anon_patient_id") or "").strip()
        if pid and pid not in ordered:
            ordered.append(pid)
    return ordered


def _match_patient_by_inventory_index(patients: list[str], selector: str) -> str | None:
    """Match ``patient=1`` to the 1-based patient in inventory order."""
    if not selector.isdigit():
        return None
    idx = int(selector)
    if idx < 1 or idx > len(patients):
        raise HeadlessOpsError(
            f"patient={selector!r} out of range (1..{len(patients)}). "
            "Use list_inventory patient_index or anon_patient_id."
        )
    return patients[idx - 1]


def _looks_like_filesystem_path(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if text.startswith("/") or text.startswith("~"):
        return True
    if ":\\" in text or text.startswith("\\\\"):
        return True
    return "/public/" in text.replace("\\", "/") or text.endswith(".dcm")


def _reject_path_selector(label: str, value: str) -> None:
    if _looks_like_filesystem_path(value):
        raise HeadlessOpsError(
            f"{label} must not be a filesystem path. "
            'Use list_inventory selectors (patient="1", series="1"|cxr).'
        )


def _reject_relative_selector(label: str, value: str) -> None:
    key = value.strip().lower().replace(" ", "").replace("-", "")
    if key in _RELATIVE_LAST or key in _RELATIVE_FIRST:
        raise HeadlessOpsError(
            f'{label}={value!r} relative selectors (first|last|latest) are not supported. '
            f'Use a 1-based index from list_inventory (e.g. {label}="1").'
        )


def _series_disk_path(controller: ProjectController, row: dict[str, Any]) -> Path:
    """Rebuild the on-disk series directory from inventory UIDs (internal only)."""
    images_dir = controller.model.images_dir()
    pid = str(row.get("anon_patient_id") or "").strip()
    study = str(row.get("anon_study_uid") or "").strip()
    series = str(row.get("anon_series_uid") or "").strip()
    if not (pid and study and series):
        raise HeadlessOpsError("Inventory row missing ids needed to locate series on disk")
    path = images_dir / pid / study / series
    if not path.is_dir():
        raise HeadlessOpsError(f"Series directory missing on disk for {pid} series_index={row.get('series_index')}")
    return path


def _study_order(rows: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    for row in rows:
        sid = str(row.get("anon_study_uid") or "").strip()
        if sid and sid not in ordered:
            ordered.append(sid)
    return ordered


def _pick_index(items: list[str], selector: str, *, label: str) -> str:
    if not items:
        raise HeadlessOpsError(f"No {label} values to select from")
    if not selector.isdigit():
        raise HeadlessOpsError(
            f'Invalid {label}={selector!r}. Use a 1-based index from list_inventory (e.g. {label}="1").'
        )
    idx = int(selector)
    if idx < 1 or idx > len(items):
        raise HeadlessOpsError(f"{label}={selector!r} out of range (1..{len(items)})")
    return items[idx - 1]


def _filter_series_rows(
    rows: list[dict[str, Any]],
    *,
    series_selector: str,
) -> list[dict[str, Any]]:
    """Filter series rows by index, modality, cxr, unscanned, or description substring."""
    key = series_selector.strip()
    if not key:
        return list(rows)
    _reject_relative_selector("series", key)
    lower = key.lower().replace(" ", "").replace("-", "")
    if lower in {"unscanned", "new", "pending"}:
        unscanned = [r for r in rows if not r.get("pixel_phi_scanned")]
        return unscanned or list(rows)
    if lower in _SERIES_CXR or key.upper() in _CXR_MODALITIES:
        return [r for r in rows if (r.get("modality") or "").upper() in _CXR_MODALITIES]
    if len(key) <= 4 and key.isalpha():
        mod = key.upper()
        matched = [r for r in rows if (r.get("modality") or "").upper() == mod]
        if matched:
            return matched
    needle = key.lower()
    matched = [
        r
        for r in rows
        if needle in str(r.get("series_description") or "").lower()
    ]
    if matched:
        return matched
    raise HeadlessOpsError(
        f"No series matched series={series_selector!r}. "
        'Use list_inventory series_index (e.g. series="1"), modality, or description substring.'
    )


def resolve_series(
    controller: ProjectController,
    *,
    patient: str = "",
    study: str = "",
    series: str = "",
    anon_series_uid: str = "",
    series_path: str | None = None,
    modality_hint: str | None = None,
) -> dict[str, Any]:
    """Resolve one inventory series via list_inventory indices (not paths).

    patient: <patient_index> | <anon_patient_id>
    study:   <study_index>  (within patient)
    series:  <series_index> | cxr | unscanned | modality | description substring
    """
    if series_path is not None and str(series_path).strip():
        raise HeadlessOpsError(
            "series_path is not supported. "
            'Use list_inventory indices: patient="1", series="1".'
        )

    uid = (anon_series_uid or "").strip()
    if uid:
        if _looks_like_filesystem_path(uid):
            raise HeadlessOpsError(
                "anon_series_uid must not be a filesystem path. "
                "Use patient=/series= selectors from list_inventory."
            )
        images_dir = controller.model.images_dir().resolve()
        matches = [
            p
            for p in images_dir.rglob(uid)
            if p.is_dir() and p.name == uid and images_dir in p.parents
        ]
        matches = sorted(matches, key=lambda p: len(p.relative_to(images_dir).parts))
        if not matches:
            raise HeadlessOpsError(f"No series directory found for anon_series_uid={uid}")
        path = matches[0]
        meta = _lookup_series_meta(controller, path.name, series_path=path)
        return {
            "anon_patient_id": meta.get("anon_patient_id") or None,
            "anon_study_uid": path.parent.name if path.parent else None,
            "anon_series_uid": path.name,
            "series_description": meta.get("series_description") or None,
            "modality": meta.get("modality") or None,
            "series_path": str(path),
            "caption": (
                f"{(meta.get('anon_patient_id') or 'Patient').strip() or 'Patient'} — "
                f"{(meta.get('series_description') or meta.get('modality') or 'Series').strip()}"
            ),
        }

    inv = list_inventory(controller)
    rows: list[dict[str, Any]] = list(inv.get("series") or [])
    if not rows:
        raise HeadlessOpsError("No series in inventory yet. Import a study first.")

    patient_sel = _norm_selector(patient)
    study_sel = _norm_selector(study)
    series_sel = _norm_selector(series) or _norm_selector(modality_hint)
    _reject_path_selector("patient", patient_sel)
    _reject_path_selector("study", study_sel)
    _reject_path_selector("series", series_sel)
    _reject_relative_selector("patient", patient_sel)
    _reject_relative_selector("study", study_sel)
    _reject_relative_selector("series", series_sel)

    # "all" means no filter for study/series. For patient it must not be treated as an id —
    # export/preview needs one patient; use patient_index from list_inventory instead.
    if patient_sel.lower() in {"all", "*"}:
        raise HeadlessOpsError(
            'patient="all" is not valid for series preview/export. '
            'Call list_inventory, then pass one patient_index (e.g. patient="2") '
            "or anon_patient_id from that table."
        )
    if study_sel.lower() in {"all", "*"}:
        study_sel = ""
    if series_sel.lower() in {"all", "*"}:
        series_sel = ""

    filtered = list(rows)

    if patient_sel:
        patients = _patient_order(filtered)
        if patient_sel.isdigit():
            target_patient = _match_patient_by_inventory_index(patients, patient_sel)
        else:
            exact = [p for p in patients if p == patient_sel]
            if not exact:
                exact = [p for p in patients if p.startswith(patient_sel)]
            if len(exact) == 1:
                target_patient = exact[0]
            elif len(exact) > 1:
                raise HeadlessOpsError(
                    f"Ambiguous patient={patient_sel!r}; matches: {', '.join(exact[:5])}"
                )
            else:
                raise HeadlessOpsError(
                    f"Unknown patient={patient_sel!r}. "
                    'Use list_inventory patient_index (e.g. patient="1") or anon_patient_id. '
                    f"Known: {', '.join(patients[:8])}"
                )
        filtered = [r for r in filtered if str(r.get("anon_patient_id") or "") == target_patient]
        if not filtered:
            raise HeadlessOpsError(f"No series for patient={target_patient!r}")

    if study_sel:
        # Prefer inventory study_index when present; else 1-based order of distinct studies.
        by_study_index = [
            r for r in filtered if str(r.get("study_index") or "") == study_sel
        ]
        if study_sel.isdigit() and by_study_index:
            filtered = by_study_index
        else:
            studies = _study_order(filtered)
            picked = _pick_index(studies, study_sel, label="study")
            filtered = [r for r in filtered if str(r.get("anon_study_uid") or "") == picked]
        if not filtered:
            raise HeadlessOpsError(f"No series for study selector={study_sel!r}")

    if series_sel:
        if series_sel.isdigit():
            want = int(series_sel)
            # Global row_index when patient omitted (e.g. "second series in inventory").
            by_row = [r for r in filtered if int(r.get("row_index") or 0) == want]
            by_index = [r for r in filtered if int(r.get("series_index") or 0) == want]
            if not patient_sel and by_row:
                filtered = by_row
            elif by_index:
                filtered = by_index
            elif patient_sel and 1 <= want <= len(filtered):
                filtered = [filtered[want - 1]]
            else:
                raise HeadlessOpsError(
                    f"No series matched series={series_sel!r}. "
                    "Call list_inventory; use series_index within a patient, "
                    "or row_index when patient is omitted."
                )
            pick_row = filtered[0]
        else:
            filtered = _filter_series_rows(filtered, series_selector=series_sel)
            if len(filtered) != 1:
                raise HeadlessOpsError(
                    f"series={series_sel!r} matched {len(filtered)} series; "
                    'pass series_index from list_inventory (e.g. series="1").'
                )
            pick_row = filtered[0]
    else:
        if len(filtered) == 1:
            pick_row = filtered[0]
        else:
            raise HeadlessOpsError(
                f"{len(filtered)} series match; pass series_index from list_inventory "
                '(e.g. patient="1", series="1"), or row_index as series="2" with no patient.'
            )

    path = _series_disk_path(controller, pick_row)
    patient_id = str(pick_row.get("anon_patient_id") or "").strip() or "Patient"
    desc = (
        str(pick_row.get("series_description") or "").strip()
        or str(pick_row.get("modality") or "").strip()
        or "Series"
    )
    return {
        "anon_patient_id": pick_row.get("anon_patient_id") or None,
        "anon_study_uid": pick_row.get("anon_study_uid") or None,
        "anon_series_uid": pick_row.get("anon_series_uid") or None,
        "patient_index": pick_row.get("patient_index"),
        "study_index": pick_row.get("study_index"),
        "series_index": pick_row.get("series_index"),
        "row_index": pick_row.get("row_index"),
        "series_description": pick_row.get("series_description") or None,
        "modality": pick_row.get("modality") or None,
        "pixel_phi_scanned": bool(pick_row.get("pixel_phi_scanned")),
        "series_path": str(path),
        "caption": f"{patient_id} — {desc}",
    }


def resolve_series_path(
    controller: ProjectController,
    *,
    anon_series_uid: str = "",
    series_path: str | None = None,
    modality_hint: str | None = None,
    patient: str = "",
    study: str = "",
    series: str = "",
) -> Path:
    """Resolve a series directory (friendly selectors or power-user UID/path)."""
    resolved = resolve_series(
        controller,
        patient=patient,
        study=study,
        series=series,
        anon_series_uid=anon_series_uid,
        series_path=series_path,
        modality_hint=modality_hint,
    )
    return Path(str(resolved["series_path"]))


def remove_pixel_phi(
    controller: ProjectController,
    session: ProjectSession,
    *,
    anon_series_uid: str = "",
    series_path: str | None = None,
    removal_mode: PixelPhiRemovalMode | str = PixelPhiRemovalMode.BLACKOUT,
    use_modality_whitelist: bool = True,
    modality_hint: str = "",
    patient: str = "",
    study: str = "",
    series: str = "",
) -> dict[str, Any]:
    series_sel = _norm_selector(series)
    patient_sel = _norm_selector(patient)
    if series_sel.lower() in {"all", "*"} or patient_sel.lower() in {"all", "*"}:
        inv = list_inventory(controller)
        rows = list(inv.get("series") or [])
        if not rows:
            raise HeadlessOpsError("No series in inventory. Import DICOM first.")
        results: list[dict[str, Any]] = []
        failed = 0
        for row in rows:
            uid = str(row.get("anon_series_uid") or "").strip()
            if not uid:
                continue
            try:
                one = remove_pixel_phi(
                    controller,
                    session,
                    anon_series_uid=uid,
                    removal_mode=removal_mode,
                    use_modality_whitelist=use_modality_whitelist,
                )
                results.append(
                    {
                        "anon_series_uid": one.get("anon_series_uid"),
                        "anon_patient_id": one.get("anon_patient_id"),
                        "status": one.get("status"),
                        "caption": one.get("caption"),
                    }
                )
            except HeadlessOpsError as exc:
                failed += 1
                results.append(
                    {
                        "anon_series_uid": uid,
                        "anon_patient_id": row.get("anon_patient_id"),
                        "status": "failed",
                        "detail": str(exc),
                    }
                )
        return {
            "status": "ok" if failed == 0 else "partial",
            "detail": (
                f"Pixel PHI processed for {len(results)} series"
                + (f" ({failed} failed)." if failed else ".")
            ),
            "series_count": len(results),
            "failed": failed,
            "results": results,
            "project": serialize_project_info(controller),
        }

    try:
        path = resolve_series_path(
            controller,
            anon_series_uid=anon_series_uid,
            series_path=series_path,
            modality_hint=modality_hint or None,
            patient=patient,
            study=study,
            series=series,
        )
        mode = normalize_pixel_phi_removal_mode(removal_mode, default=PixelPhiRemovalMode.BLACKOUT)
    except ValueError as exc:
        raise HeadlessOpsError(str(exc)) from exc

    runner = RemovePixelPhiRunner()
    try:
        handle = session.ensure_ocr_reader(runner)
        reader = getattr(handle, "reader", None)
        if reader is None:
            raise HeadlessOpsError("OCR reader failed to load")
        outcome = apply_remove_pixel_phi_series(
            path,
            anon_model=controller.anonymizer.model,
            ocr_reader=reader,
            removal_mode=mode,
            project_dir=controller.model.storage_dir,
            use_modality_whitelist=use_modality_whitelist,
        )
    except HeadlessOpsError:
        raise
    except Exception as exc:
        logger.exception("remove_pixel_phi failed for %s", path)
        raise HeadlessOpsError(str(exc)) from exc

    safe_detail: str | None = None
    if outcome.status in {"failed", "skipped", "complete"}:
        safe_detail = outcome.message
    elif outcome.status == "ok":
        safe_detail = "Burnt-in text removed from one or more instances"

    anon_uid = path.name
    scanned = controller.anonymizer.model.series_pixel_phi_scanned(anon_uid)
    if outcome.status == "failed":
        raise HeadlessOpsError(outcome.message or "remove_pixel_phi failed")

    meta = _lookup_series_meta(controller, anon_uid, series_path=path)
    patient_id = str(meta.get("anon_patient_id") or "").strip() or "Patient"
    desc = (
        str(meta.get("series_description") or "").strip()
        or str(meta.get("modality") or "").strip()
        or "Series"
    )
    return {
        "status": outcome.status,
        "detail": safe_detail,
        "anon_series_uid": anon_uid,
        "anon_patient_id": meta.get("anon_patient_id") or None,
        "series_description": meta.get("series_description") or None,
        "modality": meta.get("modality") or None,
        "caption": f"{patient_id} — {desc}",
        "removal_mode": mode.value,
        "pixel_phi_scanned": scanned,
        "project": serialize_project_info(controller),
    }


def export_series_preview(
    controller: ProjectController,
    *,
    anon_series_uid: str = "",
    series_path: str | None = None,
    frame_index: int = 0,
    image_format: PreviewImageFormat | str = PreviewImageFormat.PNG,
    require_pixel_phi_scanned: bool = False,
    modality_hint: str = "",
    size: int = 448,
    patient: str = "",
    study: str = "",
    series: str = "",
) -> dict[str, Any]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise HeadlessOpsError(f"Pillow required for preview export: {exc}") from exc

    resolved = resolve_series(
        controller,
        anon_series_uid=anon_series_uid,
        series_path=series_path,
        modality_hint=modality_hint or None,
        patient=patient,
        study=study,
        series=series,
    )
    path = Path(str(resolved["series_path"]))

    anon_uid = path.name
    scanned = controller.anonymizer.model.series_pixel_phi_scanned(anon_uid)
    if require_pixel_phi_scanned and not scanned:
        raise HeadlessOpsError(
            "Series has not been scanned for burnt-in (pixel) PHI yet. "
            "Call remove_pixel_phi first, or omit require_pixel_phi_scanned."
        )

    if isinstance(image_format, PreviewImageFormat):
        fmt = image_format.value
    else:
        fmt = str(image_format or PreviewImageFormat.PNG.value).strip().lower().lstrip(".")
    if fmt == "jpg":
        fmt = PreviewImageFormat.JPEG.value
    try:
        fmt = PreviewImageFormat(fmt).value
    except ValueError as exc:
        raise HeadlessOpsError(
            f"Unsupported image_format={image_format!r} (use png or jpeg)"
        ) from exc

    try:
        out_size = int(size)
    except (TypeError, ValueError) as exc:
        raise HeadlessOpsError(f"Invalid size={size!r} (expected positive int)") from exc
    if out_size < 32 or out_size > 4096:
        raise HeadlessOpsError(f"size must be between 32 and 4096 (got {out_size})")

    logger.info(
        "image transfer — starting export series=%s frame=%s size=%s format=%s",
        path.name,
        frame_index,
        out_size,
        fmt,
    )
    t0 = time.perf_counter()

    try:
        loaded = load_series_frames(path)
    except Exception as exc:
        raise HeadlessOpsError(f"Failed to load series frames: {exc}") from exc

    frames = loaded.frames
    if frames is None or len(frames) == 0:
        raise HeadlessOpsError("Series has no frames")

    idx = int(frame_index)
    if idx < 0 or idx >= len(frames):
        raise HeadlessOpsError(f"frame_index {idx} out of range (0..{len(frames) - 1})")

    from anonymizer.utils.windowing import apply_windowing

    frame = frames[idx]
    wl, ww = loaded.default_window
    try:
        bgr = apply_windowing(float(wl), float(ww), frame)
    except Exception:
        from anonymizer.controller.ai.harmonize.xp_bodypart.preprocess import (
            uint8_grayscale_from_array,
        )

        gray = uint8_grayscale_from_array(np.asarray(frame))
        bgr = np.stack([gray, gray, gray], axis=-1)

    rgb = bgr[:, :, ::-1] if bgr.ndim == 3 else np.stack([bgr, bgr, bgr], axis=-1)
    image = Image.fromarray(rgb.astype(np.uint8), mode="RGB")
    native_width, native_height = image.size
    if image.size != (out_size, out_size):
        image = image.resize((out_size, out_size), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    save_kwargs: dict[str, Any] = {}
    if fmt == "jpeg":
        save_kwargs["quality"] = 92
    image.save(buf, format=fmt.upper(), **save_kwargs)
    raw = buf.getvalue()
    mime = "image/jpeg" if fmt == "jpeg" else "image/png"

    modality = getattr(loaded.metadata, "Modality", None)
    meta = _lookup_series_meta(controller, anon_uid, series_path=path)
    patient_id = (
        str(resolved.get("anon_patient_id") or meta.get("anon_patient_id") or "").strip()
        or "Patient"
    )
    desc = (
        str(resolved.get("series_description") or meta.get("series_description") or "").strip()
        or str(modality or resolved.get("modality") or meta.get("modality") or "").strip()
        or "Series"
    )
    b64 = base64.b64encode(raw).decode("ascii")
    logger.info(
        "image transfer — done export series=%s %.3fs mime=%s bytes=%d b64_chars=%d %dx%d",
        path.name,
        time.perf_counter() - t0,
        mime,
        len(raw),
        len(b64),
        image.width,
        image.height,
    )
    return {
        "anon_series_uid": anon_uid,
        "anon_patient_id": resolved.get("anon_patient_id") or meta.get("anon_patient_id") or None,
        "patient_index": resolved.get("patient_index"),
        "study_index": resolved.get("study_index"),
        "series_index": resolved.get("series_index"),
        "row_index": resolved.get("row_index"),
        "series_description": resolved.get("series_description")
        or meta.get("series_description")
        or None,
        "caption": str(resolved.get("caption") or f"{patient_id} — {desc}"),
        "preview_base64": b64,
        "mime_type": mime,
        "byte_length": len(raw),
        "format": fmt,
        "frame_index": idx,
        "frame_count": len(frames),
        "width": image.width,
        "height": image.height,
        "native_width": native_width,
        "native_height": native_height,
        "size": out_size,
        "modality": str(modality) if modality else (resolved.get("modality") or meta.get("modality") or None),
        "pixel_phi_scanned": scanned,
        "project": serialize_project_info(controller),
    }


def _inventory_study_keys(controller: ProjectController) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []
    anon_model = controller.anonymizer.model
    for phi in anon_model.load_phi_with_studies_series_no_instances():
        if phi.patient_id == AnonymizerModel.DEFAULT_PHI_PATIENT_ID_PK_VALUE:
            continue
        anon_patient_id = str(phi.anon_patient_id or "").strip()
        if not anon_patient_id:
            continue
        for study in phi.studies or []:
            anon_study_uid = str(study.anon_study_uid or "").strip()
            if not anon_study_uid:
                continue
            key = (anon_patient_id, anon_study_uid)
            if key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def harmonize_studies(
    controller: ProjectController,
    *,
    patient: str = "",
    study: str = "",
    anon_study_uids: list[str] | None = None,
) -> dict[str, Any]:
    """Harmonize study/series descriptions via ``ProjectController.harmonize_studies``.

    omit patient+study, or patient=all → every study
    patient=<patient_index>|<anon_patient_id> → that patient's studies
    study=<study_index> → one study within the patient
    """
    patient_sel = _norm_selector(patient)
    study_sel = _norm_selector(study)
    _reject_path_selector("patient", patient_sel)
    _reject_path_selector("study", study_sel)
    _reject_relative_selector("patient", patient_sel)
    _reject_relative_selector("study", study_sel)
    if patient_sel.lower() in {"all", "*"}:
        patient_sel = ""
    if study_sel.lower() in {"all", "*"}:
        study_sel = ""

    wanted_uids = [u.strip() for u in (anon_study_uids or []) if str(u).strip()]
    if wanted_uids:
        all_studies = _inventory_study_keys(controller)
        if not all_studies:
            raise HeadlessOpsError("No studies in inventory. Import DICOM first.")
        wanted_set = set(wanted_uids)
        studies = [(pid, sid) for pid, sid in all_studies if sid in wanted_set]
        missing = sorted(wanted_set - {sid for _, sid in studies})
        if missing:
            raise HeadlessOpsError(
                "Unknown anon_study_uid(s). Call list_inventory and use selectors "
                f"(patient=/study=) instead. Missing: {', '.join(missing[:5])}"
            )
    else:
        inv = list_inventory(controller)
        rows: list[dict[str, Any]] = list(inv.get("series") or [])
        if not rows:
            raise HeadlessOpsError("No studies in inventory. Import DICOM first.")

        filtered = list(rows)
        if patient_sel:
            patients = _patient_order(filtered)
            if patient_sel.isdigit():
                target_patient = _match_patient_by_inventory_index(patients, patient_sel)
            else:
                exact = [p for p in patients if p == patient_sel]
                if not exact:
                    exact = [p for p in patients if p.startswith(patient_sel)]
                if len(exact) == 1:
                    target_patient = exact[0]
                elif len(exact) > 1:
                    raise HeadlessOpsError(
                        f"Ambiguous patient={patient_sel!r}; matches: {', '.join(exact[:5])}"
                    )
                else:
                    raise HeadlessOpsError(
                        f"Unknown patient={patient_sel!r}. "
                        'Use list_inventory patient_index (e.g. patient="1") or anon_patient_id.'
                    )
            if target_patient is None:
                raise HeadlessOpsError(f"Unknown patient={patient_sel!r}")
            filtered = [r for r in filtered if str(r.get("anon_patient_id") or "") == target_patient]
            if not filtered:
                raise HeadlessOpsError(f"No studies for patient={target_patient!r}")

        if study_sel:
            if not patient_sel:
                raise HeadlessOpsError(
                    'study= requires patient= (e.g. patient="1", study="1"). '
                    'Use patient="all" or omit both for every study.'
                )
            studies_for_patient = _study_order(filtered)
            picked_study = _pick_index(studies_for_patient, study_sel, label="study")
            filtered = [r for r in filtered if str(r.get("anon_study_uid") or "") == picked_study]

        seen: set[tuple[str, str]] = set()
        studies: list[tuple[str, str]] = []
        for row in filtered:
            pid = str(row.get("anon_patient_id") or "").strip()
            sid = str(row.get("anon_study_uid") or "").strip()
            if not pid or not sid:
                continue
            key = (pid, sid)
            if key not in seen:
                seen.add(key)
                studies.append(key)

    if not studies:
        raise HeadlessOpsError("No matching studies to harmonize.")

    try:
        summary = controller.harmonize_studies(studies)
    except Exception as exc:
        logger.exception("harmonize_studies failed")
        raise HeadlessOpsError(str(exc)) from exc

    # Series batch does not write StudyDescription; same follow-up as AI batch / Series View.
    study_uids = [sid for _, sid in studies]
    study_applied: list[dict[str, Any]] = []
    try:
        for offer, updated_uids in auto_apply_best_study_descriptions(
            images_dir=controller.model.images_dir(),
            anon_model=controller.anonymizer.model,
            anon_study_uids=study_uids,
        ):
            name = ""
            if offer.matches:
                name = str(offer.matches[0].long_common_name or "").strip()
            study_applied.append(
                {
                    "study_description": name,
                    "studies_updated": len(updated_uids),
                }
            )
    except Exception as exc:
        logger.exception("auto_apply_best_study_descriptions failed")
        raise HeadlessOpsError(f"Series harmonized but study descriptions failed: {exc}") from exc

    return {
        "study_count": len(studies),
        "processed": summary.processed,
        "applied": summary.applied,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "cancelled": summary.cancelled,
        "study_descriptions_applied": sum(item["studies_updated"] for item in study_applied),
        "study_description_results": study_applied,
        "project": serialize_project_info(controller),
    }


def _import_paths(controller: ProjectController, paths: list[str], *, source: str) -> dict[str, Any]:
    succeeded = 0
    skipped = 0
    failed = 0
    samples: list[dict[str, Any]] = []
    already_stored = _("Instance already stored")

    for path in paths:
        error_msg, ds = controller.anonymizer.anonymize_file(Path(path))
        anon_patient_id = str(ds.PatientID) if ds is not None and hasattr(ds, "PatientID") else None
        entry = {
            "path": abridged_path(path),
            "anon_patient_id": anon_patient_id,
            "error": error_msg,
        }
        if error_msg is None:
            succeeded += 1
            if len(samples) < _MAX_IMPORT_SAMPLES and anon_patient_id:
                samples.append({**entry, "status": "ok"})
        elif error_msg == already_stored or already_stored in str(error_msg):
            skipped += 1
        else:
            failed += 1
            if len(samples) < _MAX_IMPORT_SAMPLES:
                samples.append({**entry, "status": "failed"})

    return {
        "source": source,
        "files_seen": len(paths),
        "succeeded": succeeded,
        "skipped": skipped,
        "failed": failed,
        "samples": samples,
        "project": serialize_project_info(controller),
    }


def import_directory(controller: ProjectController, directory: str) -> dict[str, Any]:
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise HeadlessOpsError(
            f"Not a directory: {root}. For a single DICOM file use import_file instead."
        )
    paths = list_import_directory_files(root)
    result = _import_paths(controller, paths, source=str(root))
    result["directory"] = str(root)
    return result


def import_file(controller: ProjectController, file_path: str) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise HeadlessOpsError(
            f"Not a file: {path}. For a folder of DICOM files use import_directory instead."
        )
    result = _import_paths(controller, [str(path)], source=str(path))
    result["file"] = str(path)
    return result


def configure_remote(
    controller: ProjectController,
    *,
    ip: str,
    port: int,
    aet: str,
    role: RemoteScpRole | str = RemoteScpRole.QUERY,
) -> dict[str, Any]:
    """Thin adapter: set ``remote_scps`` + ``save_model`` (no controller changes)."""
    try:
        role_enum = role if isinstance(role, RemoteScpRole) else RemoteScpRole(str(role).strip().upper())
    except ValueError as exc:
        raise HeadlessOpsError(
            f"role must be {RemoteScpRole.QUERY.value} or {RemoteScpRole.EXPORT.value}"
        ) from exc
    scp_key = _query_scp_key() if role_enum is RemoteScpRole.QUERY else _export_scp_key()

    if not ip.strip() or not aet.strip():
        raise HeadlessOpsError("ip and aet are required")
    if not (1 <= int(port) <= 65535):
        raise HeadlessOpsError("port must be 1–65535")

    node = DICOMNode(ip.strip(), int(port), aet.strip(), False)
    controller.model.remote_scps[scp_key] = node
    if not controller.save_model():
        raise HeadlessOpsError("Failed to save ProjectModel.json")

    return {
        "role": role_enum.value,
        "remote": serialize_dicom_node(node),
        "project": serialize_project_info(controller),
    }


def pacs_find(
    controller: ProjectController,
    *,
    patient_name: str = "",
    patient_id: str = "",
    accession: str = "",
    study_date: str = "",
    modality: str = "",
) -> dict[str, Any]:
    """Thin adapter: ``ProjectController.find_studies`` → allowlisted study dicts."""
    scp_key = _query_scp_key()
    if scp_key not in controller.model.remote_scps:
        raise HeadlessOpsError(f"No {scp_key} remote configured. Call configure_remote first.")

    try:
        results = controller.find_studies(
            scp_key,
            patient_name or "",
            patient_id or "",
            accession or "",
            study_date or "",
            modality or "",
            ux_Q=None,
            verify_attributes=True,
        )
    except Exception as exc:
        raise HeadlessOpsError(str(exc)) from exc

    studies = [serialize_find_study(ds) for ds in (results or [])]
    return {
        "query": {
            "patient_name_provided": bool(patient_name),
            "patient_id": patient_id or "",
            "accession": accession or "",
            "study_date": study_date or "",
            "modality": modality or "",
        },
        "count": len(studies),
        "studies": studies,
    }


def pacs_move(
    controller: ProjectController,
    session: ProjectSession,
    *,
    studies: list[dict[str, str]],
    level: PacsMoveLevel | str = PacsMoveLevel.SERIES,
) -> dict[str, Any]:
    """Thin adapter: ensure SCP → ``get_study_uid_hierarchies`` / ``manage_move``."""
    try:
        session.ensure_scp()
    except HeadlessSessionError as exc:
        raise HeadlessOpsError(str(exc)) from exc

    if not studies:
        raise HeadlessOpsError("studies list is empty")

    scp_key = _query_scp_key()
    if scp_key not in controller.model.remote_scps:
        raise HeadlessOpsError(f"No {scp_key} remote configured. Call configure_remote first.")

    hierarchies: list[StudyUIDHierarchy] = []
    for item in studies:
        study_uid = (item.get("study_instance_uid") or "").strip()
        ptid = (item.get("patient_id") or "").strip()
        if not study_uid:
            raise HeadlessOpsError("each study requires study_instance_uid")
        hierarchies.append(StudyUIDHierarchy(uid=study_uid, ptid=ptid))

    level_text = level.value if isinstance(level, PacsMoveLevel) else str(level).strip().upper()
    if level_text in (_("IMAGE"), "IMAGE"):
        level_text = PacsMoveLevel.INSTANCE.value
    try:
        level_enum = PacsMoveLevel(level_text)
    except ValueError as exc:
        raise HeadlessOpsError(
            f"level must be {PacsMoveLevel.STUDY.value}, {PacsMoveLevel.SERIES.value}, "
            f"or {PacsMoveLevel.INSTANCE.value}"
        ) from exc
    instance_level = level_enum is PacsMoveLevel.INSTANCE
    try:
        controller.get_study_uid_hierarchies(scp_key, hierarchies, instance_level=instance_level)
    except Exception as exc:
        raise HeadlessOpsError(f"Failed to resolve study hierarchy: {exc}") from exc

    usable = [s for s in hierarchies if s.series and not s.last_error_msg]
    if not usable:
        raise HeadlessOpsError("No studies resolved for move")

    dest_aet = controller.model.scp.aet
    request = MoveStudiesRequest(
        scp_name=scp_key,
        dest_scp_ae=dest_aet,
        level=level_enum.value,
        studies=usable,
    )
    try:
        controller.manage_move(request)
    except Exception as exc:
        raise HeadlessOpsError(f"Move failed: {exc}") from exc

    return {
        "dest_aet": dest_aet,
        "level": level_enum.value,
        "studies": [serialize_move_study(s) for s in hierarchies],
        "project": serialize_project_info(controller),
    }
