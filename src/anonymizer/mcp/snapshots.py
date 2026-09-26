"""Allowlisted non-PHI snapshots for MCP tool results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydicom.dataset import Dataset

from anonymizer.controller.project import ProjectController, StudyUIDHierarchy
from anonymizer.model.project import DICOMNode

# Paths teach MCP clients to leave the tool API — omit from public project snapshots.
_MCP_PROJECT_PATH_KEYS = frozenset({"storage_dir", "images_dir", "private_dir"})
_MCP_INVENTORY_INTERNAL_KEYS = frozenset(
    {
        "anon_study_uid",
        "anon_series_uid",
        "series_path",
        "series_path_abridged",
        "_disk_path",
    }
)

# Always present on public inventory rows (LLM-facing).
_MCP_INVENTORY_PUBLIC_KEYS = (
    "row_index",
    "patient_index",
    "study_index",
    "series_index",
    "anon_patient_id",
    "modality",
    "study_description",
    "study_harmonized",
    "series_description",
    "series_harmonized",
    "instance_count",
    "pixel_phi_scanned",
)


def serialize_project_info(controller: ProjectController) -> dict[str, Any]:
    """Safe project snapshot — no PHI, passwords, or lookup tables."""
    model = controller.model
    totals = controller.get_totals()
    return {
        "project_name": model.project_name,
        "site_id": model.site_id,
        "uid_root": model.uid_root,
        "storage_dir": str(model.storage_dir),
        "images_dir": str(model.images_dir()),
        "private_dir": str(model.private_dir()),
        "model_version": model.version,
        "modalities": list(model.modalities),
        "imported_modalities": controller.get_imported_modalities(),
        "totals": {
            "patients": totals.patients,
            "studies": totals.studies,
            "series": totals.series,
            "instances": totals.instances,
        },
        "remote_scps": {name: serialize_dicom_node(node) for name, node in model.remote_scps.items()},
        "local_scp": serialize_dicom_node(model.scp),
    }


def public_project_info(controller: ProjectController) -> dict[str, Any]:
    """Project snapshot for MCP clients — no filesystem paths."""
    raw = serialize_project_info(controller)
    return {k: v for k, v in raw.items() if k not in _MCP_PROJECT_PATH_KEYS}


def serialize_dicom_node(node: DICOMNode) -> dict[str, Any]:
    return {"ip": node.ip, "port": node.port, "aet": node.aet, "local": node.local}


def abridged_path(path: str | Path, depth: int = 3) -> str:
    parts = Path(path).parts
    if len(parts) <= depth:
        return str(path)
    return ".../" + "/".join(parts[-depth:])


def serialize_inventory_series(
    *,
    anon_patient_id: str,
    anon_study_uid: str,
    anon_series_uid: str,
    modality: str | None,
    instance_count: int,
    pixel_phi_scanned: bool,
    series_description: str | None = None,
    study_description: str | None = None,
    series_harmonized: bool = False,
    study_harmonized: bool = False,
    patient_index: int = 0,
    study_index: int = 0,
    series_index: int = 0,
    row_index: int = 0,
) -> dict[str, Any]:
    """Allowlisted inventory row — indices + anon patient id (no filesystem paths).

    UIDs are kept for internal resolve/path rebuild; strip via ``public_inventory_row``
    before returning from MCP tools.
    """
    return {
        "row_index": int(row_index),
        "patient_index": int(patient_index),
        "study_index": int(study_index),
        "series_index": int(series_index),
        "anon_patient_id": anon_patient_id,
        "anon_study_uid": anon_study_uid,
        "anon_series_uid": anon_series_uid,
        "modality": modality or "",
        "study_description": (study_description or "").strip(),
        "study_harmonized": bool(study_harmonized),
        "series_description": (series_description or "").strip(),
        "series_harmonized": bool(series_harmonized),
        "instance_count": instance_count,
        "pixel_phi_scanned": pixel_phi_scanned,
    }


def public_inventory_row(row: dict[str, Any]) -> dict[str, Any]:
    """Inventory row for MCP — indices + descriptions (no UIDs or paths)."""
    out: dict[str, Any] = {}
    for key in _MCP_INVENTORY_PUBLIC_KEYS:
        if key == "study_description":
            out[key] = str(row.get("study_description") or "").strip()
        elif key == "series_description":
            out[key] = str(row.get("series_description") or "").strip()
        elif key in {"study_harmonized", "series_harmonized", "pixel_phi_scanned"}:
            out[key] = bool(row.get(key))
        elif key in {
            "instance_count",
            "row_index",
            "patient_index",
            "study_index",
            "series_index",
        }:
            out[key] = int(row.get(key) or 0)
        elif key in {"anon_patient_id", "modality"}:
            out[key] = str(row.get(key) or "")
        else:
            out[key] = row.get(key)
    return out


def public_inventory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip internal fields from a list_inventory-style payload."""
    out = dict(payload)
    series = out.get("series")
    if isinstance(series, list):
        out["series"] = [public_inventory_row(r) if isinstance(r, dict) else r for r in series]
    project = out.get("project")
    if isinstance(project, dict):
        out["project"] = {k: v for k, v in project.items() if k not in _MCP_PROJECT_PATH_KEYS}
    return out


def strip_path_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove filesystem path keys from a tool result (recursive on nested dicts)."""
    skip = frozenset(
        {
            "series_path",
            "series_path_abridged",
            "storage_dir",
            "images_dir",
            "private_dir",
            "_disk_path",
        }
    )
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in skip:
            continue
        if isinstance(value, dict):
            out[key] = strip_path_fields(value)
        elif isinstance(value, list):
            out[key] = [
                strip_path_fields(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            out[key] = value
    return out


def serialize_find_study(ds: Dataset) -> dict[str, Any]:
    """Allowlisted C-FIND study fields. Omits PatientName; keeps PatientID for C-MOVE."""

    def _get(attr: str, default: str = "") -> str:
        value = getattr(ds, attr, default)
        if value is None:
            return default
        return str(value)

    return {
        "study_instance_uid": _get("StudyInstanceUID"),
        "patient_id": _get("PatientID"),
        "study_date": _get("StudyDate"),
        "study_description": _get("StudyDescription"),
        "modalities_in_study": _get("ModalitiesInStudy"),
        "accession_number": _get("AccessionNumber"),
        "series_count": _get("NumberOfStudyRelatedSeries"),
        "instance_count": _get("NumberOfStudyRelatedInstances"),
    }


def serialize_move_study(study: StudyUIDHierarchy) -> dict[str, Any]:
    return {
        "study_instance_uid": study.uid,
        "patient_id": study.ptid,
        "series_count": len(study.series) if study.series else 0,
        "instance_count": study.get_number_of_instances(),
        "completed_sub_ops": study.completed_sub_ops,
        "failed_sub_ops": study.failed_sub_ops,
        "remaining_sub_ops": study.remaining_sub_ops,
        "last_error": study.last_error_msg,
    }
