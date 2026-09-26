"""Log every inbound MCP request (tools/call, initialize, tools/list, …).

Installed via ``middleware.default_middleware()``. Logs full outbound
``initialize`` instructions and ``tools/list`` API definitions.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastmcp.server.middleware import Middleware

logger = logging.getLogger("anonymizer.mcp")

# Cap for args / tool-call briefs only — never truncate instructions or tools/list.
_MAX_BRIEF = 400
_MAX_TOOL_CALL_LOG = 8_000


def _brief(value: Any, *, limit: int = _MAX_BRIEF) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = repr(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _as_result_dict(result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict):
        return result
    model_dump = getattr(result, "model_dump", None)
    if not callable(model_dump):
        return None
    try:
        data = model_dump(by_alias=True, exclude_none=True)
    except TypeError:
        try:
            data = model_dump()
        except Exception:
            return None
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _params_brief(method: str | None, params: Any) -> str:
    if params is None:
        return ""
    if isinstance(params, dict):
        if method == "tools/call" or (params.get("name") and "arguments" in params):
            return f"tool={params.get('name', '?')} args={_brief(params.get('arguments') or {})}"
        return _brief(params)
    name = getattr(params, "name", None)
    if name is not None:
        return f"tool={name} args={_brief(getattr(params, 'arguments', None) or {})}"
    model_dump = getattr(params, "model_dump", None)
    if callable(model_dump):
        return _brief(model_dump())
    return _brief(params)


def _content_texts(result: Any) -> str | None:
    data = _as_result_dict(result)
    blocks = None
    if data is not None:
        blocks = data.get("content")
    if blocks is None:
        blocks = getattr(result, "content", None)
    if not isinstance(blocks, list) or not blocks:
        return None
    texts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("text") is not None:
            texts.append(str(block["text"]))
        else:
            t = getattr(block, "text", None)
            if t is not None:
                texts.append(str(t))
    return "\n".join(texts) if texts else None


def _result_brief(result: Any) -> str:
    if result is None:
        return "ok"
    instructions = _instructions_from_result(result)
    if instructions:
        return f"ok instructions_chars={len(instructions)}"
    data = _as_result_dict(result)
    if data is not None:
        tools = data.get("tools")
        if isinstance(tools, list):
            return f"ok tools={len(tools)}"
    tools = getattr(result, "tools", None)
    if tools is not None:
        return f"ok tools={len(tools)}"
    text = _content_texts(result)
    if text is not None:
        return f"ok {_brief(text, limit=200)}"
    if data is not None:
        return f"ok keys={list(data.keys())}" if data else "ok"
    return "ok"


def _instructions_from_result(result: Any) -> str | None:
    data = _as_result_dict(result)
    if data is not None:
        text = data.get("instructions")
        if isinstance(text, str) and text.strip():
            return text
    text = getattr(result, "instructions", None)
    if isinstance(text, str) and text.strip():
        return text
    return None


def _tools_list_payload(result: Any) -> list[dict[str, Any]] | None:
    data = _as_result_dict(result)
    tools: Any = None
    if data is not None:
        tools = data.get("tools")
    if tools is None:
        tools = getattr(result, "tools", None)
    if tools is None and isinstance(result, list):
        tools = result
    if tools is None:
        return None
    out: list[dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, dict):
            schema = (
                tool.get("inputSchema")
                or tool.get("input_schema")
                or tool.get("parameters")
            )
            entry = {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "inputSchema": schema,
            }
        else:
            schema = (
                getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None)
                or getattr(tool, "parameters", None)
            )
            if schema is None and hasattr(tool, "model_dump"):
                raw = tool.model_dump(by_alias=True, exclude_none=True)
                schema = raw.get("inputSchema") or raw.get("input_schema") or raw.get("parameters")
                entry = {
                    "name": raw.get("name"),
                    "description": raw.get("description"),
                    "inputSchema": schema,
                }
            else:
                entry = {
                    "name": getattr(tool, "name", None),
                    "description": getattr(tool, "description", None),
                    "inputSchema": schema,
                }
        out.append(entry)
    return out


def _log_full(label: str, body: str, *, extra: str = "", level: int = logging.INFO) -> None:
    suffix = f" {extra}" if extra else ""
    logger.log(
        level,
        "MCP → %s returned to client (%d chars)%s:\n%s",
        label,
        len(body),
        suffix,
        body,
    )


class McpCallLoggingMiddleware(Middleware):
    """Log inbound MCP calls and full outbound instructions / tool API definitions."""

    async def on_message(self, context: Any, call_next: Any) -> Any:
        method = getattr(context, "method", None) or "?"
        params = getattr(context, "message", None)
        t0 = time.perf_counter()
        logger.info("MCP ← %s %s", method, _params_brief(method, params))
        try:
            result = await call_next(context)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.info(
                "MCP → %s failed %.3fs: %s: %s",
                method,
                elapsed,
                type(exc).__name__,
                exc,
            )
            raise
        elapsed = time.perf_counter() - t0
        logger.info("MCP → %s %s (%.3fs)", method, _result_brief(result), elapsed)

        if method == "initialize":
            data = _as_result_dict(result) or {}
            instructions = _instructions_from_result(result)
            envelope = {
                k: data[k]
                for k in ("protocolVersion", "capabilities", "serverInfo")
                if k in data
            }
            if envelope:
                _log_full(
                    "initialize serverInfo/capabilities",
                    json.dumps(envelope, ensure_ascii=False, indent=2, default=str),
                )
            if instructions:
                _log_full("initialize instructions", instructions)
            else:
                logger.info(
                    "MCP → initialize wire keys=%s (no instructions)",
                    list(data.keys()) if data else type(result).__name__,
                )
        elif method == "tools/list":
            payload = _tools_list_payload(result)
            if payload is not None:
                body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
                names = [str(t.get("name") or "?") for t in payload]
                _log_full(
                    "tools/list API definitions",
                    body,
                    extra=f"tools={len(payload)} names={names}",
                    level=logging.DEBUG,
                )
        elif method == "tools/call":
            text = _content_texts(result)
            if text is not None:
                if "preview_base64" in text or len(text) > _MAX_TOOL_CALL_LOG:
                    text = _brief(text, limit=_MAX_TOOL_CALL_LOG)
                _log_full("tools/call", text)

        return result
