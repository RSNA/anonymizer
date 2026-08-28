"""Tests for TotalSegmentator path-based readiness (no cached weight state)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from anonymizer.controller.ai.tseg.readiness import (
    TsWeightKind,
    anatomy_ct_ready,
    anatomy_mr_ready,
    brain_structures_ready,
    checkpoint_ready,
    download_segmentation_model,
    face_ct_ready,
    face_mr_ready,
    log_runtime_status,
    totalsegmentator_available,
    verify_face_license,
    weight_kind_ready,
)


def test_totalsegmentator_available_ignores_cwd_shadow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken totalsegmentator/ tree in cwd must not hide the venv package."""
    shadow = tmp_path / "totalsegmentator"
    shadow.mkdir()
    (shadow / "__init__.py").write_text('raise ImportError("broken cwd stub")\n', encoding="utf-8")

    pkg_root = tmp_path / "site-packages"
    pkg_root.mkdir()
    real_pkg = pkg_root / "totalsegmentator"
    real_pkg.mkdir()
    (real_pkg / "__init__.py").write_text('__version__ = "2.17.0"\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", ["", str(pkg_root), *sys.path[1:]])
    for name in list(sys.modules):
        if name == "totalsegmentator" or name.startswith("totalsegmentator."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    import importlib.metadata as md

    monkeypatch.setattr(
        md,
        "version",
        lambda name: "2.17.0" if name == "totalsegmentator" else (_ for _ in ()).throw(md.PackageNotFoundError(name)),
    )

    assert totalsegmentator_available() is True
    module = importlib.import_module("totalsegmentator")
    assert str(real_pkg) in module.__file__.replace("\\", "/")


def test_totalsegmentator_available_false_without_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as md

    def _missing(_name: str) -> str:
        raise md.PackageNotFoundError("totalsegmentator")

    monkeypatch.setattr(md, "version", _missing)
    assert totalsegmentator_available() is False


def test_checkpoint_ready_fold_and_root(tmp_path: Path) -> None:
    fold_model = tmp_path / "fold_model"
    (fold_model / "fold_0").mkdir(parents=True)
    (fold_model / "fold_0" / "checkpoint_final.pth").write_bytes(b"x")
    assert checkpoint_ready(fold_model) is True

    root_model = tmp_path / "root_model"
    root_model.mkdir()
    (root_model / "checkpoint_final.pth").write_bytes(b"x")
    assert checkpoint_ready(root_model) is True

    empty = tmp_path / "empty"
    empty.mkdir()
    assert checkpoint_ready(empty) is False
    assert checkpoint_ready(None) is False


def test_anatomy_ct_ready_when_all_task_checkpoints_exist(tmp_path: Path) -> None:
    model_folder = tmp_path / "model"
    model_folder.mkdir()
    (model_folder / "checkpoint_final.pth").write_bytes(b"x")

    with (
        patch("anonymizer.controller.ai.tseg.readiness.totalsegmentator_available", return_value=True),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.ct_anatomy_task_ids_for_mode",
            return_value=(297, 298),
        ),
        patch("anonymizer.controller.ai.tseg.config.ENABLE_TS_CONTRAST", False),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.resolve_harmonize_model_folder",
            return_value=model_folder,
        ),
    ):
        assert anatomy_ct_ready("3mm") is True


def test_anatomy_ct_ready_false_when_any_checkpoint_missing(tmp_path: Path) -> None:
    present = tmp_path / "present"
    present.mkdir()
    (present / "checkpoint_final.pth").write_bytes(b"x")
    missing = tmp_path / "missing"
    missing.mkdir()

    def _resolve(task_id: int) -> Path:
        return present if task_id == 297 else missing

    with (
        patch("anonymizer.controller.ai.tseg.readiness.totalsegmentator_available", return_value=True),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.ct_anatomy_task_ids_for_mode",
            return_value=(297, 298),
        ),
        patch("anonymizer.controller.ai.tseg.config.ENABLE_TS_CONTRAST", False),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.resolve_harmonize_model_folder",
            side_effect=_resolve,
        ),
    ):
        assert anatomy_ct_ready("3mm") is False


def test_anatomy_mr_and_face_ready_use_path_checks(tmp_path: Path) -> None:
    model_folder = tmp_path / "model"
    (model_folder / "fold_0").mkdir(parents=True)
    (model_folder / "fold_0" / "checkpoint_final.pth").write_bytes(b"x")

    with (
        patch("anonymizer.controller.ai.tseg.readiness.totalsegmentator_available", return_value=True),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.mr_anatomy_task_ids_for_mode",
            return_value=(852,),
        ),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.resolve_harmonize_model_folder",
            return_value=model_folder,
        ),
        patch("anonymizer.controller.ai.tseg.model_cache.face_task_ids", return_value=(303,)),
        patch("anonymizer.controller.ai.tseg.model_cache.mr_face_task_ids", return_value=(856,)),
        patch(
            "anonymizer.controller.ai.tseg.readiness.resolve_model_folder",
            return_value=model_folder,
        ),
    ):
        assert anatomy_mr_ready("3mm") is True
        assert face_ct_ready() is True
        assert face_mr_ready() is True
        assert weight_kind_ready(TsWeightKind.FACE) is True


def test_brain_structures_ready(tmp_path: Path) -> None:
    model_folder = tmp_path / "brain"
    model_folder.mkdir()
    (model_folder / "checkpoint_final.pth").write_bytes(b"x")

    with (
        patch("anonymizer.controller.ai.tseg.readiness.totalsegmentator_available", return_value=True),
        patch(
            "anonymizer.controller.ai.tseg.readiness.resolve_model_folder",
            return_value=model_folder,
        ),
    ):
        assert brain_structures_ready() is True
        assert weight_kind_ready(TsWeightKind.BRAIN_STRUCTURES) is True


def test_ready_false_without_totalsegmentator() -> None:
    with patch("anonymizer.controller.ai.tseg.readiness.totalsegmentator_available", return_value=False):
        assert anatomy_ct_ready("3mm") is False
        assert anatomy_mr_ready("3mm") is False
        assert face_ct_ready() is False
        assert face_mr_ready() is False
        assert brain_structures_ready() is False


def test_download_segmentation_model_skips_when_ready() -> None:
    with (
        patch("anonymizer.controller.ai.tseg.readiness.weight_kind_ready", return_value=True),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.download_segmentation_model_weights"
        ) as mock_download,
    ):
        assert download_segmentation_model(TsWeightKind.ANATOMY) is True
        mock_download.assert_not_called()


def test_download_segmentation_model_runs_and_rechecks() -> None:
    with (
        patch("anonymizer.controller.ai.tseg.readiness.weight_kind_ready", side_effect=[False, True]),
        patch("anonymizer.controller.ai.tseg.readiness.totalsegmentator_available", return_value=True),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.download_segmentation_model_weights"
        ) as mock_download,
    ):
        assert download_segmentation_model(TsWeightKind.FACE) is True
        mock_download.assert_called_once_with(TsWeightKind.FACE)


def test_verify_face_license_without_package() -> None:
    with patch("anonymizer.controller.ai.tseg.readiness.totalsegmentator_available", return_value=False):
        ok, detail = verify_face_license()
    assert ok is False
    assert "not installed" in detail.lower()


def test_log_runtime_status_does_not_raise() -> None:
    with (
        patch("anonymizer.controller.ai.tseg.readiness.totalsegmentator_available", return_value=True),
        patch("anonymizer.controller.ai.tseg.readiness.xgboost_available", return_value=True),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.installed_ct_segmentation_modes",
            return_value=(),
        ),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.installed_mr_segmentation_modes",
            return_value=(),
        ),
        patch("anonymizer.controller.ai.tseg.readiness.face_ct_ready", return_value=False),
        patch("anonymizer.controller.ai.tseg.readiness.face_mr_ready", return_value=False),
        patch("anonymizer.controller.ai.tseg.readiness.brain_structures_ready", return_value=False),
        patch("anonymizer.controller.ai.tseg.readiness.face_license_available", return_value=False),
    ):
        log_runtime_status()


def test_project_ai_gates_use_ready_checks() -> None:
    from anonymizer.view.ai.features.availability import face_blur_allowed, harmonize_allowed

    with (
        patch("anonymizer.view.ai.features.availability.totalsegmentator_available", return_value=True),
        patch("anonymizer.view.ai.features.availability.xgboost_available", return_value=True),
        patch(
            "anonymizer.view.ai.features.availability.installed_ct_segmentation_modes",
            return_value=("3mm",),
        ),
        patch(
            "anonymizer.view.ai.features.availability.installed_mr_segmentation_modes",
            return_value=(),
        ),
        patch("anonymizer.view.ai.features.availability.face_ct_ready", return_value=True),
        patch("anonymizer.view.ai.features.availability.face_mr_ready", return_value=False),
        patch("anonymizer.view.ai.features.availability.face_license_available", return_value=True),
    ):
        assert harmonize_allowed() is True
        assert face_blur_allowed() is True
    with (
        patch("anonymizer.view.ai.features.availability.totalsegmentator_available", return_value=True),
        patch("anonymizer.view.ai.features.availability.xgboost_available", return_value=True),
        patch(
            "anonymizer.view.ai.features.availability.installed_ct_segmentation_modes",
            return_value=(),
        ),
        patch(
            "anonymizer.view.ai.features.availability.installed_mr_segmentation_modes",
            return_value=(),
        ),
        patch("anonymizer.view.ai.features.availability.face_ct_ready", return_value=False),
        patch("anonymizer.view.ai.features.availability.face_mr_ready", return_value=False),
        patch("anonymizer.view.ai.features.availability.face_license_available", return_value=True),
    ):
        assert harmonize_allowed() is False
        assert face_blur_allowed() is False
