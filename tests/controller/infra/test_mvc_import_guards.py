"""Guard MVC layering and top-level anonymizer imports."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src" / "anonymizer"
_CONTROLLER_ROOT = _SRC_ROOT / "controller"
_UTILS_ROOT = _SRC_ROOT / "utils"

_TOUCHED_CONTROLLER_MODULES = frozenset(
    {
        _CONTROLLER_ROOT / "ai" / "tseg" / "seg_retention.py",
        _CONTROLLER_ROOT / "ai" / "remove_pixel_phi.py",
    }
)

# seg_retention ↔ blur_face.pipeline ↔ segment cycle; only allowed mid-function import.
_ALLOWED_LAZY_MODULES_BY_FILE: dict[Path, frozenset[str]] = {
    _CONTROLLER_ROOT / "ai" / "tseg" / "seg_retention.py": frozenset(
        {"anonymizer.controller.ai.blur_face.pipeline"}
    ),
}


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
    return found


def _function_body_anonymizer_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Imports of anonymizer.* that appear inside functions/methods (not TYPE_CHECKING)."""
    offenders: list[tuple[int, str]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._in_type_checking = 0
            self._fn_depth = 0

        def visit_If(self, node: ast.If) -> None:
            is_type_checking = isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
            if is_type_checking:
                self._in_type_checking += 1
            self.generic_visit(node)
            if is_type_checking:
                self._in_type_checking -= 1

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._fn_depth += 1
            self.generic_visit(node)
            self._fn_depth -= 1

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._fn_depth += 1
            self.generic_visit(node)
            self._fn_depth -= 1

        def visit_Import(self, node: ast.Import) -> None:
            if self._fn_depth and not self._in_type_checking:
                for alias in node.names:
                    if alias.name.startswith("anonymizer"):
                        offenders.append((node.lineno, alias.name))
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if self._fn_depth and not self._in_type_checking and node.module:
                if node.module.startswith("anonymizer"):
                    offenders.append((node.lineno, node.module))
            self.generic_visit(node)

    Visitor().visit(tree)
    return offenders


def test_controller_does_not_import_view() -> None:
    offenders: list[str] = []
    for path in _iter_python_files(_CONTROLLER_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, module in _imported_modules(tree):
            if module == "anonymizer.view" or module.startswith("anonymizer.view."):
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {module}")
    assert offenders == []


def test_utils_does_not_import_controller_or_view() -> None:
    offenders: list[str] = []
    for path in _iter_python_files(_UTILS_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, module in _imported_modules(tree):
            if module.startswith("anonymizer.controller") or module.startswith("anonymizer.view"):
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {module}")
    assert offenders == []


def test_utils_has_no_function_body_anonymizer_imports() -> None:
    offenders: list[str] = []
    for path in _iter_python_files(_UTILS_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, module in _function_body_anonymizer_imports(tree):
            rel = path.relative_to(_REPO_ROOT)
            offenders.append(f"{rel}:{lineno}: {module}")
    assert offenders == []


def test_touched_controller_modules_top_level_imports() -> None:
    offenders: list[str] = []
    for path in sorted(_TOUCHED_CONTROLLER_MODULES):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        allowed = _ALLOWED_LAZY_MODULES_BY_FILE.get(path, frozenset())
        for lineno, module in _function_body_anonymizer_imports(tree):
            if module in allowed:
                continue
            rel = path.relative_to(_REPO_ROOT)
            offenders.append(f"{rel}:{lineno}: {module}")
    assert offenders == []
