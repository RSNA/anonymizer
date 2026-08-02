"""Tests for package version helpers."""

from __future__ import annotations

from pathlib import Path

from anonymizer.utils.version import _version_from_pyproject, get_version


def test_get_version_reads_pyproject_project_table() -> None:
    version = get_version()
    pyproject_version = _version_from_pyproject(Path("pyproject.toml"))
    assert version == pyproject_version
    assert version.startswith("19.0.0")


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
