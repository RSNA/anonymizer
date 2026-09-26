# MedGemma × Anonymizer MCP chat

Typical MCP LLM client prototype: `initialize` → `tools/list` → model →
`tools/call`. No NL/regex planner. Weights stay on disk; pass `--model`.

`--model` must be a **Hugging Face layout** directory loadable by
`transformers` (PyTorch). Weights load in **NF4 4-bit** via `bitsandbytes`
(~3–4 GB vs ~9 GB BF16). After `export_series_preview`, the PNG is written under
a temp folder (`[preview] …`) and also passed into the next **multimodal**
generate turn so MedGemma can see the image. MLX / GGUF downloads from chat apps
are **not** supported by this prototype.

Generic LLM clients usually load an `mcpServers` wrapper (see
[`docs/en/10-headless/mcp.example.json`](../../../docs/en/10-headless/mcp.example.json)).
This prototype CLI reads a **thin** config (`url` + optional `transport`) as in
[`mcp.example.json`](mcp.example.json).

## Runbook (two terminals)

`-c` and `--mcp` are mutually exclusive on the anonymizer CLI. For chat, run
MCP alone (open/create projects via tools).

### 1. Anonymizer — HTTP MCP

```bash
cd /path/to/anonymizer
uv sync --extra mcp
uv run rsna-anonymizer --mcp 127.0.0.1:8000
```

Leave this running. Endpoint: `http://127.0.0.1:8000/mcp`.

### 2. MedGemma chat — REPL

```bash
cd /path/to/anonymizer
uv sync --extra mcp --group medgemma-chat
uv run python -m prototyping.medgemma_chat \
  --model /path/to/medgemma_hf_weights \
  --mcp-url http://127.0.0.1:8000/mcp
```

Or with the thin config file:

```bash
uv run python -m prototyping.medgemma_chat \
  --model /path/to/medgemma_hf_weights \
  --mcp-config src/prototyping/medgemma_chat/mcp.example.json
```

### 3. Optional — Gradio UI

`gradio` is in the `dev` dependency group:

```bash
uv sync --extra mcp --group medgemma-chat --group dev
uv run python -m prototyping.medgemma_chat \
  --model /path/to/medgemma_hf_weights \
  --mcp-url http://127.0.0.1:8000/mcp \
  --ui gradio
```

## Flags

| Flag | Meaning |
| --- | --- |
| `--model PATH` | **Required.** Local MedGemma HF weights directory |
| `--mcp-url URL` | Streamable HTTP endpoint (wins over config file) |
| `--mcp-config PATH` | Thin JSON `{"url":"...","transport":"streamable-http"}` |
| `--ui repl\|gradio` | Interface (default `repl`) |
| `--device auto\|mps\|cpu\|cuda` | Inference device |
| `--max-tokens N` | Generation budget per call |

Tool schemas always come from live `tools/list` (not a hardcoded allowlist).

More MCP CLI and `mcp.json` detail: [Run headless](../../../docs/en/10-headless/index.md).
