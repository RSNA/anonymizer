import importlib.metadata
from pathlib import Path

import toml

_PACKAGE_NAME = "rsna-anonymizer"


def _version_from_pyproject(pyproject_path: Path) -> str:
    pyproject_data = toml.load(pyproject_path)
    project = pyproject_data.get("project")
    if isinstance(project, dict) and project.get("version"):
        return str(project["version"])
    poetry = pyproject_data.get("tool", {}).get("poetry")
    if isinstance(poetry, dict) and poetry.get("version"):
        return str(poetry["version"])
    raise KeyError("No project version found in pyproject.toml")


def _pyproject_names_package(pyproject_path: Path) -> bool:
    pyproject_data = toml.load(pyproject_path)
    project = pyproject_data.get("project")
    if isinstance(project, dict) and project.get("name") == _PACKAGE_NAME:
        return True
    poetry = pyproject_data.get("tool", {}).get("poetry")
    return isinstance(poetry, dict) and poetry.get("name") == _PACKAGE_NAME


def find_project_pyproject() -> Path | None:
    """Return ``pyproject.toml`` for this repo when running from a source checkout."""
    path = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = path / "pyproject.toml"
        if candidate.is_file() and _pyproject_names_package(candidate):
            return candidate
        if path.parent == path:
            break
        path = path.parent
    return None


def get_version() -> str:
    """
    Return the package version.

    Prefer ``pyproject.toml`` when this package is loaded from a source checkout
    so log lines, window titles, and CLI help match the repo version exactly.
    Fall back to installed distribution metadata for PyPI wheel installs.
    """
    pyproject_path = find_project_pyproject()
    if pyproject_path is not None:
        return _version_from_pyproject(pyproject_path)
    try:
        return importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError as import_error:
        raise FileNotFoundError(f"{_PACKAGE_NAME} is not installed and pyproject.toml was not found") from import_error
