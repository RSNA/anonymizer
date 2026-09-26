"""JSON Schema helpers for MCP ``inputSchema`` (from Pydantic models)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def mcp_input_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Build a flat MCP ``inputSchema`` from a Pydantic model.

    - ``additionalProperties: false`` (strict args)
    - ``$ref`` / ``$defs`` inlined so small LLM clients need not resolve refs
    - model ``title`` stripped (tool name is authoritative)
    """
    raw = model.model_json_schema(mode="validation")
    schema = _inline_defs(deepcopy(raw))
    schema.pop("title", None)
    schema.pop("$defs", None)
    schema.pop("definitions", None)
    schema["type"] = "object"
    schema.setdefault("properties", {})
    schema["additionalProperties"] = False
    return schema


def _inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs") or schema.get("definitions") or {}
    return _resolve(schema, defs)


def _resolve(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.rsplit("/", 1)[-1]
            target = defs.get(name)
            if isinstance(target, dict):
                merged = {k: v for k, v in node.items() if k != "$ref"}
                base = _resolve(deepcopy(target), defs)
                if isinstance(base, dict):
                    # Prefer local description/default over def title noise.
                    out = {**base, **merged}
                    out.pop("title", None)
                    return out
        return {k: _resolve(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, defs) for v in node]
    return node


def schema_fields_markdown(model: type[BaseModel]) -> str:
    """Human-readable argument list for initialize instructions / prompts."""
    schema = mcp_input_schema(model)
    props: dict[str, Any] = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    if not props:
        return "- _(none — pass_ `{}` _only)_"
    lines: list[str] = []
    for name, prop in props.items():
        typ = _type_label(prop)
        if name in required:
            flag = "required"
        elif "default" in prop:
            flag = f"optional, default {prop['default']!r}"
        else:
            flag = "optional"
        desc = (prop.get("description") or "").strip()
        lines.append(f"- `{name}` ({typ}, {flag}): {desc}")
    return "\n".join(lines)


def _type_label(prop: dict[str, Any]) -> str:
    if "enum" in prop:
        return "enum " + "|".join(str(x) for x in prop["enum"])
    if "anyOf" in prop or "oneOf" in prop:
        return "union"
    t = prop.get("type")
    if t == "array":
        items = prop.get("items") or {}
        return f"array[{_type_label(items)}]" if items else "array"
    if isinstance(t, list):
        return "|".join(str(x) for x in t)
    return str(t or "object")
