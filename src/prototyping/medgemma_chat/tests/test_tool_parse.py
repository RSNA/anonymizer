"""Unit tests for MedGemma chat tool JSON parsing (no GPU / planner)."""

from __future__ import annotations

from prototyping.medgemma_chat.mcp_client import load_mcp_config
from prototyping.medgemma_chat.tool_parse import clean_tool_arguments, parse_tool_call


def test_parse_tool_call_from_json_fence() -> None:
    reply = (
        'Sure.\n```json\n{"name": "list_inventory", "arguments": {}}\n```\n'
    )
    call = parse_tool_call(reply)
    assert call == {"name": "list_inventory", "arguments": {}}


def test_parse_tool_call_bare_object() -> None:
    reply = '{"name": "export_series_preview", "arguments": {"patient": "1", "series": "cxr"}}'
    call = parse_tool_call(reply)
    assert call is not None
    assert call["name"] == "export_series_preview"
    assert call["arguments"] == {"patient": "1", "series": "cxr"}


def test_parse_tool_call_strips_empty_args() -> None:
    reply = (
        '{"name": "remove_pixel_phi", '
        '"arguments": {"patient": "1", "study": "", "series": "all", "extra": null}}'
    )
    call = parse_tool_call(reply)
    assert call == {
        "name": "remove_pixel_phi",
        "arguments": {"patient": "1", "series": "all"},
    }


def test_parse_tool_call_rejects_bare_tool_name() -> None:
    assert parse_tool_call("```tool\nlist_projects\n```") is None
    assert parse_tool_call("list_projects") is None
    assert parse_tool_call("I will list the inventory now.") is None


def test_parse_tool_call_rejects_missing_name() -> None:
    assert parse_tool_call('{"arguments": {}}') is None
    assert parse_tool_call('{"name": "", "arguments": {}}') is None


def test_parse_tool_call_skips_incidental_json_then_finds_tool() -> None:
    """Thought/prose may contain args-only JSON before the real tool call."""
    reply = (
        'call with arguments `{"project_name": "MCP_MVP"}`.\n'
        '{"name": "project_open", "arguments": {"project_name": "MCP_MVP"}}'
    )
    call = parse_tool_call(reply)
    assert call == {
        "name": "project_open",
        "arguments": {"project_name": "MCP_MVP"},
    }


def test_parse_tool_call_strips_medgemma_thought_block() -> None:
    reply = (
        "<unused94>thought\n"
        "The user wants to open MCP_MVP.\n"
        'I should call with {"project_name": "MCP_MVP"}.\n'
        "<unused95>"
        '{"name": "project_open", "arguments": {"project_name": "MCP_MVP"}}'
    )
    call = parse_tool_call(reply)
    assert call == {
        "name": "project_open",
        "arguments": {"project_name": "MCP_MVP"},
    }


def test_parse_tool_call_recovers_json_only_inside_thought() -> None:
    """4-bit MedGemma often builds the call in thought, then replies in prose."""
    reply = (
        "<unused94>thought\n"
        "1. Identify the tool: project_open\n"
        "2. Construct the JSON:\n"
        "```json\n"
        '{"name": "project_open", "arguments": {"project_name": "MCP_MVP"}}\n'
        "```\n"
        '4. Formulate the plain language reply: "Okay, I will open…"'
        "<unused95>"
        "Okay, I will open the project named MCP_MVP."
    )
    call = parse_tool_call(reply)
    assert call == {
        "name": "project_open",
        "arguments": {"project_name": "MCP_MVP"},
    }


def test_clean_tool_arguments() -> None:
    assert clean_tool_arguments({"a": 1, "b": "", "c": None, "d": "x"}) == {"a": 1, "d": "x"}


def test_load_mcp_config_url_wins(tmp_path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text('{"url": "http://from-file/mcp"}', encoding="utf-8")
    assert (
        load_mcp_config(mcp_url="http://explicit/mcp", mcp_config=cfg)
        == "http://explicit/mcp"
    )
    assert load_mcp_config(mcp_url=None, mcp_config=cfg) == "http://from-file/mcp"
