"""``python -m prototyping.medgemma_chat --model /path/to/weights``."""

from __future__ import annotations

import asyncio
import sys

from prototyping.medgemma_chat.cli import build_parser, configure_logging, run_repl
from prototyping.medgemma_chat.mcp_client import McpConnectionError, load_mcp_config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(verbose=args.verbose)
    mcp_url = load_mcp_config(mcp_url=args.mcp_url, mcp_config=args.mcp_config)

    if args.ui == "gradio":
        from prototyping.medgemma_chat.gradio_app import launch_gradio

        try:
            launch_gradio(
                mcp_url=mcp_url,
                model_dir=args.model,
                device=args.device,
                max_tokens=args.max_tokens,
                verbose=args.verbose,
                host=args.host,
                port=args.port,
            )
        except McpConnectionError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    try:
        return asyncio.run(run_repl(args))
    except McpConnectionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
