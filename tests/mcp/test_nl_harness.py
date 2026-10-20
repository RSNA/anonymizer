"""L2 NL harness scaffold: score tool traces against scenarios (MedGemma optional).

Does not modify prototyping.medgemma_chat. When MedGemma weights / MCP server are
unavailable, tests skip. Contract validation of the scenario pack always runs.
"""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

SCENARIOS = Path(__file__).parent / "scenarios" / "mvp.yaml"
FUNCTION_SCENARIOS = Path(__file__).parent / "scenarios" / "functions.yaml"
_RUNNER = Path(__file__).parent / "run_nl_lmstudio.py"


def _load() -> list[dict]:
    return yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_nl_lmstudio", _RUNNER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_nl_scenarios_define_ask_or_tools():
    cases = _load()
    assert len(cases) == 10
    assert len({case["id"] for case in cases}) == 10
    for case in cases:
        trace = case.get("expected_trace") or []
        assert trace, case["id"]
        for step in trace:
            assert "tool" in step or step.get("ask") is True, case["id"]
    # The pack sticks to project creation / settings modification.
    tools_used = {
        step["tool"]
        for case in cases
        for step in (case.get("expected_trace") or [])
        if step.get("tool")
    }
    assert tools_used <= {"create_project", "update_project_settings", "project_info"}


def test_nl_packs_cover_every_catalog_tool():
    """mvp.yaml (creation/settings) + functions.yaml cover the whole catalog."""
    from anonymizer.mcp.api.catalog import MCP_TOOL_NAMES

    covered: set[str] = set()
    for path in (SCENARIOS, FUNCTION_SCENARIOS):
        cases = yaml.safe_load(path.read_text(encoding="utf-8"))["scenarios"]
        assert len({case["id"] for case in cases}) == len(cases), path.name
        for case in cases:
            for step in case.get("expected_trace") or []:
                assert "tool" in step or step.get("ask") is True, case["id"]
                if step.get("tool"):
                    covered.add(step["tool"])
    assert covered == set(MCP_TOOL_NAMES)


def test_nl_runner_qwen_helpers(monkeypatch):
    mod = _load_runner()
    unload_calls: list[list[str]] = []
    monkeypatch.setattr(
        mod.subprocess, "run", lambda args, **_kw: unload_calls.append(list(args))
    )
    mod._unload_model_from_lm_studio("qwen3-8b-mlx")
    assert unload_calls == [["lms", "unload", "qwen3-8b-mlx"]]
    assert mod._is_qwen_model("qwen3-8b-mlx") is True
    assert mod._is_qwen_model("medgemma-1.5-4b-it") is False
    assert mod._is_medgemma_model("medgemma-1.5-4b-it@4bit") is True
    assert mod._is_medgemma_model("qwen3-14b-mlx") is False
    # Processing uses a per-run system temporary directory, like the pytest
    # project tests. The MCP child's synthetic HOME and its application log
    # stay below that processing directory, not in a report directory.
    processing_dir = mod._create_processing_dir()
    try:
        assert processing_dir.parent == Path(tempfile.gettempdir())
        run_home = mod._run_home(processing_dir)
        assert run_home == processing_dir / "home"
        assert mod._application_log_path(run_home) == (
            processing_dir
            / "home"
            / "Documents"
            / "RSNA Anonymizer"
            / "logs"
            / "anonymizer.log"
        )
    finally:
        shutil.rmtree(processing_dir, ignore_errors=True)
    assert '"name"' in mod._user_turn_suffix("medgemma-1.5-4b-it@4bit")
    assert mod._parse_tool_arguments("{}") == {}
    assert mod._parse_tool_arguments('{"ip":"10.0.0.5"}') == {"ip": "10.0.0.5"}
    # Nested settings match by value (key order / int-vs-float irrelevant).
    assert mod._args_match(
        {"network_timeouts": {"network": 300}, "scp": {"aet": "NEWLOCAL"}},
        {"scp": {"aet": "NEWLOCAL", "port": 11112}, "network_timeouts": {"network": 300.0}},
    )
    assert not mod._args_match(
        {"modalities": ["CT", "MR"]}, {"modalities": ["MR", "CT"]}
    )
    case = {
        "expected_trace": [
            {
                "tool": "create_project",
                "before_clarify": True,
                "arguments": {"project_name": "X", "confirm": False},
            },
            {
                "tool": "create_project",
                "after_clarify": True,
                "arguments": {"project_name": "X", "confirm": True, "revision": 1},
            },
        ]
    }
    assert mod._expected_tools_satisfied(case, []) is False
    assert (
        mod._expected_tools_satisfied(
            case,
            [
                {
                    "name": "create_project",
                    "_result_status": "confirmation_required",
                    "arguments": {"project_name": "X", "confirm": False},
                }
            ],
        )
        is False
    )
    assert (
        mod._expected_tools_satisfied(
            case,
            [
                {
                    "name": "create_project",
                    "_result_status": "confirmation_required",
                    "arguments": {"project_name": "X", "confirm": False},
                },
                {
                    "name": "create_project",
                    "_after_clarify": True,
                    "_result_status": "created",
                    "arguments": {"project_name": "X", "confirm": True, "revision": 1},
                },
            ],
        )
        is True
    )


def test_nl_medgemma_optional_import():
    """Import medgemma_chat if present; skip otherwise (no prototyping edits)."""
    pytest.importorskip("transformers")
    try:
        from prototyping.medgemma_chat.tool_parse import parse_tool_call  # noqa: F401
    except ImportError:
        pytest.skip("prototyping.medgemma_chat not importable")


@pytest.mark.mcp_e2e
def test_nl_live_medgemma_trace_placeholder():
    """Opt-in live NL scoring — requires MCP server + MedGemma weights (manual)."""
    pytest.skip(
        "Live NL scoring is manual: start rsna-anonymizer --mcp, run "
        "tests/mcp/run_nl_lmstudio.py against scenarios/mvp.yaml."
    )
