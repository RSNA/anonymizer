"""FastMCP middleware stack for the anonymizer MCP server.

Add new middleware classes here and include them in ``default_middleware()``.
"""

from __future__ import annotations

from fastmcp.server.middleware import Middleware

from anonymizer.mcp.middleware.call_logging import McpCallLoggingMiddleware

__all__ = [
    "McpCallLoggingMiddleware",
    "default_middleware",
]


def default_middleware() -> list[Middleware]:
    """Ordered middleware applied in ``create_server``."""
    return [McpCallLoggingMiddleware()]
