"""Packaged default anonymizer script path.

Public API
----------
packaged_default_script_path(*, require_exists) -> Path
    Relative path to the shipped default .script; optionally require the file.
"""

from pathlib import Path

from anonymizer.model.project import ProjectModel


def packaged_default_script_path(*, require_exists: bool = False) -> Path:
    """
    Path to the shipped default anonymizer script.

    Args:
        require_exists: When True, raise FileNotFoundError if the file is missing
            (MCP project create).

    Returns:
        The packaged default script path (install-dir relative).

    Raises:
        FileNotFoundError: When require_exists is True and the file is absent.
    """
    path = ProjectModel.default_anonymizer_script_path()
    if require_exists and not path.is_file():
        raise FileNotFoundError(f"Packaged anonymizer script missing: {path}")
    return path
