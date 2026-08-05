"""Tests for package version helpers."""

from __future__ import annotations

from pathlib import Path

from anonymizer.utils.version import _version_from_pyproject, find_project_pyproject, get_version


def test_get_version_matches_pyproject_exactly() -> None:
    pyproject_path = find_project_pyproject()
    assert pyproject_path is not None
    pyproject_version = _version_from_pyproject(pyproject_path)
    assert get_version() == pyproject_version


def test_find_project_pyproject_from_repo_root() -> None:
    pyproject_path = find_project_pyproject()
    assert pyproject_path is not None
    assert pyproject_path.name == "pyproject.toml"
    assert _version_from_pyproject(pyproject_path) == _version_from_pyproject(Path("pyproject.toml"))


def test_version_from_pyproject_supports_pep621_and_poetry(tmp_path: Path) -> None:
    pep621 = tmp_path / "pep621.toml"
    pep621.write_text(
        '[project]\nname = "example"\nversion = "1.2.3.dev4"\n',
        encoding="utf-8",
    )
    assert _version_from_pyproject(pep621) == "1.2.3.dev4"

    poetry = tmp_path / "poetry.toml"
    poetry.write_text(
        '[tool.poetry]\nname = "example"\nversion = "18.0.7"\n',
        encoding="utf-8",
    )
    assert _version_from_pyproject(poetry) == "18.0.7"
