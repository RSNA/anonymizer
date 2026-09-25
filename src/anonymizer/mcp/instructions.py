"""Load MCP InitializeResult.instructions from ``mcp/assets`` (API only — no user manual)."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path

_ASSET_NAME = "instructions.md"


@lru_cache(maxsize=1)
def load_server_instructions() -> str:
    """Return the MCP server instructions text sent on ``initialize``."""
    try:
        text = resources.files("anonymizer.mcp.assets").joinpath(_ASSET_NAME).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, TypeError, AttributeError):
        path = Path(__file__).resolve().parent / "assets" / _ASSET_NAME
        if not path.is_file():
            raise FileNotFoundError(f"MCP instructions asset missing: {path}") from None
        text = path.read_text(encoding="utf-8")
    return text.strip() + "\n"
