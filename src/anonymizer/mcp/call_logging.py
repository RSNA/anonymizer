"""Log every inbound MCP request (tools/call, initialize, …) for the HTTP/stdio server."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("anonymizer.mcp")

# Cap logged argument / result payloads so PHI paths stay short on the console.
_MAX_BRIEF = 400


def _brief(value: Any, *, limit: int = _MAX_BRIEF) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = repr(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _params_brief(method: str | None, params: Any) -> str:
    if params is None:
        return ""
    if isinstance(params, dict):
        if method == "tools/call" or (params.get("name") and "arguments" in params):
            name = params.get("name", "?")
            args = params.get("arguments") or {}
            return f"tool={name} args={_brief(args)}"
        return _brief(params)
    # Pydantic models from the SDK
    name = getattr(params, "name", None)
    arguments = getattr(params, "arguments", None)
    if name is not None:
        return f"tool={name} args={_brief(arguments or {})}"
    model_dump = getattr(params, "model_dump", None)
    if callable(model_dump):
        return _brief(model_dump())
    return _brief(params)


def _result_brief(result: Any) -> str:
    if result is None:
        return "ok"
    instructions = getattr(result, "instructions", None)
    if isinstance(instructions, str) and instructions.strip():
        return f"ok instructions_chars={len(instructions)}"
    is_error = getattr(result, "isError", None)
    if is_error is None:
        is_error = getattr(result, "is_error", False)
    content = getattr(result, "content", None)
    if content is not None:
        texts: list[str] = []
        for block in content or []:
            t = getattr(block, "text", None)
            if t is not None:
                texts.append(t)
        joined = "\n".join(texts) if texts else ""
        try:
            data = json.loads(joined) if joined else None
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            if data.get("ok") is False:
                return f"error={_brief(data.get('error'))}"
            if data.get("ok") is True:
                if "preview_base64" in data or data.get("byte_length") is not None:
                    mime = data.get("mime_type") or "?"
                    nbytes = data.get("byte_length")
                    b64 = data.get("preview_base64")
                    b64_chars = len(b64) if isinstance(b64, str) else 0
                    wh = ""
                    if data.get("width") is not None and data.get("height") is not None:
                        wh = f" {data['width']}x{data['height']}"
                    return (
                        f"ok preview mime={mime} bytes={nbytes} "
                        f"b64_chars={b64_chars}{wh}"
                    )
                keys = [k for k in data if k != "ok"]
                return f"ok keys={keys}"
        status = "error" if is_error else "ok"
        return f"{status} {_brief(joined, limit=200)}"
    tools = getattr(result, "tools", None)
    if tools is not None:
        return f"ok tools={len(tools)}"
    return "ok"


def _instructions_from_initialize_result(result: Any) -> str | None:
    """Return server instructions text when ``result`` is an InitializeResult."""
    text = getattr(result, "instructions", None)
    if isinstance(text, str) and text.strip():
        return text
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        try:
            data = model_dump()
        except Exception:
            data = None
        if isinstance(data, dict):
            maybe = data.get("instructions")
            if isinstance(maybe, str) and maybe.strip():
                return maybe
    return None


def _tools_list_payload(result: Any) -> list[dict[str, Any]] | None:
    """Serialize ``tools/list`` payload as the LLM sees it (name, description, inputSchema)."""
    tools = getattr(result, "tools", None)
    if tools is None:
        return None
    out: list[dict[str, Any]] = []
    for tool in tools:
        if hasattr(tool, "model_dump"):
            raw = tool.model_dump(by_alias=True, exclude_none=True)
            entry = {
                "name": raw.get("name"),
                "description": raw.get("description"),
                "inputSchema": raw.get("inputSchema") or raw.get("input_schema"),
            }
        else:
            entry = {
                "name": getattr(tool, "name", None),
                "description": getattr(tool, "description", None),
                "inputSchema": getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None),
            }
        out.append(entry)
    return out


class McpCallLoggingMiddleware:
    """ServerMiddleware: log method, args, duration, and outcome for every MCP call."""

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        method = getattr(ctx, "method", None) or "?"
        params = getattr(ctx, "params", None)
        t0 = time.perf_counter()
        logger.info("MCP ← %s %s", method, _params_brief(method, params))
        try:
            result = await call_next(ctx)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.info("MCP → %s failed %.3fs: %s: %s", method, elapsed, type(exc).__name__, exc)
            raise
        elapsed = time.perf_counter() - t0
        logger.info("MCP → %s %s (%.3fs)", method, _result_brief(result), elapsed)
        if method == "initialize":
            instructions = _instructions_from_initialize_result(result)
            if instructions:
                logger.info(
                    "MCP → initialize instructions returned to client (%d chars):\n%s",
                    len(instructions),
                    instructions,
                )
            else:
                logger.info("MCP → initialize returned no instructions field")
        elif method == "tools/list":
            payload = _tools_list_payload(result)
            if payload is not None:
                body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
                logger.info(
                    "MCP → tools/list returned to client (%d tools, %d chars):\n%s",
                    len(payload),
                    len(body),
                    body,
                )
            else:
                logger.info("MCP → tools/list returned no tools field")
        return result
