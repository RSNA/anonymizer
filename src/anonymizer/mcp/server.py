"""stdio / HTTP MCP server bootstrap for RSNA Anonymizer (FastMCP).

``create_server`` wires:
  - ``middleware.default_middleware()`` — request/response logging
  - ``api.register_tools`` — tool contract from ``api.catalog.TOOL_CATALOG``
  - ``instructions.load_server_instructions()`` — initialize howto
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from anonymizer.mcp import __version__
from anonymizer.mcp.api import register_tools
from anonymizer.mcp.instructions import load_server_instructions
from anonymizer.mcp.middleware import default_middleware
from anonymizer.mcp.session import SESSION
from anonymizer.utils.logging import init_logging
from anonymizer.utils.translate import set_language_code

logger = logging.getLogger(__name__)

MCP_HTTP_PATH = "/mcp"


def _preserve_logging_across_uvicorn() -> None:
    """Keep ``init_logging`` handlers when FastMCP starts uvicorn."""
    import uvicorn

    if getattr(uvicorn.Config.__init__, "_anonymizer_mcp_log_patch", False):
        return
    _orig = uvicorn.Config.__init__

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["log_config"] = None
        return _orig(self, *args, **kwargs)

    _init._anonymizer_mcp_log_patch = True  # type: ignore[attr-defined]
    uvicorn.Config.__init__ = _init  # type: ignore[method-assign]


def create_server() -> FastMCP:
    """Build FastMCP server from middleware + API tool definitions."""
    set_language_code("en_US")
    server = FastMCP(
        name="rsna-anonymizer",
        version=__version__,
        instructions=load_server_instructions(),
        middleware=default_middleware(),
    )
    register_tools(server)
    return server


def run_MCP(
    *,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = MCP_HTTP_PATH,
    init_logs: bool = False,
) -> None:
    """Run the MCP server (stdio or HTTP). Projects are opened via tools."""
    logs_dir = init_logging() if init_logs else None

    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    _preserve_logging_across_uvicorn()

    server = create_server()
    logger.info(
        "MCP server ready (FastMCP)%s",
        f"; logs_dir={logs_dir}" if logs_dir else "",
    )

    transport_l = (transport or "stdio").lower()

    try:
        if transport_l == "stdio":
            server.run(transport="stdio", show_banner=False)
            return
        if transport_l == "http":
            logger.info("HTTP MCP on http://%s:%s%s", host, port, path)
            server.run(
                transport="http",
                host=host,
                port=port,
                path=path,
                show_banner=False,
            )
            return
        raise ValueError(f"Unsupported MCP transport: {transport!r}")
    except KeyboardInterrupt:
        logger.info("MCP server stopped")
        raise SystemExit(130) from None
    finally:
        SESSION.close()
