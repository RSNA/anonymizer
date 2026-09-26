"""Load MCP InitializeResult.instructions (behavior rules + generated Tool API)."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path

_ASSET_NAME = "instructions.md"


@lru_cache(maxsize=1)
def load_server_instructions() -> str:
    """Return initialize instructions: behavior asset + catalog Tool API."""
    try:
        text = resources.files("anonymizer.mcp.assets").joinpath(_ASSET_NAME).read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, ModuleNotFoundError, TypeError, AttributeError):
        path = Path(__file__).resolve().parent / "assets" / _ASSET_NAME
        if not path.is_file():
            raise FileNotFoundError(f"MCP instructions asset missing: {path}") from None
        text = path.read_text(encoding="utf-8")

    from anonymizer.mcp.api.catalog import render_tools_api_markdown

    return (text.strip() + "\n\n" + render_tools_api_markdown()).strip() + "\n"
