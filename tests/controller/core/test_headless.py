"""Unit tests for headless project load and controller creation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.headless import create_headless_controller, load_model
from anonymizer.model.project import ProjectModel


def _write_project_json(path: Path, *, version: int | None = None) -> ProjectModel:
    model = ProjectModel()
    if version is not None:
        model.version = version
    path.write_text(model.to_json(indent=2), encoding="utf-8")  # type: ignore[attr-defined]
    return model


def test_load_model_primary_ok(tmp_path: Path) -> None:
    path = tmp_path / "ProjectModel.json"
    _write_project_json(path)
    loaded = load_model(path)
    assert isinstance(loaded, ProjectModel)
    assert loaded.version == ProjectModel.MODEL_VERSION


def test_load_model_recovers_from_bak(tmp_path: Path) -> None:
    path = tmp_path / "ProjectModel.json"
    path.write_text("{not-json", encoding="utf-8")
    bak = Path(str(path) + ".bak")
    _write_project_json(bak)
    loaded = load_model(path)
    assert isinstance(loaded, ProjectModel)
    assert loaded.version == ProjectModel.MODEL_VERSION


def test_load_model_both_corrupt_raises(tmp_path: Path) -> None:
    path = tmp_path / "ProjectModel.json"
    path.write_text("{bad", encoding="utf-8")
    Path(str(path) + ".bak").write_text("{also-bad", encoding="utf-8")
    with pytest.raises(RuntimeError, match="corrupt"):
        load_model(path)


def test_load_model_missing_bak_raises(tmp_path: Path) -> None:
    path = tmp_path / "ProjectModel.json"
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(RuntimeError, match="corrupt"):
        load_model(path)


def test_create_headless_controller_missing_path(tmp_path: Path) -> None:
    assert create_headless_controller(tmp_path / "missing.json") is None


def test_create_headless_controller_not_a_file(tmp_path: Path) -> None:
    d = tmp_path / "not_a_file"
    d.mkdir()
    assert create_headless_controller(d) is None


def test_create_headless_controller_version_upgrade_saves(tmp_path: Path) -> None:
    path = tmp_path / "ProjectModel.json"
    _write_project_json(path, version=ProjectModel.MODEL_VERSION - 1)
    fake = MagicMock(name="ProjectController")
    fake.model.version = ProjectModel.MODEL_VERSION
    with patch("anonymizer.controller.headless.ProjectController", return_value=fake) as ctor:
        controller = create_headless_controller(path)
    assert controller is fake
    ctor.assert_called_once()
    fake.save_model.assert_called_once()


def test_create_headless_controller_ctor_fail(tmp_path: Path) -> None:
    path = tmp_path / "ProjectModel.json"
    _write_project_json(path)
    with patch(
        "anonymizer.controller.headless.ProjectController",
        side_effect=RuntimeError("boom"),
    ):
        assert create_headless_controller(path) is None


def test_create_headless_controller_success(tmp_path: Path) -> None:
    path = tmp_path / "ProjectModel.json"
    _write_project_json(path)
    fake = MagicMock(name="ProjectController")
    with patch("anonymizer.controller.headless.ProjectController", return_value=fake):
        controller = create_headless_controller(path)
    assert controller is fake
    fake.save_model.assert_not_called()
