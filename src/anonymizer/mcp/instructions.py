"""Load MCP InitializeResult.instructions (behavior rules + generated Tool API)."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path

from anonymizer.mcp.api.catalog import render_tools_api_markdown

_ASSET_NAME = "instructions.md"


def _read_behavior_asset() -> str:
    """Load ``assets/instructions.md`` (behavior rules only)."""
    try:
        return resources.files("anonymizer.mcp.assets").joinpath(_ASSET_NAME).read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, ModuleNotFoundError, TypeError, AttributeError):
        path = Path(__file__).resolve().parent / "assets" / _ASSET_NAME
        if not path.is_file():
            raise FileNotFoundError(f"MCP instructions asset missing: {path}") from None
        return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_behavior_instructions() -> str:
    """Return behavior rules only (no generated Tool API appendix)."""
    return _read_behavior_asset().strip() + "\n"


@lru_cache(maxsize=1)
def load_server_instructions() -> str:
    """Return initialize instructions: behavior asset + catalog Tool API."""
    return (
        load_behavior_instructions().rstrip()
        + "\n\n"
        + render_tools_api_markdown()
    ).strip() + "\n"
