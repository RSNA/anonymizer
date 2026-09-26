"""MCP package for headless RSNA Anonymizer.

Modules
-------
``server``
    FastMCP bootstrap (``create_server`` / ``run_MCP``).
``middleware``
    FastMCP middleware stack (call logging).
``api.catalog``
    Authoritative tool list: descriptions, MCP annotations, Pydantic models.
``api.schemas`` / ``api.schema_json``
    Args models + flat ``inputSchema`` for ``tools/list``.
``api.handlers`` / ``api.wire``
    Implementations and plain-text tool results.
``ops`` / ``session`` / ``snapshots``
    Domain operations behind the API.
``instructions``
    Initialize howto = behavior asset + generated Tool API from the catalog.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
