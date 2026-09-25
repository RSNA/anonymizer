"""stdio / HTTP MCP server bootstrap for RSNA Anonymizer."""

from __future__ import annotations

import logging
from pathlib import Path

from anonymizer.mcp import __version__
from anonymizer.mcp.call_logging import McpCallLoggingMiddleware
from anonymizer.mcp.instructions import load_server_instructions
from anonymizer.mcp.session import SESSION
from anonymizer.mcp.tools import register_mcp_tools
from anonymizer.utils.logging import init_logging
from anonymizer.utils.translate import set_language_code

logger = logging.getLogger(__name__)


def _preserve_logging_across_uvicorn() -> None:
    """Keep ``init_logging`` handlers when MCPServer starts uvicorn."""
    import uvicorn

    if getattr(uvicorn.Config.__init__, "_anonymizer_mcp_log_patch", False):
        return
    _orig = uvicorn.Config.__init__

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["log_config"] = None
        return _orig(self, *args, **kwargs)

    _init._anonymizer_mcp_log_patch = True  # type: ignore[attr-defined]
    uvicorn.Config.__init__ = _init  # type: ignore[method-assign]


def _require_mcp():
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "The MCP optional dependency is not installed. "
            "Install with: uv sync --extra mcp   or   pip install 'rsna-anonymizer[mcp]'"
        ) from exc
    return MCPServer


def create_server():
    """Build MCPServer; tool API is ``anonymizer.mcp.tools`` (typed signatures + handlers)."""
    set_language_code("en_US")
    MCPServer = _require_mcp()
    server = MCPServer(
        name="rsna-anonymizer",
        version=__version__,
        instructions=load_server_instructions(),
        middleware=[McpCallLoggingMiddleware()],
    )
    register_mcp_tools(server)
    return server


def run_MCP(
    *,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
    project_config: Path | None = None,
    init_logs: bool = False,
) -> None:
    logs_dir = init_logging() if init_logs else None

    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    _preserve_logging_across_uvicorn()

    if project_config is not None:
        try:
            SESSION.open_path(Path(project_config))
            logger.info("Pre-opened project from -c/--config: %s", project_config)
        except Exception as exc:
            logger.error("Failed to pre-open project %s: %s", project_config, exc)
            raise SystemExit(1) from exc

    server = create_server()
    logger.info(
        "MCP server ready (headless ProjectController via create_headless_controller)%s",
        f"; logs_dir={logs_dir}" if logs_dir else "",
    )
    try:
        if transport == "stdio":
            server.run(transport="stdio")
        elif transport == "sse":
            server.run(transport="sse", host=host, port=port)
        else:
            logger.info("Streamable HTTP MCP on http://%s:%s%s", host, port, path)
            server.run(
                transport="streamable-http",
                host=host,
                port=port,
                streamable_http_path=path,
            )
    except KeyboardInterrupt:
        logger.info("MCP server stopped")
        raise SystemExit(130) from None
    finally:
        SESSION.close()
