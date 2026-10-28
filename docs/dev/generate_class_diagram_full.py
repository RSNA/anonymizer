#!/usr/bin/env python3
"""Regenerate repo-root class_diagram_full.md from real anonymizer imports.

Strict MVC edges only: view/mcp → controller → model (and view/mcp → model).
Same-layer and utils edges are omitted.

Usage (from repo root):
  python3 docs/dev/generate_class_diagram_full.py
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "src" / "anonymizer"
OUT = REPO / "class_diagram_full.md"

STRICT = {
    ("view", "controller"),
    ("mcp", "controller"),
    ("controller", "model"),
    ("view", "model"),
    ("mcp", "model"),
}


def _modules() -> dict[str, Path]:
    pkgs: dict[str, Path] = {}
    for path in ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or "assets" in path.parts:
            continue
        rel = path.relative_to(ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mod = ".".join(("anonymizer", *parts)) if parts else "anonymizer"
        pkgs[mod] = path
    return pkgs


def _resolve(name: str, modules: set[str]) -> str | None:
    if name in modules:
        return name
    parts = name.split(".")
    while len(parts) > 1:
        parts.pop()
        cand = ".".join(parts)
        if cand in modules:
            return cand
    return None


def _layer(mod: str) -> str:
    rest = mod[len("anonymizer.") :] if mod.startswith("anonymizer.") else mod
    if rest == "anonymizer" or rest == "view" or rest.startswith("view."):
        return "view"
    if rest == "mcp" or rest.startswith("mcp."):
        return "mcp"
    if rest.startswith("controller"):
        return "controller"
    if rest.startswith("model"):
        return "model"
    if rest.startswith("utils"):
        return "utils"
    return "other"


def _short_name(mod: str) -> str:
    rest = mod[len("anonymizer.") :] if mod.startswith("anonymizer.") else mod
    if rest == "anonymizer":
        return "anonymizer"
    for prefix in ("view.", "controller.", "model.", "mcp."):
        if rest.startswith(prefix):
            return rest[len(prefix) :]
    if rest in {"view", "controller", "model", "mcp"}:
        return rest
    return rest


def _nid(mod: str) -> str:
    layer = _layer(mod)[0].upper()
    short = _short_name(mod).replace(".", "_").replace("-", "_")
    return f"{layer}_{short}"


def _label(mod: str, classes_by_mod: dict[str, list[str]]) -> str:
    name = _short_name(mod)
    classes = classes_by_mod.get(mod, [])
    shown = classes[:8]
    extra = len(classes) - len(shown)
    lines = [f"<b>{name}</b>", *shown]
    if extra > 0:
        lines.append(f"+{extra} more")
    if not classes:
        lines.append("‹module›")
    return "<br/>".join(lines)


def main() -> None:
    pkgs = _modules()
    modules = set(pkgs)
    classes_by_mod: dict[str, list[str]] = defaultdict(list)
    edges: set[tuple[str, str]] = set()

    for mod, path in pkgs.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                classes_by_mod[mod].append(node.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("anonymizer"):
                tgt = _resolve(node.module, modules)
                if tgt and tgt != mod:
                    edges.add((mod, tgt))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith("anonymizer"):
                        continue
                    tgt = _resolve(alias.name, modules)
                    if tgt and tgt != mod:
                        edges.add((mod, tgt))

    strict_edges = sorted((a, b) for a, b in edges if (_layer(a), _layer(b)) in STRICT)
    involved: set[str] = set()
    for a, b in strict_edges:
        involved.add(a)
        involved.add(b)

    nodes_by_layer: dict[str, list[str]] = defaultdict(list)
    for mod in sorted(involved):
        nodes_by_layer[_layer(mod)].append(mod)

    body: list[str] = [
        "flowchart TB",
        '    subgraph CLIENTS[" "]',
        "        direction LR",
        "",
        '        subgraph VIEW["VIEW"]',
        "            direction TB",
    ]
    view_mods = nodes_by_layer.get("view", [])
    for mod in view_mods:
        body.append(f'            {_nid(mod)}["{_label(mod, classes_by_mod)}"]')
    for left, right in zip(view_mods, view_mods[1:]):
        body.append(f"            {_nid(left)} ~~~ {_nid(right)}")
    body.extend(
        [
            "        end",
            "",
            '        subgraph MCP["MCP"]',
            "            direction TB",
        ]
    )
    mcp_mods = nodes_by_layer.get("mcp", [])
    for mod in mcp_mods:
        body.append(f'            {_nid(mod)}["{_label(mod, classes_by_mod)}"]')
    for left, right in zip(mcp_mods, mcp_mods[1:]):
        body.append(f"            {_nid(left)} ~~~ {_nid(right)}")
    body.extend(
        [
            "        end",
            "    end",
            "",
            '    subgraph CONTROLLER["CONTROLLER"]',
            "        direction TB",
        ]
    )
    ctrl_mods = nodes_by_layer.get("controller", [])
    for mod in ctrl_mods:
        body.append(f'            {_nid(mod)}["{_label(mod, classes_by_mod)}"]')
    for left, right in zip(ctrl_mods, ctrl_mods[1:]):
        body.append(f"            {_nid(left)} ~~~ {_nid(right)}")
    body.extend(
        [
            "    end",
            "",
            '    subgraph MODEL["MODEL"]',
            "        direction TB",
        ]
    )
    model_mods = nodes_by_layer.get("model", [])
    for mod in model_mods:
        body.append(f'            {_nid(mod)}["{_label(mod, classes_by_mod)}"]')
    for left, right in zip(model_mods, model_mods[1:]):
        body.append(f"            {_nid(left)} ~~~ {_nid(right)}")
    body.extend(["    end", "", "    %% Strict MVC import edges (A imports B)"])
    for a, b in strict_edges:
        body.append(f"    {_nid(a)} --> {_nid(b)}")

    counts = Counter((_layer(a), _layer(b)) for a, b in strict_edges)
    legend_rows = [
        (("view", "controller"), "GUI View imports Controller"),
        (("mcp", "controller"), "MCP imports Controller"),
        (("controller", "model"), "Controller imports Model"),
        (("view", "model"), "View imports Model (Settings / create paths)"),
        (("mcp", "model"), "MCP imports Model (project open/create)"),
    ]

    doc = "\n".join(
        [
            "# Full MVC class diagram (V19)",
            "",
            "Generated from real `anonymizer.*` imports. **Strict MVC edges only**:",
            "View → Controller, MCP → Controller, Controller → Model,",
            "plus View/MCP → Model where those imports exist.",
            "Same-layer and `utils` edges are omitted. Overview: [`class_diagram.md`](class_diagram.md).",
            "",
            "Arrow `A --> B` means **A imports B**.",
            "",
            f"- Modules shown: **{len(involved)}**",
            f"- Strict cross-layer edges: **{len(strict_edges)}**",
            "",
            "```mermaid",
            *body,
            "```",
            "",
            "## Edge legend",
            "",
            "| Direction | Meaning | Count |",
            "| --- | --- | ---: |",
            *[
                f"| {key[0]} → {key[1]} | {meaning} | {counts.get(key, 0)} |"
                for key, meaning in legend_rows
            ],
            "",
            "## Notes",
            "",
            "- Module labels drop the layer prefix (`view.`, `controller.`, …); the subgraph is the layer.",
            "- Public classes are listed (up to 8 per module). Private `_` classes omitted.",
            "- Same-layer wiring is omitted here; see the overview diagram.",
            "- Regenerate: `python3 docs/dev/generate_class_diagram_full.py`",
            "",
        ]
    )
    OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} nodes={len(involved)} edges={len(strict_edges)}")


if __name__ == "__main__":
    main()
