"""Guard against AI feature wrapper / View re-export regressions."""

from __future__ import annotations

import ast
from pathlib import Path

import anonymizer.controller.ai.tseg.config as tseg_config
import anonymizer.view.ai.features as features_pkg
import anonymizer.view.ai.features.availability as features_availability

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTROLLER_ROOT = _REPO_ROOT / "src" / "anonymizer" / "controller"
_MODEL_ROOT = _REPO_ROOT / "src" / "anonymizer" / "model"

_FORBIDDEN_CONFIG_NAMES = frozenset({"SEGMENTATION_MODE"})

_FORBIDDEN_FEATURES_PKG_EXPORTS = frozenset(
    {
        "segmentation_mode_display",
        "segmentation_mode_menu_values",
        "default_installed_segmentation_mode",
        "installed_segmentation_mode_menu_values",
        "harmonize_allowed",
        "pixel_phi_allowed",
        "face_blur_allowed",
    }
)

_MOVED_GATE_NAMES = frozenset(
    {
        "pixel_phi_allowed",
        "harmonize_allowed",
        "harmonize_allowed_for_modality",
        "face_blur_allowed",
        "brain_structures_allowed",
        "any_ai_batch_feature_allowed",
        "remove_pixel_phi_has_models",
        "harmonize_has_models",
        "harmonize_ct_has_models",
        "harmonize_mr_has_models",
        "brain_structures_has_models",
        "face_blur_has_models",
        "face_ct_has_models",
        "face_mr_has_models",
        "remove_pixel_phi_needs_download",
        "harmonize_ct_needs_download",
        "harmonize_mr_needs_download",
        "brain_structures_needs_download",
        "face_blur_needs_license",
        "face_ct_needs_download",
        "face_mr_needs_download",
    }
)


def test_tseg_config_does_not_define_segmentation_mode_alias() -> None:
    for name in _FORBIDDEN_CONFIG_NAMES:
        assert not hasattr(tseg_config, name), f"tseg.config must not define {name}"


def test_features_package_does_not_reexport_controller_symbols() -> None:
    for name in _FORBIDDEN_FEATURES_PKG_EXPORTS:
        assert not hasattr(features_pkg, name), f"view.ai.features must not expose {name}"


def test_view_availability_does_not_define_moved_gates() -> None:
    for name in _MOVED_GATE_NAMES:
        assert not hasattr(features_availability, name), (
            f"view.ai.features.availability must not define {name} (lives in controller)"
        )


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _imported_gate_names_from_view_availability(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "anonymizer.view.ai.features.availability":
            continue
        for alias in node.names:
            if alias.name in _MOVED_GATE_NAMES:
                names.add(alias.name)
    return names


def test_controller_and_model_do_not_import_gates_from_view_availability() -> None:
    offenders: list[str] = []
    for root in (_CONTROLLER_ROOT, _MODEL_ROOT):
        for path in _iter_python_files(root):
            source = path.read_text(encoding="utf-8")
            imported = _imported_gate_names_from_view_availability(ast.parse(source))
            if imported:
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}: {sorted(imported)}")
    assert offenders == []
