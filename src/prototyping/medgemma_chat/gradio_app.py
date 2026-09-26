"""Gradio UI for MedGemma + Anonymizer MCP (lazy-imports gradio)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any

from prototyping.medgemma_chat.infer import (
    TurnAborted,
    generate_text,
    load_medgemma,
    require_ml,
    resolve_device,
    text_message,
)
from prototyping.medgemma_chat.loop import ChatContext, agent_turn
from prototyping.medgemma_chat.mcp_client import (
    McpConnectionError,
    build_system_prompt,
    format_exc,
    raise_if_mcp_unreachable,
    require_mcp,
)

logger = logging.getLogger("prototyping.medgemma_chat")


def _require_gradio():
    try:
        import gradio as gr
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Gradio is required for --ui gradio. Install with:\n"
            "  uv sync --extra mcp --group medgemma-chat --group dev\n"
            f"({exc})"
        ) from exc
    return gr


class GradioSession:
    """MedGemma + MCP client state for the Gradio process."""

    def __init__(self) -> None:
        self.ready = False
        self.error: str | None = None
        self.mcp_url: str = ""
        self.model = None
        self.processor = None
        self.device = None
        self.torch_mod = None
        self.messages: list[dict[str, Any]] = []
        self.ctx = ChatContext()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session = None
        self._streams_cm = None
        self._session_cm = None
        self.max_tokens = 512
        self.verbose = False
        self._thumb_dir = Path(tempfile.mkdtemp(prefix="mcp_medgemma_chat_"))
        self.last_thumb_path: str | None = None
        self._cancel = threading.Event()
        self._current_fut: concurrent.futures.Future | None = None

    def start(
        self,
        *,
        mcp_url: str,
        model_dir: Path,
        device: str,
        max_tokens: int,
        verbose: bool,
    ) -> None:
        self.mcp_url = mcp_url
        self.max_tokens = max_tokens
        self.verbose = verbose
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        fut = asyncio.run_coroutine_threadsafe(
            self._async_start(mcp_url=mcp_url, model_dir=model_dir, device=device),
            self._loop,
        )
        try:
            fut.result()
        except McpConnectionError:
            raise
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise_if_mcp_unreachable(mcp_url, exc)
            raise

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _async_start(self, *, mcp_url: str, model_dir: Path, device: str) -> None:
        try:
            torch_mod, AutoModel, AutoProcessor = require_ml()
            ClientSession, streamable_http_client = require_mcp()
            model_dir = model_dir.expanduser().resolve()
            if not model_dir.is_dir():
                raise RuntimeError(f"Model dir not found: {model_dir}")

            resolved = resolve_device(device, torch_mod)
            logger.info("Loading MedGemma (device=%s)…", resolved)
            model, processor = load_medgemma(
                model_dir, resolved, torch_mod, AutoModel, AutoProcessor
            )
            try:
                _ = generate_text(
                    model=model,
                    processor=processor,
                    device=resolved,
                    torch_mod=torch_mod,
                    messages=[text_message("user", "Say ready.")],
                    max_new_tokens=8,
                )
            except Exception as exc:
                logger.info("warmup skipped: %s", type(exc).__name__)

            logger.info("Connecting to Anonymizer MCP at %s…", mcp_url)
            streams_cm = streamable_http_client(mcp_url)
            try:
                read, write = await streams_cm.__aenter__()
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                raise_if_mcp_unreachable(mcp_url, exc)
                raise
            session_cm = ClientSession(read, write)
            try:
                session = await session_cm.__aenter__()
                init = await session.initialize()
                listed = await session.list_tools()
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                raise_if_mcp_unreachable(mcp_url, exc)
                raise

            tools = list(listed.tools)
            instructions = getattr(init, "instructions", None) or ""

            system = build_system_prompt(server_instructions=instructions, tools=tools)
            messages: list[dict[str, Any]] = [text_message("user", system)]
            messages.append(
                text_message(
                    "assistant",
                    "Ready. Ask in plain language; I will use Anonymizer tools when needed.",
                )
            )

            self.torch_mod = torch_mod
            self.model = model
            self.processor = processor
            self.device = resolved
            self._streams_cm = streams_cm
            self._session_cm = session_cm
            self._session = session
            self.messages = messages
            self.ctx = ChatContext()
            self.ready = True
            logger.info("Gradio session ready; tools=%s", [t.name for t in tools])
        except McpConnectionError as exc:
            self.error = str(exc)
            self.ready = False
            raise
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            try:
                raise_if_mcp_unreachable(mcp_url, exc)
            except McpConnectionError as conn_exc:
                self.error = str(conn_exc)
                self.ready = False
                raise conn_exc from None
            self.error = format_exc(exc)
            self.ready = False
            raise

    def _stage_thumb(self) -> Path | None:
        dst = self.ctx.stage_preview_file(self._thumb_dir)
        if dst is not None:
            self.last_thumb_path = str(dst.resolve())
        return dst

    def abort(self) -> None:
        self._cancel.set()
        fut = self._current_fut
        if fut is not None and not fut.done():
            fut.cancel()

    def chat(self, user_text: str) -> tuple[str, str | None]:
        if not self.ready or self._loop is None or self._session is None:
            raise RuntimeError(self.error or "Session not ready")
        self._cancel.clear()
        fut = asyncio.run_coroutine_threadsafe(
            agent_turn(
                session=self._session,
                model=self.model,
                processor=self.processor,
                device=self.device,
                torch_mod=self.torch_mod,
                messages=self.messages,
                user_text=user_text,
                max_new_tokens=self.max_tokens,
                verbose=self.verbose,
                ctx=self.ctx,
                cancel_event=self._cancel,
            ),
            self._loop,
        )
        self._current_fut = fut
        try:
            reply = fut.result()
        except concurrent.futures.CancelledError as exc:
            raise TurnAborted() from exc
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise_if_mcp_unreachable(self.mcp_url or "MCP", exc)
            raise
        finally:
            self._current_fut = None
        thumb = self._stage_thumb()
        return reply, str(thumb) if thumb else None


def launch_gradio(
    *,
    mcp_url: str,
    model_dir: Path,
    device: str,
    max_tokens: int,
    verbose: bool,
    host: str,
    port: int,
) -> None:
    gr = _require_gradio()
    session = GradioSession()
    try:
        session.start(
            mcp_url=mcp_url,
            model_dir=model_dir,
            device=device,
            max_tokens=max_tokens,
            verbose=verbose,
        )
    except McpConnectionError as exc:
        raise SystemExit(str(exc)) from None

    def respond(message: str, history: list):
        if not (message or "").strip():
            return history, None
        try:
            reply, thumb = session.chat(message.strip())
        except TurnAborted:
            history = list(history or [])
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": "(cancelled)"})
            return history, None
        except McpConnectionError as exc:
            history = list(history or [])
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": str(exc)})
            return history, None
        except Exception as exc:
            history = list(history or [])
            history.append({"role": "user", "content": message})
            history.append(
                {"role": "assistant", "content": f"Error: {format_exc(exc)}"}
            )
            return history, None
        history = list(history or [])
        history.append({"role": "user", "content": message})
        content: Any = reply
        if thumb:
            content = [
                {"type": "text", "text": reply},
                {"type": "image", "image": thumb},
            ]
        history.append({"role": "assistant", "content": content})
        return history, thumb

    with gr.Blocks(title="MedGemma × Anonymizer MCP") as demo:
        gr.Markdown("# MedGemma × Anonymizer MCP")
        chatbot = gr.Chatbot(height=480, type="messages")
        preview = gr.Image(label="Last series preview", type="filepath")
        msg = gr.Textbox(label="Message", placeholder="Ask to create a project, import, list inventory…")
        with gr.Row():
            send = gr.Button("Send", variant="primary")
            stop = gr.Button("Stop")

        send.click(respond, inputs=[msg, chatbot], outputs=[chatbot, preview]).then(
            lambda: "", None, msg
        )
        msg.submit(respond, inputs=[msg, chatbot], outputs=[chatbot, preview]).then(
            lambda: "", None, msg
        )
        stop.click(lambda: session.abort(), queue=False)

    demo.queue().launch(server_name=host, server_port=port)
