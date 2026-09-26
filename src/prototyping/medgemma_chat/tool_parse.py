"""Extract a single MCP tool call ``{"name", "arguments"}`` from model text.

No NL/intent planner — JSON fence or bare object only. Prefers tool JSON in the
visible reply (after MedGemma thought blocks); falls back to scanning thoughts
when the model only constructed the call inside ``thought``.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
# MedGemma channel markers (decoded special tokens), e.g. <unused94>thought … <unused95>
_THOUGHT_RE = re.compile(
    r"<unused\d+>\s*thought\b.*?(?:<unused\d+>|$)",
    re.DOTALL | re.IGNORECASE,
)


def clean_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Drop null/empty optional fields so MCP schemas get clean kwargs."""
    return {k: v for k, v in arguments.items() if v is not None and v != ""}


def _as_tool_call(obj: Any) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    args = obj.get("arguments", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None
    return {"name": name.strip(), "arguments": clean_tool_arguments(args)}


def _iter_balanced_objects(text: str) -> list[str]:
    """Yield every top-level ``{...}`` substring (JSON object candidates)."""
    out: list[str] = []
    i = 0
    while i < len(text):
        start = text.find("{", i)
        if start < 0:
            break
        depth = 0
        for j, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[start : j + 1])
                    i = j + 1
                    break
        else:
            break
    return out


def _find_tool_call(text: str) -> dict[str, Any] | None:
    if not text or not text.strip():
        return None

    for match in _FENCE_RE.finditer(text):
        try:
            parsed = _as_tool_call(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
        if parsed is not None:
            return parsed

    # Prefer a tool call that includes "name"; skip incidental JSON in prose.
    for chunk in _iter_balanced_objects(text):
        try:
            parsed = _as_tool_call(json.loads(chunk))
        except json.JSONDecodeError:
            continue
        if parsed is not None:
            return parsed
    return None


def parse_tool_call(reply: str) -> dict[str, Any] | None:
    """Return ``{"name", "arguments"}`` or ``None`` if the reply is prose / invalid."""
    raw = reply or ""
    visible = _THOUGHT_RE.sub(" ", raw).strip()
    found = _find_tool_call(visible)
    if found is not None:
        return found
    # 4-bit / small models often leave the only valid call inside thought.
    return _find_tool_call(raw)


def needs_tool_nudge(reply: str) -> bool:
    """True when the model started a tool turn but never emitted usable JSON."""
    if parse_tool_call(reply) is not None:
        return False
    text = reply or ""
    if _THOUGHT_RE.search(text):
        return True
    if "```json" in text or '{"name"' in text or '{"name":' in text:
        return True
    return False


_TOOL_NUDGE = (
    "Stop. Reply with only one JSON tool call now — no thought, no prose. "
    'Examples: {"name":"list_inventory","arguments":{}} or '
    '{"name":"export_series_preview","arguments":{"patient":"1","series":"1"}}.'
)
