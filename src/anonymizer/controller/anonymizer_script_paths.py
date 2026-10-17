"""Anonymizer script filesystem locations (shared; avoids import cycles)."""

from __future__ import annotations

from pathlib import Path


def project_anonymizer_script_path(project_model) -> Path:
    """Project script beside ``ProjectModel.json`` (config, not PHI)."""
    return Path(project_model.storage_dir) / f"{project_model.site_id}-anonymizer.script"


def private_anonymizer_script_path(project_model) -> Path:
    """Legacy name; same path as ``project_anonymizer_script_path``."""
    return project_anonymizer_script_path(project_model)
