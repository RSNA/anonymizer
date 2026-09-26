"""CLI REPL for MedGemma + Anonymizer MCP."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from prototyping.medgemma_chat import DEFAULT_MCP_URL
from prototyping.medgemma_chat.infer import (
    append_assistant,
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
    load_mcp_config,
    raise_if_mcp_unreachable,
    require_mcp,
)

logger = logging.getLogger("prototyping.medgemma_chat")


def configure_logging(*, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MedGemma chat over a running Anonymizer MCP server (streamable HTTP).",
    )
    p.add_argument(
        "--model",
        type=Path,
        required=True,
        help="Local MedGemma weights directory (HF layout)",
    )
    p.add_argument(
        "--mcp-url",
        default=None,
        help=f"Streamable HTTP MCP endpoint (default: {DEFAULT_MCP_URL} or --mcp-config)",
    )
    p.add_argument(
        "--mcp-config",
        type=Path,
        default=None,
        help="JSON file with {\"url\": \"http://.../mcp\", \"transport\": \"streamable-http\"}",
    )
    p.add_argument(
        "--device",
        choices=("auto", "mps", "cpu", "cuda"),
        default="auto",
        help="Inference device (default: auto)",
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=512,
        help="max_new_tokens per generate call (default: 512)",
    )
    p.add_argument(
        "--ui",
        choices=("repl", "gradio"),
        default="repl",
        help="Interface: repl (default) or gradio (requires uv sync --group dev)",
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Gradio bind host (default: 127.0.0.1)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=7860,
        help="Gradio bind port (default: 7860)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Show timings and raw tool JSON",
    )
    return p


async def run_repl(args: argparse.Namespace) -> int:
    configure_logging(verbose=args.verbose)
    torch_mod, AutoModel, AutoProcessor = require_ml()
    ClientSession, streamable_http_client = require_mcp()

    mcp_url = load_mcp_config(mcp_url=args.mcp_url, mcp_config=args.mcp_config)
    model_dir = Path(args.model).expanduser().resolve()
    device = resolve_device(args.device, torch_mod)
    logger.info("Loading MedGemma (device=%s)…", device)
    model, processor = load_medgemma(model_dir, device, torch_mod, AutoModel, AutoProcessor)

    logger.info("Connecting to Anonymizer MCP at %s…", mcp_url)
    try:
        async with streamable_http_client(mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                try:
                    init = await session.initialize()
                    listed = await session.list_tools()
                except BaseException as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    raise_if_mcp_unreachable(mcp_url, exc)
                    raise McpConnectionError(
                        f"Could not initialize MCP at {mcp_url}:\n{format_exc(exc)}"
                    ) from None

                tools = list(listed.tools)
                instructions = getattr(init, "instructions", None) or ""
                logger.info("MCP tools ready (%d): %s", len(tools), [t.name for t in tools])

                system = build_system_prompt(server_instructions=instructions, tools=tools)
                messages: list[dict[str, Any]] = [text_message("user", system)]
                messages.append(
                    text_message(
                        "assistant",
                        "Ready. Ask in plain language; I will use Anonymizer tools when needed.",
                    )
                )
                research_ctx = ChatContext()

                print(
                    "\nReady. Ask about projects, imports, inventory, or PACS — or type 'exit'.\n"
                    "(Anonymizer MCP must already be running.)\n",
                    flush=True,
                )
                while True:
                    try:
                        user_text = (await asyncio.to_thread(input, "you> ")).strip()
                    except (EOFError, KeyboardInterrupt):
                        print(flush=True)
                        break
                    if not user_text:
                        continue
                    if user_text.lower() in {"exit", "quit", ":q"}:
                        break
                    try:
                        reply = await agent_turn(
                            session=session,
                            model=model,
                            processor=processor,
                            device=device,
                            torch_mod=torch_mod,
                            messages=messages,
                            user_text=user_text,
                            max_new_tokens=args.max_tokens,
                            verbose=args.verbose,
                            ctx=research_ctx,
                        )
                    except BaseException as exc:
                        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                            raise
                        if messages and messages[-1].get("role") == "user":
                            append_assistant(
                                messages,
                                "Sorry — something went wrong handling that. Please try again.",
                            )
                        try:
                            raise_if_mcp_unreachable(mcp_url, exc)
                        except McpConnectionError as conn_exc:
                            logger.info("assistant error: MCP unreachable")
                            print(f"\nassistant> {conn_exc}\n", flush=True)
                            continue
                        logger.exception("assistant error: %s", exc)
                        print(
                            f"\nassistant> Sorry — something went wrong "
                            f"({type(exc).__name__}: {exc}).\n",
                            flush=True,
                        )
                        continue
                    thumb = research_ctx.stage_preview_file()
                    if thumb is not None:
                        print(f"\n[preview] {thumb}", flush=True)
                    print(f"\nassistant> {reply}\n", flush=True)
    except McpConnectionError:
        raise
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise_if_mcp_unreachable(mcp_url, exc)
        raise

    return 0
