"""MCP streamable-HTTP client helpers for the MedGemma chat prototype."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from prototyping.medgemma_chat import DEFAULT_MCP_URL


class McpConnectionError(RuntimeError):
    """Anonymizer MCP HTTP endpoint unreachable or failed to initialize."""


def load_mcp_config(
    *,
    mcp_url: str | None = None,
    mcp_config: Path | None = None,
) -> str:
    """Resolve streamable-HTTP MCP URL. Explicit ``mcp_url`` wins over config file."""
    if mcp_url and mcp_url.strip():
        return mcp_url.strip()
    if mcp_config is not None:
        path = mcp_config.expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"MCP config not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit(f"MCP config must be a JSON object: {path}")
        url = data.get("url")
        if not isinstance(url, str) or not url.strip():
            raise SystemExit(f"MCP config missing string 'url': {path}")
        transport = data.get("transport", "streamable-http")
        if transport not in (None, "streamable-http"):
            raise SystemExit(
                f"Unsupported transport {transport!r} in {path} "
                "(only streamable-http is supported)"
            )
        return url.strip()
    return DEFAULT_MCP_URL


def require_mcp():
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise SystemExit(
            "Missing MCP client. Install with:  uv sync --extra mcp"
        ) from exc
    return ClientSession, streamable_http_client


def _walk_exceptions(exc: BaseException) -> Iterator[BaseException]:
    """Yield ``exc`` and nested causes / ExceptionGroup members (deduped)."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        cur = stack.pop()
        cid = id(cur)
        if cid in seen:
            continue
        seen.add(cid)
        yield cur
        if isinstance(cur, BaseExceptionGroup):
            stack.extend(cur.exceptions)
        cause = getattr(cur, "__cause__", None)
        if isinstance(cause, BaseException):
            stack.append(cause)
        ctx = getattr(cur, "__context__", None)
        if isinstance(ctx, BaseException) and ctx is not cause:
            stack.append(ctx)


def is_mcp_connect_error(exc: BaseException) -> bool:
    """True for httpx/httpcore connect failures (often wrapped in ExceptionGroup)."""
    connect_names = {
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "NetworkError",
        "TimeoutException",
    }
    for err in _walk_exceptions(exc):
        if isinstance(err, (ConnectionError, TimeoutError, ConnectionRefusedError)):
            return True
        if type(err).__name__ in connect_names:
            return True
        msg = str(err).lower()
        if "connection attempts failed" in msg or "all connection attempts failed" in msg:
            return True
        if "connect call failed" in msg or "actively refused" in msg:
            return True
    return False


def mcp_unreachable_message(mcp_url: str, exc: BaseException | None = None) -> str:
    """Short user-facing message when the MCP server is down."""
    leaf = ""
    if exc is not None:
        errs = list(_walk_exceptions(exc))
        tip = next(
            (e for e in errs if type(e).__name__ in {"ConnectError", "ConnectTimeout"}),
            errs[-1] if errs else exc,
        )
        leaf = f"\n({type(tip).__name__}: {tip})"
    return (
        f"Could not connect to Anonymizer MCP at {mcp_url}.\n"
        "Start the server in another terminal, then retry:\n"
        "  uv run rsna-anonymizer --mcp 127.0.0.1:8000"
        f"{leaf}"
    )


def raise_if_mcp_unreachable(mcp_url: str, exc: BaseException) -> None:
    """Raise ``McpConnectionError`` when ``exc`` is a connect failure."""
    if is_mcp_connect_error(exc):
        raise McpConnectionError(mcp_unreachable_message(mcp_url, exc)) from None


def format_exc(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        parts = [f"{type(exc).__name__}: {exc}"]
        for i, sub in enumerate(exc.exceptions):
            parts.append(f"  [{i}] {type(sub).__name__}: {sub}")
        return "\n".join(parts)
    return f"{type(exc).__name__}: {exc}"


def format_tools_block(tools: list[Any]) -> str:
    """Full tools/list dump for the system prompt (name, description, each arg)."""
    lines: list[str] = []
    for tool in tools:
        schema = (
            getattr(tool, "parameters", None)
            or getattr(tool, "inputSchema", None)
            or getattr(tool, "input_schema", None)
            or {}
        )
        if not isinstance(schema, dict):
            schema = {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        desc = (tool.description or "").strip()
        title = getattr(getattr(tool, "annotations", None), "title", None) or ""
        header = f"### `{tool.name}`"
        if title:
            header += f" — {title}"
        lines.append(header)
        if desc:
            lines.append(desc)
        if not props:
            lines.append("arguments: {}")
        else:
            lines.append("arguments:")
            for name, prop in props.items():
                if not isinstance(prop, dict):
                    continue
                typ = prop.get("type") or (
                    "enum " + "|".join(str(x) for x in prop["enum"])
                    if "enum" in prop
                    else "object"
                )
                flag = "required" if name in required else "optional"
                if "default" in prop and name not in required:
                    flag += f", default {prop['default']!r}"
                pdesc = (prop.get("description") or "").strip()
                lines.append(f"- `{name}` ({typ}, {flag}): {pdesc}")
        lines.append("")
    return "\n".join(lines).rstrip() if lines else "(no tools)"


def tool_result_text(result: Any) -> str:
    """Plain text for the model / logs. Image bytes are never included here."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        return "TOOL ERROR:\n" + ("\n".join(parts) if parts else repr(result))
    return "\n".join(parts) if parts else repr(result)


def tool_result_payload(result: Any) -> dict[str, Any] | None:
    """Parse MCP tool result text (plain TSV inventory or compact JSON)."""
    from anonymizer.mcp.api.wire import parse_wire_text

    text = tool_result_text(result)
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("TOOL ERROR:"):
        err = raw[len("TOOL ERROR:") :].strip()
        return {"ok": False, "error": err or "tool error"}
    return parse_wire_text(text)


def build_system_prompt(*, server_instructions: str, tools: list[Any]) -> str:
    """Combine MCP initialize instructions with live tools/list (full schemas)."""
    tools_block = format_tools_block(tools)
    instr = (server_instructions or "").strip()
    return (
        f"{instr}\n\n"
        "## Available tools (live tools/list — same contract as Tool API above)\n\n"
        f"{tools_block}\n\n"
        "When you need a tool, keep any thought short, then end with exactly one JSON "
        "object and nothing else (no announce, no multi-step plan in prose):\n"
        '{"name": "<tool_name>", "arguments": {<args>}}\n'
        "list_inventory arguments are always {}. "
        "One tool per reply — wait for the tool result before another call. "
        "Do only what the user asked; never invent paths. "
        "Only after a tool result (or when no tool is needed) reply in plain language."
    )
