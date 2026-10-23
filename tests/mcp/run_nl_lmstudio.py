#!/usr/bin/env python3
"""L2 NL scenario runner: LM Studio OpenAI API + Anonymizer MCP HTTP.

Manual developer verification only — do not add this runner to CI. See
``tests/mcp/README.md`` for the current reference model and scenario packs.

Default model is Qwen3-14B MLX (``qwen3-14b-mlx``, trainedForToolUse). Uses LMS
native ``tools`` / ``tool_calls`` (OpenAI-compat) with thinking disabled for
Qwen3. Falls back to parsing JSON / ``<tool_call>`` text for non-tool models.

Prereqs::

    lms server start -p 1234
    lms unload --all
    lms load qwen3-14b-mlx -c 8192 -y

  uv run python tests/mcp/run_nl_lmstudio.py --model qwen3-14b-mlx

All project processing uses a per-run temporary directory, like the
pytest project tests: created projects, the spawned MCP child's synthetic
``HOME``, its default project store, and its application log are removed
when the run exits. ``--out-dir`` is an optional report directory for
``nl_scenario_results.json`` and (for spawned MCP) ``mcp_server.log`` only;
it is never used for project processing. When ``--out-dir`` is omitted,
reports are written to a separate temporary report directory.
"""

import argparse
import asyncio
import atexit
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _load_wait_for_mcp_tcp():
    path = _HERE / "http_ready.py"
    spec = importlib.util.spec_from_file_location("mcp_http_ready", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.wait_for_mcp_tcp


wait_for_mcp_tcp = _load_wait_for_mcp_tcp()


def _create_processing_dir() -> Path:
    """Create the per-run temporary directory used for all processing.

    Mirrors the pytest project tests' temporary-directory pattern: project
    files, imported data, and the spawned MCP child's ``Documents/RSNA
    Anonymizer`` store stay under the system temporary directory and are
    removed when this runner process exits.

    Returns:
        Path: Newly created temporary processing directory.
    """
    processing_dir = Path(tempfile.mkdtemp(prefix="anonymizer-nl-processing-"))
    atexit.register(shutil.rmtree, processing_dir, ignore_errors=True)
    return processing_dir


def _run_home(processing_dir: Path) -> Path:
    """Synthetic HOME for the spawned MCP subprocess.

    Keeping this under the per-run processing directory separates the
    subprocess's normal ``Documents/RSNA Anonymizer`` store/logs from the
    runner's report directory.

    Args:
        processing_dir: Per-run temporary processing directory.

    Returns:
        Path: Synthetic HOME directory for the MCP subprocess.
    """
    return processing_dir / "home"


def _application_log_path(run_home: Path) -> Path:
    """Anonymizer rotating log written under the MCP subprocess HOME."""
    return (
        run_home
        / "Documents"
        / "RSNA Anonymizer"
        / "logs"
        / "anonymizer.log"
    )


def _stop_mcp_process(proc: subprocess.Popen) -> None:
    """Stop an MCP subprocess spawned by this runner.

    Args:
        proc: MCP subprocess to stop with SIGINT, then kill if needed.
    """
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _unload_model_from_lm_studio(model: str) -> None:
    """Unload a model from LM Studio, warning instead of failing the run.

    Args:
        model: LM Studio model identifier to unload.
    """
    try:
        subprocess.run(["lms", "unload", model], check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Warning: could not unload LM Studio model {model!r}: {exc}", flush=True)


SCENARIOS_DEFAULT = _HERE / "scenarios" / "mvp.yaml"
DAVIDSON_DCM = next(
    (
        REPO
        / "tests"
        / "controller"
        / "assets"
        / "test_dcm_files"
        / "davidson_cxr"
    ).glob("*.dcm")
)
_LMS_MODELS = Path.home() / ".lmstudio" / "models"
MODEL_PATHS = {
    "medgemma-4b-it-mlx": _LMS_MODELS
    / "lmstudio-community"
    / "medgemma-4b-it-MLX-4bit",
    "medgemma-1.5-4b-it": _LMS_MODELS
    / "mlx-community"
    / "medgemma-1.5-4b-it-bf16",
    "medgemma-1.5-4b-it@4bit": _LMS_MODELS
    / "mlx-community"
    / "medgemma-1.5-4b-it-4bit",
    "medgemma-1.5-4b-it@bf16": _LMS_MODELS
    / "mlx-community"
    / "medgemma-1.5-4b-it-bf16",
    "qwen3-4b-instruct-2507-mlx": _LMS_MODELS
    / "lmstudio-community"
    / "Qwen3-4B-Instruct-2507-MLX-4bit",
    "qwen3-8b": _LMS_MODELS / "lmstudio-community" / "Qwen3-8B-MLX-4bit",
    "qwen3-8b-mlx": _LMS_MODELS / "lmstudio-community" / "Qwen3-8B-MLX-4bit",
    "qwen3-14b": _LMS_MODELS / "lmstudio-community" / "Qwen3-14B-MLX-4bit",
    "qwen3-14b-mlx": _LMS_MODELS / "lmstudio-community" / "Qwen3-14B-MLX-4bit",
}
DEFAULT_MODEL_ID = "qwen3-14b-mlx"
DEFAULT_LMS_URL = "http://127.0.0.1:1234/v1"
DEFAULT_MCP_URL = "http://127.0.0.1:8000/mcp"
MAX_TOOL_ROUNDS = 6
DEFAULT_MAX_TOKENS = 1024


def _subs(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("${DAVIDSON_DCM}", str(DAVIDSON_DCM)).replace(
            "${DAVIDSON_DIR}", str(DAVIDSON_DCM.parent)
        )
    if isinstance(value, dict):
        return {k: _subs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_subs(v) for v in value]
    return value


def _is_qwen_model(model: str) -> bool:
    """True when the LMS model id looks like a Qwen3 family checkpoint."""
    return "qwen" in (model or "").lower()


def _is_medgemma_model(model: str) -> bool:
    """True for MedGemma checkpoints (not trained for native tool calls)."""
    return "medgemma" in (model or "").lower()


def _tool_input_schema(tool: Any) -> dict[str, Any]:
    """MCP tool JSON Schema (SDK may expose ``input_schema`` or ``inputSchema``)."""
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
    return dict(schema) if isinstance(schema, dict) else {"type": "object", "properties": {}}


def _slim_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Drop Field descriptions from tool parameters to fit LMS context limits."""
    out = {k: v for k, v in schema.items() if k != "description"}
    props = schema.get("properties")
    if isinstance(props, dict):
        slim_props: dict[str, Any] = {}
        for key, val in props.items():
            if isinstance(val, dict):
                slim_props[key] = _slim_json_schema(val)
            else:
                slim_props[key] = val
        out["properties"] = slim_props
    items = schema.get("items")
    if isinstance(items, dict):
        out["items"] = _slim_json_schema(items)
    for key in ("anyOf", "oneOf", "allOf"):
        alts = schema.get(key)
        if isinstance(alts, list):
            out[key] = [
                _slim_json_schema(a) if isinstance(a, dict) else a for a in alts
            ]
    return out


def _mcp_tools_to_openai(tools: list[Any]) -> list[dict[str, Any]]:
    """Convert MCP ``list_tools`` entries to OpenAI ``tools`` payloads.

    Keeps property *names* (critical for exact args) but strips long Field text
    so Qwen3 fits in an 8k–16k context with behavior rules.
    """
    out: list[dict[str, Any]] = []
    for t in tools:
        params = _slim_json_schema(_tool_input_schema(t))
        if params.get("type") is None:
            params = {**params, "type": "object"}
        desc = (t.description or "").strip()
        # Opening only — full text lives in initialize instructions, but keep
        # refusal/gate sentences (e.g. identity fields fixed) that follow it.
        short = desc[:400]
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": short,
                    "parameters": params,
                },
            }
        )
    return out


def _text_tool_catalog(openai_tools: list[dict[str, Any]]) -> str:
    """Compact name/args catalog for text-JSON models (no long descriptions)."""
    lines: list[str] = []
    for tool in openai_tools:
        fn = tool.get("function") or {}
        params = fn.get("parameters") or {}
        required = params.get("required") or []
        parts: list[str] = []
        for key, prop in (params.get("properties") or {}).items():
            if not isinstance(prop, dict):
                continue
            detail = str(prop.get("type") or "object")
            if prop.get("enum"):
                detail = "enum " + "|".join(str(x) for x in prop["enum"])
            if "default" in prop:
                detail += f", default {prop['default']!r}"
            if key in required:
                detail += ", required"
            nested = prop.get("properties")
            if isinstance(nested, dict) and nested:
                detail += " keys: " + ",".join(nested)
            parts.append(f"{key} ({detail})")
        lines.append(f"- {fn.get('name')}: " + ("; ".join(parts) or "no arguments"))
    return "\n".join(lines)


def _compact_behavior_rules(behavior: str) -> str:
    """Keep stop/sibling/exact-arg and project-confirmation rules for NL."""
    text = (behavior or "").strip()
    cut = text.find("## Result format")
    head = text[:cut].rstrip() if cut > 0 else text[:2500]
    marker = "## Project creation confirmation"
    start = text.find(marker)
    if start < 0:
        return head + "\n"
    end = text.find("\n## ", start + len(marker))
    section = text[start:end if end > 0 else None].rstrip()
    return f"{head}\n\n{section}\n"


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """Parse LMS tool argument payload (JSON string or dict) into a dict."""
    from prototyping.medgemma_chat.tool_parse import clean_tool_arguments

    if isinstance(raw, dict):
        return clean_tool_arguments(raw)
    if raw is None or raw == "":
        return {}
    text = str(raw).strip()
    # Common Qwen typo: arguments:{}} instead of "arguments":{}
    text = text.replace("arguments:{}", '"arguments":{}')
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(obj, dict):
        return clean_tool_arguments(obj)
    return {}


def _lms_chat(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.1,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """One chat completion; return content + structured tool_calls.

    For Qwen3, disables thinking via ``chat_template_kwargs`` so tool_calls
    land in the OpenAI field instead of empty content / reasoning blobs.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if _is_qwen_model(model):
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    with httpx.Client(timeout=300.0) as client:
        resp = client.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"LM Studio HTTP {resp.status_code}: {resp.text[:2000]}"
            )
        data = resp.json()
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected LM Studio response: {data!r}") from exc

    content = str(message.get("content") or "")
    reasoning = str(message.get("reasoning_content") or "")
    parsed_calls: list[dict[str, Any]] = []
    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        name = fn.get("name") if isinstance(fn, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue
        parsed_calls.append(
            {
                "id": str(tc.get("id") or f"call_{len(parsed_calls)}"),
                "name": name.strip(),
                "arguments": _parse_tool_arguments(
                    fn.get("arguments") if isinstance(fn, dict) else None
                ),
                "raw": tc,
            }
        )
    return {
        "content": content,
        "reasoning": reasoning,
        "tool_calls": parsed_calls,
        "message": message,
    }


def _values_equal(want: Any, got: Any) -> bool:
    """Canonical arg equality: dicts subset-wise, numbers by value."""
    if isinstance(want, bool) or isinstance(got, bool):
        return want is got or str(got).lower() == str(want).lower()
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return float(want) == float(got)
    if isinstance(want, dict) and isinstance(got, dict):
        return all(
            key in got and _values_equal(val, got[key]) for key, val in want.items()
        )
    if isinstance(want, list) and isinstance(got, list):
        return len(want) == len(got) and all(
            _values_equal(w, g) for w, g in zip(want, got, strict=True)
        )
    return str(got) == str(want)


def _args_match(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    tool_name: str | None = None,
) -> bool:
    """True if every expected key equals the actual/default value."""
    for key, want in expected.items():
        got = actual.get(key)
        if key not in actual and tool_name:
            try:
                from anonymizer.mcp.api.catalog import TOOL_INPUT_MODELS

                field = TOOL_INPUT_MODELS[tool_name].model_fields.get(key)
                default = field.get_default(call_default_factory=True) if field else None
                got = getattr(default, "value", default)
            except Exception:
                got = None
        if not _values_equal(want, got):
            return False
    return True


def _step_matches(step: dict[str, Any], call: dict[str, Any]) -> bool:
    """Return whether one actual call satisfies an expected trace step."""
    if call.get("name") != step.get("tool"):
        return False
    if not _args_match(
        step.get("arguments") or {},
        call.get("arguments") or {},
        tool_name=step.get("tool"),
    ):
        return False
    if step.get("before_clarify") and call.get("_after_clarify"):
        return False
    if step.get("after_clarify") and not call.get("_after_clarify"):
        return False
    if step.get("result_status") and call.get("_result_status") != step["result_status"]:
        return False
    expected_args = step.get("arguments") or {}
    if step.get("tool") == "create_project" and "confirm" in expected_args:
        expected_status = "created" if expected_args["confirm"] else "confirmation_required"
        if call.get("_result_status") != expected_status:
            return False
    return True


def _score_case(
    case: dict[str, Any],
    *,
    tools_called: list[dict[str, Any]],
    final_text: str,
) -> dict[str, Any]:
    """Compare tool trace / ask behavior to scenario expected_trace."""
    expected = _subs(case.get("expected_trace") or [])
    reasons: list[str] = []
    names = [t["name"] for t in tools_called]

    for forbid in case.get("forbidden_tools") or []:
        if forbid in names:
            reasons.append(f"forbidden tool called: {forbid}")

    for forbid in case.get("forbidden_first_tools") or []:
        if names and names[0] == forbid:
            reasons.append(f"forbidden first tool: {forbid}")

    for forbid in case.get("forbidden_before_create") or []:
        if "create_project" in names:
            idx_c = names.index("create_project")
            if forbid in names[:idx_c]:
                reasons.append(f"{forbid} before create_project")

    exp_tools = [s for s in expected if s.get("tool")]
    exp_asks = [s for s in expected if s.get("ask") is True]

    if exp_asks and not exp_tools:
        if tools_called:
            reasons.append(f"expected ask-only but tools={names}")
        for ask in exp_asks:
            blob = final_text.lower()
            for token in ask.get("must_mention") or []:
                t = token.lower()
                alt = t.replace("_", " ")
                if t not in blob and alt not in blob:
                    reasons.append(f"ask reply missing mention of {token!r}")

    # Soft sequence: each expected tool must appear in order with matching args.
    cursor = 0
    for step in exp_tools:
        want_name = step["tool"]
        want_args = step.get("arguments") or {}
        found = None
        for i in range(cursor, len(tools_called)):
            if _step_matches(step, tools_called[i]):
                found = i
                break
        if found is None:
            reasons.append(
                f"missing tool {want_name} with args {want_args} in trace {tools_called}"
            )
        else:
            cursor = found + 1

    passed = not reasons
    return {
        "id": case["id"],
        "pass": passed,
        "reasons": reasons,
        "tools_called": tools_called,
        "final_text": final_text[:2000],
        "utterance": case.get("utterance"),
    }


def _tool_result_payload(result: Any) -> dict[str, Any]:
    """Parse a JSON MCP tool result for direct scenario preparation."""
    text = "".join(getattr(b, "text", "") or "" for b in (result.content or []))
    if text.lower().startswith("error:"):
        raise RuntimeError(text)
    payload = json.loads(text)
    if payload.get("ok") is False:
        raise RuntimeError(text)
    return payload


async def _call_tool_json(
    session: Any,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Call one MCP tool directly and return its JSON payload."""
    return _tool_result_payload(await session.call_tool(name, arguments))


async def _confirm_prepared_project(
    session: Any,
    *,
    name: str,
    storage: Path,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare and confirm one project through the public MCP flow."""
    storage.mkdir(parents=True, exist_ok=True)
    prepared = await _call_tool_json(
        session,
        "create_project",
        {
            "project_name": name,
            "storage_dir": str(storage),
            "overwrite": True,
            "confirm": False,
            **(arguments or {}),
        },
    )
    if prepared.get("status") != "confirmation_required":
        raise RuntimeError(f"prepare create_project failed: {prepared}")
    created = await _call_tool_json(
        session,
        "create_project",
        {
            "project_name": name,
            "confirm": True,
            "revision": prepared["revision"],
        },
    )
    if created.get("status") != "created":
        raise RuntimeError(f"confirm create_project failed: {created}")
    return created


async def _prepare_project(
    session: Any,
    *,
    name: str,
    storage: Path,
) -> None:
    """Create a fresh confirmed project so tool-only scenarios have a session."""
    await _confirm_prepared_project(session, name=name, storage=storage)


async def _prepare_pending_project(
    session: Any,
    *,
    storage: Path,
) -> None:
    """Create/revise a pending PendingConfig draft at revision 2."""
    # Confirm once first so any draft from a previous scenario is cleared and
    # the revision counter deterministically returns to 1 for the next draft.
    await _confirm_prepared_project(
        session,
        name="PendingConfig",
        storage=storage,
        arguments={"modalities": ["CT", "MR"]},
    )
    prepared = await _call_tool_json(
        session,
        "create_project",
        {
            "project_name": "PendingConfig",
            "storage_dir": str(storage),
            "overwrite": True,
            "modalities": ["CT", "MR"],
            "confirm": False,
        },
    )
    revised = await _call_tool_json(
        session,
        "create_project",
        {
            "project_name": "PendingConfig",
            "overwrite": True,
            "modalities": ["CT", "US"],
            "confirm": False,
        },
    )
    if prepared.get("revision") != 1 or revised.get("revision") != 2:
        raise RuntimeError(f"pending project preparation failed: {prepared} -> {revised}")


def _parse_any_tool_call(reply: str) -> dict[str, Any] | None:
    """Parse MedGemma-style JSON or Qwen ``<tool_call>`` XML (text fallback)."""
    import re

    from prototyping.medgemma_chat.tool_parse import clean_tool_arguments, parse_tool_call

    found = parse_tool_call(reply)
    if found is not None:
        return found
    repaired = (reply or "").replace("arguments:{}", '"arguments":{}')
    found = parse_tool_call(repaired)
    if found is not None:
        return found
    for match in re.finditer(
        r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
        repaired,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        try:
            obj = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("name"), str):
            args = obj.get("arguments") or {}
            if not isinstance(args, dict):
                continue
            return {"name": obj["name"].strip(), "arguments": clean_tool_arguments(args)}
    return None


def _expected_tools_satisfied(
    case: dict[str, Any], tools_called: list[dict[str, Any]]
) -> bool:
    """True when every expected tool step already appears with matching args."""
    expected = _subs(case.get("expected_trace") or [])
    cursor = 0
    for step in expected:
        if not step.get("tool"):
            continue
        found = None
        for i in range(cursor, len(tools_called)):
            if _step_matches(step, tools_called[i]):
                found = i
                break
        if found is None:
            return False
        cursor = found + 1
    return True


def _user_turn_suffix(model: str) -> str:
    """Per-user-message suffix: tool discipline + Qwen no-think."""
    if _is_medgemma_model(model):
        return (
            "\n\nIf a tool is needed, reply with exactly one JSON object and "
            'nothing else: {"name": "<tool_name>", "arguments": {<args>}}. '
            "Use exact argument field names only. If you must ask the clinician, "
            "reply with a short question only. Do not invent paths, AETs, ports, "
            "or UIDs. After a confirmation_required tool result, stop."
        )
    suffix = (
        "\n\nIf a tool is needed, call it via the provided tools API "
        "(exact argument field names only). "
        "If you must ask the clinician, reply with a short question only "
        "(mention project_name / DIMSE / DICOMweb when relevant). "
        "When the clinician clarifies with exact field values, call the tool "
        "immediately — do not invent missing keys. "
        "Do not invent paths, AETs, ports, or UIDs."
    )
    if _is_qwen_model(model):
        suffix += "\n/no_think"
    return suffix


async def _agent_rounds(
    session: Any,
    *,
    messages: list[dict[str, Any]],
    tools_called: list[dict[str, Any]],
    lms_url: str,
    model: str,
    openai_tools: list[dict[str, Any]],
    max_rounds: int,
    text_tool_mode: bool = False,
    expect_ask_only: bool = False,
) -> str:
    """Run tool/ask rounds until the model stops calling tools. Mutates messages."""
    from prototyping.medgemma_chat.mcp_client import tool_result_text
    from prototyping.medgemma_chat.tool_parse import needs_tool_nudge

    # Generic nudge: the prototype's stock nudge names example tools, which
    # 4-bit models copy literally instead of choosing the requested tool.
    tool_nudge = (
        "Stop. Reply with only one JSON tool call now — no thought, no prose. "
        "Use the tool that fulfills the latest user request, with the exact "
        "values from that request."
    )
    required_by_tool = {
        str(tool["function"]["name"]): list(
            (tool["function"].get("parameters") or {}).get("required") or []
        )
        for tool in openai_tools
        if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
    }

    final_text = ""
    nudge_count = 0
    for _ in range(max_rounds):
        reply = await asyncio.to_thread(
            _lms_chat,
            base_url=lms_url,
            model=model,
            messages=messages,
            tools=None if text_tool_mode else (openai_tools or None),
            temperature=0.0 if text_tool_mode else 0.1,
        )
        content = reply["content"]
        native_calls = reply["tool_calls"]
        calls: list[dict[str, Any]] = []
        if native_calls:
            calls = [
                {
                    "name": c["name"],
                    "arguments": c["arguments"],
                    "id": c["id"],
                    "raw": c.get("raw"),
                }
                for c in native_calls
            ]
        else:
            parsed = _parse_any_tool_call(content)
            if parsed is not None:
                calls = [{**parsed, "id": "text_0", "raw": None}]

        visible = content.strip() or (reply["reasoning"].strip() if not calls else "")
        final_text = visible if visible else final_text

        if not calls:
            if text_tool_mode and nudge_count < 4 and needs_tool_nudge(content):
                nudge_count += 1
                messages.append({"role": "assistant", "content": content})
                if expect_ask_only:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Stop. Do not call a tool. Reply in plain "
                                "language now, answering the question from "
                                "the system instructions."
                            ),
                        }
                    )
                else:
                    messages.append({"role": "user", "content": tool_nudge})
                continue
            messages.append({"role": "assistant", "content": content})
            if visible:
                final_text = visible
            break

        call = calls[0]
        if text_tool_mode and tools_called:
            last = tools_called[-1]
            if last["name"] == call["name"] and last["arguments"] == call["arguments"]:
                # Non-tool-trained models often repeat the same JSON call after
                # seeing its result; executing it again only restages/loops.
                break
        if text_tool_mode and call["name"] not in required_by_tool:
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"name": call["name"], "arguments": call["arguments"]}
                    ),
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Tool {call['name']!r} does not exist and was not "
                        "executed. Use exactly one tool name from the "
                        "Available tools list that fulfills the latest user "
                        "request, with the exact values from that request."
                    ),
                }
            )
            nudge_count = 0
            continue
        if text_tool_mode:
            missing = [
                key
                for key in required_by_tool.get(call["name"], [])
                if call["arguments"].get(key) in (None, "")
            ]
            if (
                not missing
                and not call["arguments"]
                and call["name"] == "update_project_settings"
            ):
                # All update keys are optional in the schema, but an empty
                # update can never fulfill a settings-change request.
                missing = ["<at least one setting>"]
            if missing:
                # Do not execute empty/invented calls: feed the schema failure
                # back so the model can ask or retry with the user's values.
                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {"name": call["name"], "arguments": call["arguments"]}
                        ),
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"That tool call was not executed: missing required "
                            f"arguments {missing}. If the user gave those exact "
                            "values, call the tool again with them. If a value "
                            "or the DIMSE versus DICOMweb choice is missing, "
                            "ask a short question and do not emit JSON."
                        ),
                    }
                )
                nudge_count = 0
                continue
        recorded_call = {"name": call["name"], "arguments": call["arguments"]}
        tools_called.append(recorded_call)

        if text_tool_mode:
            # MedGemma prototype protocol: keep the JSON call as assistant text
            # and return the result as a user turn (no OpenAI tool roles).
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"name": call["name"], "arguments": call["arguments"]}
                    ),
                }
            )
        else:
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content or None,
            }
            if call.get("raw"):
                assistant_msg["tool_calls"] = [call["raw"]]
            else:
                assistant_msg["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                ]
            messages.append(assistant_msg)

        result = await session.call_tool(call["name"], call.get("arguments") or {})
        tool_txt = tool_result_text(result)
        recorded_call["_result_ok"] = not tool_txt.lower().startswith("error:")
        try:
            payload = json.loads(tool_txt)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if isinstance(payload, dict):
            recorded_call["_result_status"] = payload.get("status")
        final_text = tool_txt
        if text_tool_mode:
            if recorded_call.get("_result_status") in {
                "confirmation_required",
                "updated",
            }:
                # Server contract: present the configuration/update and stop.
                break
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Tool result for {call['name']}:\n{tool_txt}\n\n"
                        "If the latest user request is done, reply in plain "
                        "language and stop. The request may have several "
                        "parts — verify every part is complete before "
                        "stopping. Only emit another JSON tool call "
                        "if that same request still needs it. Before another "
                        "call, re-read the latest user request and include "
                        "every explicitly mentioned setting exactly; do not "
                        "drop any setting. Unless the user explicitly asked "
                        "for defaults/ranges or current settings, do not call "
                        "project_settings_defaults or project_info next; "
                        "perform the requested action instead."
                    ),
                }
            )
        else:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": tool_txt,
                }
            )
    return final_text


async def _run_utterance(
    session: Any,
    *,
    system: str,
    utterance: str,
    lms_url: str,
    model: str,
    openai_tools: list[dict[str, Any]],
    case: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Agent loop with optional harness ``clarify`` turn (naive → guided).

    If the case has ``clarify`` and the expected tool trace is not satisfied after
    the first user message, inject that clarification as the next user turn and
    continue — simulating a clinician who answers the model's questions.
    """
    suffix = _user_turn_suffix(model)
    trace = (case or {}).get("expected_trace") or []
    expect_ask_only = bool(trace) and all(
        step.get("ask") is True for step in trace
    )
    if expect_ask_only:
        # Restraint cases: missing values/choices must be asked about, and
        # how-to questions answered, before any tool is considered.
        suffix += (
            "\nNote: missing required values or choices are asked about "
            "first, and how-to questions are answered in words; tools are "
            "only for complete, actionable requests."
        )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": utterance + suffix},
    ]
    tools_called: list[dict[str, Any]] = []
    text_tool_mode = _is_medgemma_model(model)
    final_text = await _agent_rounds(
        session,
        messages=messages,
        tools_called=tools_called,
        lms_url=lms_url,
        model=model,
        openai_tools=openai_tools,
        max_rounds=MAX_TOOL_ROUNDS,
        text_tool_mode=text_tool_mode,
        expect_ask_only=expect_ask_only,
    )

    clarify = (case or {}).get("clarify") if case else None
    if clarify and case is not None and not _expected_tools_satisfied(case, tools_called):
        clarify_text = _subs(str(clarify)).strip()
        print(f"CLARIFY: {clarify_text[:300]}", flush=True)
        messages.append({"role": "user", "content": clarify_text + suffix})
        before_clarify_count = len(tools_called)
        more = await _agent_rounds(
            session,
            messages=messages,
            tools_called=tools_called,
            lms_url=lms_url,
            model=model,
            openai_tools=openai_tools,
            max_rounds=MAX_TOOL_ROUNDS,
            text_tool_mode=text_tool_mode,
            expect_ask_only=expect_ask_only,
        )
        for call in tools_called[before_clarify_count:]:
            call["_after_clarify"] = True
        if more:
            final_text = more
    elif (
        case is not None
        and not expect_ask_only
        and not _expected_tools_satisfied(case, tools_called)
    ):
        # Multi-part requests: small models sometimes stop after the first
        # tool. One continuation turn restates the original request.
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Continue: finish every part of my request: {utterance}"
                    + suffix
                ),
            }
        )
        more = await _agent_rounds(
            session,
            messages=messages,
            tools_called=tools_called,
            lms_url=lms_url,
            model=model,
            openai_tools=openai_tools,
            max_rounds=MAX_TOOL_ROUNDS,
            text_tool_mode=text_tool_mode,
            expect_ask_only=expect_ask_only,
        )
        if more:
            final_text = more
    return tools_called, final_text


async def _drive(
    mcp_url: str,
    *,
    lms_url: str,
    model: str,
    processing_dir: Path,
    run_home: Path,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    results: list[dict[str, Any]] = []
    async with streamable_http_client(mcp_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            openai_tools = _mcp_tools_to_openai(list(tools))
            # Behavior rules only (schemas come from native tools payloads).
            from anonymizer.mcp.instructions import load_behavior_instructions

            load_behavior_instructions.cache_clear()
            behavior = _compact_behavior_rules(load_behavior_instructions())
            if _is_medgemma_model(model):
                # Text-JSON protocol (as in prototyping.medgemma_chat), but
                # with the slimmed schemas used for native calls so the 4-bit
                # model is not diluted by long per-field descriptions.
                system = (
                    "You are an MCP tool-calling agent for the RSNA DICOM "
                    "Anonymizer.\n"
                    "Copy every setting the user explicitly mentions into "
                    "the tool arguments exactly (project names, policies, "
                    "modality lists, language codes, IPs, ports, AETs); "
                    "do not drop a mentioned setting. To configure a "
                    "PACS remote, the tool is always `configure_remote`; "
                    "never invent tool names.\n\n"
                    "Server behavior rules:\n"
                    + behavior
                    + "\n## Available tools\n"
                    + _text_tool_catalog(openai_tools)
                    + "\n\nWhen you need a tool, reply with exactly one JSON "
                    'object and nothing else: {"name": "<tool_name>", '
                    '"arguments": {<args>}}. One tool per reply — wait for '
                    "the tool result before another call."
                )
            else:
                system = (
                    "You are an MCP tool-calling agent for the RSNA DICOM Anonymizer.\n"
                    "Prefer exact argument field names (unknown keys are rejected). "
                    "One tool per turn. Never invent paths, AETs, ports, or UIDs.\n"
                    "If values are incomplete, ask briefly; when the clinician clarifies "
                    "with exact fields, call the tool immediately with those names.\n"
                    "Series inventory → list_inventory (not project_info).\n\n"
                    "Server behavior rules:\n"
                    + behavior
                )

            for case in cases:
                cid = case["id"]
                utterance = _subs(case["utterance"])
                # Fixture path: put absolute path in the utterance for import scenarios.
                if case.get("fixture") == "davidson_cxr":
                    utterance = (
                        f"Import the Davidson CXR file at this absolute path: {DAVIDSON_DCM}"
                    )
                elif case.get("fixture") == "davidson_dir":
                    utterance = (
                        "Import the DICOM directory at this absolute path: "
                        f"{DAVIDSON_DCM.parent}"
                    )

                prep_dir = processing_dir / "projects" / cid
                if case.get("requires_pending_project"):
                    await _prepare_pending_project(session, storage=prep_dir)
                elif case.get("requires_open_project"):
                    prep_name = case.get("prepare_name") or (
                        "NL " + cid.replace("_", " ")[:14]
                    )
                    # Open-by-name scenarios need the project in the default
                    # store inside the MCP subprocess's synthetic HOME.
                    prep_storage = (
                        run_home / "Documents" / "RSNA Anonymizer" / prep_name
                        if case.get("prepare_in_default_store")
                        else prep_dir
                    )
                    await _prepare_project(
                        session,
                        name=prep_name,
                        storage=prep_storage,
                    )
                    if case.get("import_davidson_first") or cid == "inventory_after_import":
                        await session.call_tool(
                            "import_file", {"file_path": str(DAVIDSON_DCM)}
                        )

                print(f"\n=== {cid} ===\nUSER: {utterance}", flush=True)
                tools_called, final_text = await _run_utterance(
                    session,
                    system=system,
                    utterance=utterance,
                    lms_url=lms_url,
                    model=model,
                    openai_tools=openai_tools,
                    case=case,
                )
                print(f"TOOLS: {tools_called}", flush=True)
                print(f"FINAL: {final_text[:500]}", flush=True)
                scored = _score_case(
                    case, tools_called=tools_called, final_text=final_text
                )
                print(f"PASS={scored['pass']} reasons={scored['reasons']}", flush=True)
                results.append(scored)

    passed = sum(1 for r in results if r["pass"])
    return {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "model": model,
        "model_path": str(MODEL_PATHS.get(model, "")),
        "lms_url": lms_url,
        "mcp_url": mcp_url,
        "processing_dir": str(processing_dir),
        "run_home": str(run_home),
        "application_log": str(_application_log_path(run_home)),
        "davidson_dcm": str(DAVIDSON_DCM),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lms-url", default=DEFAULT_LMS_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--mcp-host", default="127.0.0.1")
    parser.add_argument("--mcp-port", type=int, default=8000)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "Report directory for nl_scenario_results.json and "
            "mcp_server.log only; project processing always uses a "
            "temporary directory"
        ),
    )
    parser.add_argument(
        "--external-mcp",
        action="store_true",
        help="Do not spawn MCP; assume already listening",
    )
    parser.add_argument(
        "--unload-model-on-exit",
        action="store_true",
        help=(
            "Unload --model from LM Studio when the run finishes; use on "
            "the final pack so LM Studio's llmworker releases the weights"
        ),
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated scenario ids to run (default: all in pack)",
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=SCENARIOS_DEFAULT,
        help="Scenario YAML pack (default: mvp.yaml tool-call pack; ask_gate.yaml optional)",
    )
    args = parser.parse_args()

    model_path = MODEL_PATHS.get(args.model)
    if model_path is not None and not model_path.is_dir():
        print(f"Model directory missing: {model_path}", file=sys.stderr)
        return 1

    # Probe LM Studio.
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(args.lms_url.rstrip("/") + "/models")
            r.raise_for_status()
            ids = [m.get("id") for m in (r.json().get("data") or [])]
    except Exception as exc:
        print(
            f"LM Studio not reachable at {args.lms_url}: {exc}\n"
            "Run:\n  lms server start -p 1234\n  lms load qwen3-14b-mlx -c 8192 -y",
            file=sys.stderr,
        )
        return 1
    if args.model not in ids:
        print(f"Model {args.model!r} not in LM Studio models {ids}", file=sys.stderr)
        return 1

    scenarios_path = args.scenarios.expanduser().resolve()
    if not scenarios_path.is_file():
        print(f"Scenarios file missing: {scenarios_path}", file=sys.stderr)
        return 1
    cases = yaml.safe_load(scenarios_path.read_text(encoding="utf-8"))["scenarios"]
    if args.only.strip():
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        cases = [c for c in cases if c["id"] in want]
    print(f"scenarios={scenarios_path.name} count={len(cases)}", flush=True)

    # Processing never uses the report directory or the developer's real
    # project store. Reports may be retained separately for inspection.
    processing_dir = _create_processing_dir()
    report_dir = (
        args.out_dir.expanduser().resolve()
        if args.out_dir is not None
        else Path(tempfile.mkdtemp(prefix="anonymizer-nl-reports-"))
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    mcp_url = f"http://{args.mcp_host}:{args.mcp_port}/mcp"
    trained_for_tool_use: bool | None = None
    try:
        meta = json.loads(
            subprocess.check_output(["lms", "ls", "--json"], text=True)
        )
        for row in meta:
            if row.get("modelKey") == args.model or args.model in str(
                row.get("indexedModelIdentifier") or ""
            ):
                trained_for_tool_use = bool(row.get("trainedForToolUse"))
                break
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        trained_for_tool_use = None
    print(
        f"model={args.model} trainedForToolUse={trained_for_tool_use} "
        f"path={model_path or '(unknown)'}",
        flush=True,
    )

    # The spawned MCP process gets a synthetic HOME inside the temporary
    # processing directory, so its Documents/RSNA Anonymizer store and
    # anonymizer.log are removed with the rest of the run's processing data.
    run_home = Path.home() if args.external_mcp else _run_home(processing_dir)
    mcp_server_log = None if args.external_mcp else report_dir / "mcp_server.log"

    proc: subprocess.Popen | None = None
    log_fh = None
    if not args.external_mcp:
        assert mcp_server_log is not None
        run_home.mkdir(parents=True, exist_ok=True)
        log_fh = mcp_server_log.open("w", encoding="utf-8")
        print(
            f"Starting MCP at {mcp_url} "
            f"(MCP server stdout/stderr={mcp_server_log}; "
            f"isolated HOME={run_home})",
            flush=True,
        )
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "anonymizer.anonymizer",
                "--mcp",
                f"{args.mcp_host}:{args.mcp_port}",
            ],
            cwd=str(REPO),
            env={**os.environ, "HOME": str(run_home)},
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_mcp_tcp(args.mcp_host, args.mcp_port, proc, timeout_s=300.0)
        except (RuntimeError, TimeoutError) as exc:
            print(exc, file=sys.stderr)
            _stop_mcp_process(proc)
            if log_fh:
                log_fh.close()
            if args.unload_model_on_exit:
                _unload_model_from_lm_studio(args.model)
            return 1
        time.sleep(0.5)
        print(f"MCP listening pid={proc.pid}", flush=True)

    try:
        summary = asyncio.run(
            _drive(
                mcp_url,
                lms_url=args.lms_url,
                model=args.model,
                processing_dir=processing_dir,
                run_home=run_home,
                cases=cases,
            )
        )
        summary["trained_for_tool_use"] = trained_for_tool_use
        summary["report_dir"] = str(report_dir)
        summary["mcp_server_log"] = (
            str(mcp_server_log) if mcp_server_log is not None else None
        )
    except Exception as exc:
        import traceback

        print(f"NL run failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1
    finally:
        if proc is not None:
            _stop_mcp_process(proc)
        if log_fh is not None:
            log_fh.close()
        if args.unload_model_on_exit:
            _unload_model_from_lm_studio(args.model)

    out = report_dir / "nl_scenario_results.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("ok", "passed", "total", "model")}, indent=2))
    print(f"Results: {out}", flush=True)
    if mcp_server_log is not None:
        print(f"MCP server stdout/stderr: {mcp_server_log}", flush=True)
    print(
        f"Temporary processing directory (removed at exit): {processing_dir}",
        flush=True,
    )
    if not args.external_mcp:
        print(
            "Application anonymizer.log was under the temporary MCP HOME: "
            f"{_application_log_path(run_home)}",
            flush=True,
        )
    if args.unload_model_on_exit:
        print(f"LM Studio model unloaded on exit: {args.model}", flush=True)
    else:
        print(
            f"LM Studio model remains loaded: {args.model} "
            f"(unload with: lms unload {args.model})",
            flush=True,
        )
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
