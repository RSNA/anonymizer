"""MCP LLM tool loop: generate → parse tool JSON → call_tool → repeat (no planner)."""

from __future__ import annotations

import base64
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prototyping.medgemma_chat.infer import (
    append_assistant,
    generate_text,
    multimodal_user_message,
    raise_if_cancelled,
    text_message,
)
from prototyping.medgemma_chat.mcp_client import tool_result_payload, tool_result_text
from prototyping.medgemma_chat.tool_parse import parse_tool_call

logger = logging.getLogger("prototyping.medgemma_chat")

_MAX_TOOL_ROUNDS = 8

_AFTER_TOOL = (
    "If the latest user request is done, reply in plain language and stop. "
    "Only emit another {\"name\",\"arguments\"} JSON tool call if that same "
    "request still needs it. Never invent paths or arguments the user did not give."
)

_AFTER_PREVIEW = (
    "The series preview image is attached above. Use it to answer the user's request "
    "(e.g. body part, findings). Reply in plain language and stop unless another tool "
    "is still required for that same request."
)


@dataclass
class ChatContext:
    """Optional side-channel for UIs (preview bytes for Gradio/REPL thumbs)."""

    last_preview_bytes: bytes | None = None
    last_preview_mime: str | None = None
    last_preview_caption: str = ""
    status_lines: list[str] = field(default_factory=list)
    _preview_dir: Path | None = None
    _preview_counter: int = 0

    def preview_title(self) -> str:
        return self.last_preview_caption or "series preview"

    def note(self, line: str) -> None:
        self.status_lines.append(line)

    def stage_preview_file(self, directory: Path | None = None) -> Path | None:
        """Write last preview PNG/JPEG to disk; return path or None."""
        if not self.last_preview_bytes:
            return None
        from tempfile import gettempdir

        base = directory or self._preview_dir
        if base is None:
            base = Path(gettempdir()) / "medgemma_chat_previews"
            self._preview_dir = base
        base.mkdir(parents=True, exist_ok=True)
        self._preview_counter += 1
        ext = ".jpg" if "jpeg" in (self.last_preview_mime or "") else ".png"
        slug = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in self.preview_title()
        )[:48] or "preview"
        dst = base / f"{self._preview_counter:04d}_{slug}{ext}"
        dst.write_bytes(self.last_preview_bytes)
        return dst


def _maybe_store_preview(
    ctx: ChatContext,
    name: str,
    data: dict[str, Any] | None,
    result: Any = None,
) -> bool:
    if name != "export_series_preview" or not data or not data.get("ok"):
        return False
    b64 = data.get("preview_base64")
    mime = str(data.get("mime_type") or "image/png")
    if not b64 and result is not None:
        for block in getattr(result, "content", None) or []:
            if getattr(block, "type", None) == "image" or (
                getattr(block, "data", None) and getattr(block, "mimeType", None)
            ):
                b64 = getattr(block, "data", None)
                mime = str(getattr(block, "mimeType", None) or mime)
                break
    if not isinstance(b64, str) or not b64:
        return False
    try:
        ctx.last_preview_bytes = base64.b64decode(b64)
        ctx.last_preview_mime = mime
        ctx.last_preview_caption = str(data.get("caption") or "").strip()
        return True
    except Exception:
        return False


def _preview_pil(ctx: ChatContext):
    if not ctx.last_preview_bytes:
        return None
    from io import BytesIO

    from PIL import Image

    return Image.open(BytesIO(ctx.last_preview_bytes)).convert("RGB")


def _append_tool_result_message(
    messages: list[dict[str, Any]],
    *,
    name: str,
    text: str,
    image: Any | None,
) -> None:
    body = f"Tool result for {name}:\n{text}\n\n"
    if image is not None:
        messages.append(multimodal_user_message(body + _AFTER_PREVIEW, image))
    else:
        messages.append(text_message("user", body + _AFTER_TOOL))


async def agent_turn(
    *,
    session,
    model,
    processor,
    device,
    torch_mod,
    messages: list[dict[str, Any]],
    user_text: str,
    max_new_tokens: int,
    verbose: bool = False,
    ctx: ChatContext | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    """One user turn: model may emit tool JSON; results appended as user messages."""
    if ctx is None:
        ctx = ChatContext()
    ctx.status_lines.clear()
    raise_if_cancelled(cancel_event)
    messages.append(text_message("user", user_text))

    for round_i in range(_MAX_TOOL_ROUNDS):
        raise_if_cancelled(cancel_event)
        reply = generate_text(
            model=model,
            processor=processor,
            device=device,
            torch_mod=torch_mod,
            messages=messages,
            max_new_tokens=max_new_tokens,
            cancel_event=cancel_event,
        )
        if verbose:
            logger.info("model reply[%d]: %s", round_i, reply[:500])

        call = parse_tool_call(reply)
        if call is None:
            return append_assistant(messages, reply)

        name = call["name"]
        arguments = call["arguments"]
        # Keep the tool JSON in the transcript so the model sees what it asked for.
        append_assistant(messages, json.dumps(call, ensure_ascii=False))
        args_json = json.dumps(arguments, ensure_ascii=False)
        ctx.note(f"tool → {name} {args_json}")
        logger.info("MCP_call %s arguments=%s", name, args_json)

        raise_if_cancelled(cancel_event)
        result = await session.call_tool(name, arguments)
        data = tool_result_payload(result)
        text = tool_result_text(result)
        stored_preview = _maybe_store_preview(ctx, name, data, result)
        result_preview = text if verbose else text[:500]
        logger.info("MCP_result %s %s", name, result_preview)

        image = _preview_pil(ctx) if stored_preview else None
        if image is not None:
            logger.info(
                "MCP_preview attached to multimodal turn (%s %dx%d)",
                ctx.last_preview_mime,
                image.size[0],
                image.size[1],
            )
        _append_tool_result_message(messages, name=name, text=text, image=image)

    return append_assistant(
        messages,
        "Stopped after too many tool rounds. Please rephrase or try a simpler request.",
    )
