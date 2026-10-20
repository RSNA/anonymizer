# MCP developer verification

Developer-only verification for `src/anonymizer/mcp`. This directory is the
test submodule for MCP work; natural-language model runs described here are
manual developer checks, **not CI**.

## Test layers

| Layer | Entry point | Runs in CI? |
|---|---|---|
| Deterministic MCP unit/scripted tests | `uv run pytest tests/mcp -q` | Yes — no LLM, no LM Studio, no external model server |
| Live HTTP MCP test placeholder | `test_nl_harness.py::test_nl_live_medgemma_trace_placeholder` | No — marked `mcp_e2e`, excluded by the default `addopts` in `pyproject.toml` |
| Natural-language LM Studio scenario runs | `tests/mcp/run_nl_lmstudio.py` | **No — manual developer verification only; never add this script to CI** |

The manual runner is intentionally a standalone script rather than a pytest
test: it needs a locally loaded LM Studio model, starts an MCP subprocess,
makes real tool calls, and can take several minutes per pack.

## Manual LM Studio verification

### 1. Load the reference model

Qwen3-8B is the current reference model for these workflows:

```bash
lms unload --all
lms load qwen3-8b-mlx -c 8192 -y
lms server start -p 1234
lms ps
```

Use a context of at least 8192. Other models may be substituted with
`--model`, but their results are model-capability checks, not changes to the
MCP contract. In particular, MedGemma models are not trained for native tool
calls and use the runner's text-JSON fallback.

The model stays loaded in LM Studio between packs by design; its memory is
held by LM Studio's `llmworker` Node process, not by the runner or the MCP
child. After the final pack, release it with the runner's
`--unload-model-on-exit` flag on that last invocation, or manually:

```bash
lms unload --all
lms ps
```

If LM Studio is later quit while a model is still loaded, an orphaned
`node`/`llmworker` process can survive; unloading before quitting avoids
leaving the weights resident.

### 2. Run the scenario packs

From the repository root:

```bash
# Reports only: results JSON and the spawned MCP server's captured output.
# Project processing always uses a separate per-run temporary directory.
RUN_REPORTS="$(mktemp -d)"

# Creation and settings modification
.venv/bin/python tests/mcp/run_nl_lmstudio.py \
  --model qwen3-8b-mlx \
  --out-dir "$RUN_REPORTS"

# Discovery/open, import, inventory, imaging, and PACS functions
.venv/bin/python tests/mcp/run_nl_lmstudio.py \
  --model qwen3-8b-mlx \
  --scenarios tests/mcp/scenarios/functions.yaml \
  --out-dir "$RUN_REPORTS"

# Ask-versus-call and usage-help restraint
.venv/bin/python tests/mcp/run_nl_lmstudio.py \
  --model qwen3-8b-mlx \
  --scenarios tests/mcp/scenarios/ask_gate.yaml \
  --out-dir "$RUN_REPORTS"
```

The runner starts and stops its own MCP server on `127.0.0.1:8000`; ensure
that port is free and do not start another MCP server for these runs.

To iterate on one scenario:

```bash
.venv/bin/python tests/mcp/run_nl_lmstudio.py \
  --model qwen3-8b-mlx \
  --scenarios tests/mcp/scenarios/functions.yaml \
  --only project_open_existing \
  --out-dir "$RUN_REPORTS"
```

### 3. Inspect run reports

The report directory (`--out-dir`, or `RUN_REPORTS` above) contains only:

```text
<report-dir>/
  nl_scenario_results.json       # scores, tool traces, failure reasons
  mcp_server.log                 # spawned MCP child's stdout/stderr
```

Use files in this order:

1. `nl_scenario_results.json` for pass/fail and the actual tool trace.
2. `<report-dir>/mcp_server.log` for the spawned MCP server's startup, HTTP,
   `initialize`, and `tools/call` output.

All processing is separate. Each run creates a temporary processing
directory containing the per-scenario projects and the spawned MCP child's
synthetic `HOME`; the child's normal
`Documents/RSNA Anonymizer/logs/anonymizer.log` and default project store
therefore stay in temporary storage. That processing directory is removed
when the runner exits, so automated runs never create projects or processing
data under the developer's real `~/Documents/RSNA Anonymizer` directory.

## Choosing a client for manual verification

The automated NL verification above uses **LM Studio with a local model**
(Qwen3-8B reference) because it is scriptable through its OpenAI-compatible API.
That is a developer-verification choice, not the only way to exercise the server:

- **Smoother manual demos:** A locally running client with a stronger hosted
  model (Cursor, Claude Desktop) usually follows the confirmation protocol,
  the verbatim `anonymizer_usage` answer, and multi-step flows more reliably
  than a small local model, and is not constrained by an 8192-token local
  context. Configure it with the stdio form from
  `docs/en/10-headless/index.md` (`uv run rsna-anonymizer --mcp`) and use a
  fresh chat. Hosted models receive conversation content — demo with test
  data only.
- **Cloud chat products (ChatGPT, Gemini web/mobile):** These run in the
  vendor's cloud and cannot reach `127.0.0.1`. ChatGPT can only connect via a
  public HTTPS tunnel to the local server; the Gemini chat has no custom-MCP
  option at all (Gemini CLI, running locally, does). Do not use tunnelled
  setups for verification: the server has no authentication, so a tunnel
  exposes local file/project access. See "Which LLM clients can connect?" in
  `docs/en/10-headless/index.md`.
- **Local-model gotchas seen in LM Studio:** load Qwen3-8B with at least
  `-c 32768` for multi-turn tool work (the full tool catalog plus history
  overflows 8192), use temperature ≈ 0.1 for tool calling, and be aware the
  GUI may reason before tool calls in ways the runner (thinking disabled,
  temperature 0.1) does not reproduce.

## Scenario packs

- `scenarios/mvp.yaml` — project creation and settings modification.
- `scenarios/functions.yaml` — all other MCP tools.
- `scenarios/ask_gate.yaml` — ask-versus-call restraint and usage help.

`test_nl_harness.py` deterministically checks that the packs are well-formed
and that the creation/settings plus functions packs cover every tool in the
MCP catalog. Those YAML checks may run with the normal test suite; executing
the scenarios against a model remains manual and outside CI.
