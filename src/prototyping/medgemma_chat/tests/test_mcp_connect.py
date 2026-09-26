"""Tests for MCP connect-error detection (ExceptionGroup / httpx)."""

from __future__ import annotations

from prototyping.medgemma_chat.mcp_client import (
    McpConnectionError,
    is_mcp_connect_error,
    mcp_unreachable_message,
    raise_if_mcp_unreachable,
)


def test_is_mcp_connect_error_unwraps_exception_group() -> None:
    leaf = ConnectionRefusedError("All connection attempts failed")
    group = ExceptionGroup("unhandled errors in a TaskGroup", [leaf])
    assert is_mcp_connect_error(group) is True


def test_is_mcp_connect_error_connect_error_by_name() -> None:
    class ConnectError(Exception):
        pass

    assert is_mcp_connect_error(ConnectError("All connection attempts failed")) is True
    assert is_mcp_connect_error(ValueError("nope")) is False


def test_raise_if_mcp_unreachable() -> None:
    try:
        raise_if_mcp_unreachable(
            "http://127.0.0.1:8000/mcp",
            ExceptionGroup("tg", [ConnectionError("All connection attempts failed")]),
        )
    except McpConnectionError as exc:
        msg = str(exc)
        assert "Could not connect to Anonymizer MCP" in msg
        assert "rsna-anonymizer --mcp" in msg
        assert "http://127.0.0.1:8000/mcp" in msg
    else:
        raise AssertionError("expected McpConnectionError")


def test_mcp_unreachable_message_without_exc() -> None:
    msg = mcp_unreachable_message("http://127.0.0.1:8000/mcp")
    assert "http://127.0.0.1:8000/mcp" in msg
    assert "rsna-anonymizer --mcp" in msg
