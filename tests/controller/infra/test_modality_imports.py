"""Guard against modality predicate wrappers reappearing on modality_profile."""

from __future__ import annotations

import ast
from pathlib import Path

import anonymizer.controller.ai.tseg.modality_profile as modality_profile

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTROLLER_ROOT = _REPO_ROOT / "src" / "anonymizer" / "controller"
_MODEL_ROOT = _REPO_ROOT / "src" / "anonymizer" / "model"

_FORBIDDEN_MODALITY_PROFILE_NAMES = frozenset(
    {
        "is_tseg_modality",
        "series_is_tseg_eligible",
        "is_ct_modality",
        "is_mr_modality",
        "default_ct_profile",
    }
)

_FORBIDDEN_PREDICATE_IMPORTS = frozenset(
    {
        "is_tseg_modality",
        "series_is_tseg_eligible",
        "is_ct_modality",
        "is_mr_modality",
        "normalize_modality",
    }
)


def test_modality_profile_does_not_define_predicate_wrappers() -> None:
    for name in _FORBIDDEN_MODALITY_PROFILE_NAMES:
        assert not hasattr(modality_profile, name), f"modality_profile must not define {name}"


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _imported_names_from_modality_profile(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "anonymizer.controller.ai.tseg.modality_profile":
            continue
        for alias in node.names:
            if alias.name in _FORBIDDEN_PREDICATE_IMPORTS:
                names.add(alias.name)
    return names


def test_controller_and_model_do_not_import_predicates_from_modality_profile() -> None:
    offenders: list[str] = []
    for root in (_CONTROLLER_ROOT, _MODEL_ROOT):
        for path in _iter_python_files(root):
            source = path.read_text(encoding="utf-8")
            imported = _imported_names_from_modality_profile(ast.parse(source))
            if imported:
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}: {sorted(imported)}")
    assert offenders == []
