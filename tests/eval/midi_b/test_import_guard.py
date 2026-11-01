"""eval.midi_b must stay subprocess-isolated from product and prototyping packages."""

from __future__ import annotations

import ast
from pathlib import Path

_EVAL_ROOT = Path(__file__).resolve().parents[3] / "src" / "eval"
_FORBIDDEN_ROOTS = ("anonymizer", "prototyping")


def _module_roots(node: ast.AST) -> list[str]:
    roots: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            roots.append(alias.name.split(".", 1)[0])
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            roots.append(node.module.split(".", 1)[0])
    return roots


def test_eval_package_does_not_import_anonymizer_or_prototyping() -> None:
    offenders: list[str] = []
    for path in _EVAL_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for root in _module_roots(node):
                if root in _FORBIDDEN_ROOTS:
                    offenders.append(f"{path.relative_to(_EVAL_ROOT.parent.parent)}: {root}")
    assert offenders == [], "forbidden imports:\n" + "\n".join(offenders)
