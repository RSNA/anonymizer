"""CLI dispatch: -c and --mcp are mutually exclusive."""

from __future__ import annotations

from pathlib import Path

import pytest

import anonymizer.anonymizer as anon


def _kwargs(**overrides):
    base = dict(
        config=None,
        ai_batch=None,
        ai_batch_run=False,
        mcp=None,
        logs_dir=None,
    )
    base.update(overrides)
    return base


def test_parse_mcp_bind_ok() -> None:
    assert anon.parse_mcp_bind("127.0.0.1:8000") == ("127.0.0.1", 8000)


def test_parse_mcp_bind_rejects_bad() -> None:
    with pytest.raises(ValueError):
        anon.parse_mcp_bind("8000")
    with pytest.raises(ValueError):
        anon.parse_mcp_bind("host:0")


def test_config_and_mcp_mutually_exclusive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "ProjectModel.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(anon, "run_HEADLESS", lambda *_a, **_k: None)
    monkeypatch.setattr("anonymizer.mcp.server.run_MCP", lambda **_k: None)

    with pytest.raises(SystemExit) as exc_info:
        anon.dispatch_runtime(**_kwargs(config=config, mcp="127.0.0.1:8000"))
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info2:
        anon.dispatch_runtime(**_kwargs(config=config, mcp=""))
    assert exc_info2.value.code == 2


def test_ai_batch_run_with_mcp_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(anon, "run_HEADLESS_AI_BATCH", lambda *_a, **_k: 0)

    with pytest.raises(SystemExit) as exc_info:
        anon.dispatch_runtime(
            **_kwargs(
                config=Path("ProjectModel.json"),
                ai_batch=Path("AiBatchConfig.json"),
                ai_batch_run=True,
                mcp="",
            )
        )
    assert exc_info.value.code == 2


def test_invalid_mcp_bind_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as exc_info:
        anon.dispatch_runtime(**_kwargs(mcp="not-a-bind"))
    assert exc_info.value.code == 2


def test_bare_mcp_is_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _run_mcp(**kw):
        calls.append(f"mcp:{kw.get('transport')}")

    monkeypatch.setattr("anonymizer.mcp.server.run_MCP", _run_mcp)
    monkeypatch.setattr(anon, "run_HEADLESS", lambda *_a, **_k: calls.append("headless"))

    anon.dispatch_runtime(**_kwargs(mcp=""))
    assert calls == ["mcp:stdio"]


def test_http_mcp_is_foreground(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _run_mcp(**kw):
        calls.append(f"mcp:{kw.get('transport')}:{kw.get('host')}:{kw.get('port')}")

    monkeypatch.setattr("anonymizer.mcp.server.run_MCP", _run_mcp)
    monkeypatch.setattr(anon, "run_HEADLESS", lambda *_a, **_k: calls.append("headless"))

    anon.dispatch_runtime(**_kwargs(mcp="127.0.0.1:8000"))
    assert calls == ["mcp:http:127.0.0.1:8000"]


def test_config_alone_is_headless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "ProjectModel.json"
    config.write_text("{}", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(anon, "run_HEADLESS", lambda p: calls.append(f"headless:{p}"))
    monkeypatch.setattr("anonymizer.mcp.server.run_MCP", lambda **_k: calls.append("mcp"))

    anon.dispatch_runtime(**_kwargs(config=config))
    assert calls == [f"headless:{config}"]
