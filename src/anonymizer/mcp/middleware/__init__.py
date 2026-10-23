"""FastMCP middleware stack for the anonymizer MCP server.

Add new middleware classes here and include them in default_middleware().
"""

from fastmcp.server.middleware import Middleware as Middleware

from anonymizer.mcp.middleware.call_logging import McpCallLoggingMiddleware as McpCallLoggingMiddleware


def default_middleware() -> list[Middleware]:
    """Ordered middleware applied in create_server."""
    return [McpCallLoggingMiddleware()]
