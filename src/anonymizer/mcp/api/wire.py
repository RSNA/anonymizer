"""MCP wire format: dict handlers → ``ToolResult`` (plain text; images as ImageContent).

Unit tests call handlers directly and get dicts. Registration wraps via ``as_plain_tool``.
``output_schema`` stays unset so clients get free-text / image content, not structuredContent.
"""

from __future__ import annotations

import inspect
import json
from functools import wraps
from typing import Any


def _slim_project(proj: Any) -> Any:
    if not isinstance(proj, dict):
        return proj
    keep = ("project_name", "modalities", "site_id", "totals", "imported_modalities")
    return {k: proj[k] for k in keep if k in proj}


def wire_text(result: Any) -> str:
    """Flatten a tool dict into plain text for MCP clients.

    ``list_inventory`` becomes TSV only (no ``series`` / ``inventory`` JSON arrays).
    Preview success omits ``preview_base64`` (image is sent as MCP ``ImageContent``).
    Other successes are one-line compact JSON without pretty-print nesting.
    """
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return str(result)
    if result.get("ok") is False:
        return f"error: {result.get('error') or 'failed'}"

    table = result.get("table")
    if isinstance(table, str) and table.lstrip().startswith("patient_index"):
        count = result.get("count")
        prefix = f"count={count}\n" if count is not None else ""
        return f"{prefix}{table}"

    slim = {k: v for k, v in result.items() if k != "ok"}
    if "project" in slim:
        slim["project"] = _slim_project(slim["project"])
    if isinstance(slim.get("table"), str) and "series" in slim:
        slim.pop("series", None)
    # Image bytes travel as ImageContent; keep a small text summary for the model.
    if isinstance(slim.get("preview_base64"), str):
        slim.pop("preview_base64", None)
        slim["image"] = "attached"
    return json.dumps({"ok": True, **slim}, ensure_ascii=False, separators=(",", ":"), default=str)


def parse_wire_text(text: str) -> dict[str, Any]:
    """Inverse of ``wire_text`` for clients/tests (TSV inventory → series rows)."""
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "error": "empty tool result"}
    if raw.startswith("error:"):
        return {"ok": False, "error": raw[len("error:") :].strip()}

    lines = [ln for ln in raw.splitlines() if ln.strip()]
    count: int | None = None
    if lines and lines[0].startswith("count="):
        try:
            count = int(lines[0].split("=", 1)[1].strip())
        except ValueError:
            count = None
        lines = lines[1:]
    if lines and lines[0].startswith("patient_index"):
        header = lines[0].split("\t")
        series: list[dict[str, Any]] = []
        for ln in lines[1:]:
            cols = ln.split("\t")
            row: dict[str, Any] = {}
            for key, val in zip(header, cols, strict=False):
                if key in {
                    "patient_index",
                    "study_index",
                    "series_index",
                    "row_index",
                    "instance_count",
                }:
                    try:
                        row[key] = int(val)
                    except ValueError:
                        row[key] = val
                elif key in {"study_harmonized", "series_harmonized", "pixel_phi_scanned"}:
                    row[key] = val in {"Y", "y", "1", "true", "True"}
                else:
                    row[key] = val
            series.append(row)
        table = "\n".join(lines)
        return {
            "ok": True,
            "count": count if count is not None else len(series),
            "series": series,
            "table": table,
        }

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": True, "text": raw}
    if isinstance(data, dict):
        if "ok" not in data:
            data = {"ok": True, **data}
        return data
    return {"ok": True, "data": data}


def as_plain_tool(fn: Any) -> Any:
    """Wrap a dict-returning handler as MCP ``ToolResult`` (text + optional image)."""
    from fastmcp.tools import ToolResult
    from mcp.types import ImageContent, TextContent

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
        result = fn(*args, **kwargs)
        content: list[Any] = [TextContent(type="text", text=wire_text(result))]
        if (
            isinstance(result, dict)
            and result.get("ok")
            and isinstance(result.get("preview_base64"), str)
            and result["preview_base64"]
        ):
            mime = str(result.get("mime_type") or "image/png")
            content.append(
                ImageContent(
                    type="image",
                    data=result["preview_base64"],
                    mimeType=mime,
                )
            )
        return ToolResult(content=content)

    sig = inspect.signature(fn)
    wrapper.__signature__ = sig.replace(return_annotation=ToolResult)  # type: ignore[attr-defined]
    anns = dict(getattr(fn, "__annotations__", {}))
    anns["return"] = ToolResult
    wrapper.__annotations__ = anns
    return wrapper
