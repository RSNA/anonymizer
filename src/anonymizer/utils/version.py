import importlib.metadata
from pathlib import Path

import toml


def _version_from_pyproject(pyproject_path: Path) -> str:
    pyproject_data = toml.load(pyproject_path)
    project = pyproject_data.get("project")
    if isinstance(project, dict) and project.get("version"):
        return str(project["version"])
    poetry = pyproject_data.get("tool", {}).get("poetry")
    if isinstance(poetry, dict) and poetry.get("version"):
        return str(poetry["version"])
    raise KeyError("No project version found in pyproject.toml")


def get_version() -> str:
    try:
        return importlib.metadata.version("rsna-anonymizer")
    except importlib.metadata.PackageNotFoundError as import_error:
        pyproject_path = (
            Path(__file__).resolve().parent.parent.parent.parent / "pyproject.toml"
        )
        if not pyproject_path.exists():
            raise FileNotFoundError("pyproject.toml not found") from import_error
        return _version_from_pyproject(pyproject_path)
