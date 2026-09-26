"""Gate: MCP tool handlers stay thin; no private controller helpers anywhere in mcp/."""

from __future__ import annotations

from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parents[2] / "src" / "anonymizer" / "mcp"
TOOLS_ROOT = MCP_ROOT / "tools"

_BANNED_EVERYWHERE = (
    "controller.ai_batch_process import _",
    "._manage_move",
    "._apply_remove_pixel_phi",
)

# Thin tool adapters must not touch Model; session/ops may for create/open.
_BANNED_IN_TOOLS = (
    "anonymizer.model.",
    "from anonymizer.model ",
    "import anonymizer.model",
)


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.name != "__pycache__")


@pytest.mark.parametrize("path", _python_files(MCP_ROOT), ids=lambda p: str(p.relative_to(MCP_ROOT)))
def test_mcp_no_private_controller_helpers(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for banned in _BANNED_EVERYWHERE:
        assert banned not in text, f"{path.name} must not contain {banned!r}"


@pytest.mark.parametrize(
    "path",
    _python_files(TOOLS_ROOT),
    ids=lambda p: str(p.relative_to(MCP_ROOT)),
)
def test_mcp_tools_no_model_imports(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for banned in _BANNED_IN_TOOLS:
        assert banned not in text, f"{path.name} must not contain {banned!r}"
