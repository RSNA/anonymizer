# Run headless

Use headless mode on a **lab or server** when you do not need the desktop window. Create and configure the project in the GUI first.

## Goal

- Keep receiving DICOM into an existing project, and/or
- Run AI batch once on that project, then exit, and/or
- Expose the **MCP** tool interface so an LLM client can drive projects, import, inventory, and imaging tools.

## Receive and AI batch

### 1. Receive only (DICOM listener)

```bash
rsna-anonymizer -c path/to/ProjectModel.json
```

The app loads the project and listens for incoming images using the project’s local server settings.

### 2. AI batch once, then exit

```bash
rsna-anonymizer -c path/to/ProjectModel.json --ai-batch path/to/AiBatchConfig.json --ai-batch-run
```

Both `-c` / `--config` and `--ai-batch` are required with `--ai-batch-run`. Do **not** combine `-c` with `--mcp` (mutually exclusive).

## What each file is for

| File | Purpose |
| --- | --- |
| **ProjectModel.json** | Site, project name, storage path, DICOM nodes, modalities, timeouts—the project definition. |
| **AiBatchConfig.json** | Which AI tools to run, blur/OCR modes, study selection (`all` or a list), optional CT/MR resolution overrides. |

Example AI batch config (downloadable: [`AiBatchConfig.example.json`](AiBatchConfig.example.json)):

```json
{
  "algorithms": ["harmonize", "face_blur", "remove_pixel_phi"],
  "blur_mode": "gaussian",
  "pixel_phi_removal_mode": "blackout",
  "use_modality_whitelist": true,
  "include_brain_structures": false,
  "ct_segmentation_mode": "3mm",
  "mr_segmentation_mode": "3mm",
  "studies": "all",
  "skip_already_processed": true
}
```

OCR whitelists remain under the project `whitelists/` directory (same as the GUI).

## MCP server

`-c` and `--mcp` are **mutually exclusive**. Use `-c` for DICOM receive (or AI batch); use `--mcp` for the MCP tool server. Open or create projects with MCP tools after connect.

Install the optional MCP extra once (FastMCP-based server):

```bash
uv sync --extra mcp
# or: pip install 'rsna-anonymizer[mcp]'
```

### HTTP MCP

```bash
rsna-anonymizer --mcp 127.0.0.1:8000
```

Endpoint: `http://127.0.0.1:8000/mcp` (path `/mcp` is fixed). Leave the process running; clients connect to that URL.

### Stdio MCP (spawn clients)

```bash
rsna-anonymizer --mcp
```

### Client `mcp.json`

LLM clients typically load an `mcp.json` (or equivalent). Example: [`mcp.example.json`](mcp.example.json).

**HTTP (URL) form** — matches `--mcp 127.0.0.1:8000`:

```json
{
  "mcpServers": {
    "rsna-anonymizer": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

**Stdio (spawn) form** (see [`mcp.stdio.example.json`](mcp.stdio.example.json)):

```json
{
  "mcpServers": {
    "rsna-anonymizer": {
      "command": "uv",
      "args": ["run", "rsna-anonymizer", "--mcp"]
    }
  }
}
```

Rules:

- Client URL is always `http://HOST:PORT/mcp`.
- Host and port must match `--mcp HOST:PORT`.
- After changing server instructions or tools, **restart the MCP process** and start a **new** chat in the client so `initialize` reloads.

### What the model sees

Per the [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools):

1. **`initialize`** — server instructions (API howto + selectors)
2. **`tools/list`** — each tool’s `name`, `description`, and `inputSchema`
3. **`tools/call`** — plain text results (`list_inventory` is a TSV table; other tools return compact JSON or `error: …`)

Tool groups: session (`list_projects`, `create_project`, `project_open`, `project_info`), local ingest (`import_directory`, `import_file`), PACS (`configure_remote`, `pacs_find`, `pacs_move`), inventory (`list_inventory`), process (`remove_pixel_phi`, `harmonize_studies`, `export_series_preview`). Full argument tables live in the server instructions asset shipped with the package (`anonymizer/mcp/assets/instructions.md`).

Always pass `arguments` (use `{}` for zero-argument tools). Do not invent client result markers such as `TOOL_RESULT` / `END_TOOL_RESULT`.

### GUI and MCP

Two processes (do not write the same project from both at once):

```bash
# Terminal 1 — GUI
rsna-anonymizer

# Terminal 2 — HTTP MCP
rsna-anonymizer --mcp 127.0.0.1:8000
```

### Prototype MedGemma chat

Local MedGemma MCP client (REPL or Gradio) under `src/prototyping/medgemma_chat/` in the source tree. Protocol: `initialize` → `tools/list` → `tools/call`. It loads **Hugging Face / PyTorch** weights via `--model` (not MLX / GGUF chat-app downloads).

**Terminal 1 — anonymizer HTTP MCP**

```bash
cd /path/to/anonymizer
uv sync --extra mcp
uv run rsna-anonymizer --mcp 127.0.0.1:8000
```

**Terminal 2 — MedGemma chat**

```bash
cd /path/to/anonymizer
uv sync --extra mcp --group medgemma-chat
uv run python -m prototyping.medgemma_chat \
  --model /path/to/medgemma_hf_weights \
  --mcp-url http://127.0.0.1:8000/mcp
```

Gradio UI (needs the `dev` dependency group for Gradio):

```bash
uv sync --extra mcp --group medgemma-chat --group dev
uv run python -m prototyping.medgemma_chat \
  --model /path/to/medgemma_hf_weights \
  --mcp-url http://127.0.0.1:8000/mcp \
  --ui gradio
```

Full flags: [`src/prototyping/medgemma_chat/README.md`](../../../src/prototyping/medgemma_chat/README.md).

## Prerequisites

- Project already created in the GUI ([Create a project](../05-create-project/)).
- Models and face license already set up on **this machine** ([AI Features setup](../03-ai-features-setup)).
- Enough free memory for the selected algorithms.
- For MCP: the `[mcp]` optional dependency installed.

## What good looks like

- Receive mode: process stays running; new studies appear under storage / Dataset when you open the GUI later.
- Batch mode: log shows phases and a summary; process exits when finished (exit code 0 on success).
- MCP: client `tools/list` shows anonymizer tools; `list_inventory` returns a TSV table.

## Common failures

| Problem | What to check |
| --- | --- |
| `--ai-batch-run` without files | Provide both `-c` and `--ai-batch` |
| `-c` with `--mcp` | Mutually exclusive; run receive/batch **or** MCP |
| Feature gate errors | Download models / license on that workstation |
| Empty study list | Import data first, or fix `studies` in AiBatchConfig |
| Low memory | Reduce concurrent load; see [Troubleshooting](../troubleshooting.md) |
| Client cannot connect | `--mcp HOST:PORT` vs `mcp.json` URL (`http://HOST:PORT/mcp`); MCP extra installed; firewall |
| Stale tools/instructions | Restart MCP; start a new chat in the client |

## For clinicians

Headless does **not** replace reviewing a sample in the Dataset or Series View. Use the GUI for first-time setup and quality checks; use headless for routine receive or overnight batch.

!!! tip "Same job as GUI batch"
    Desktop steps: [Run on many studies](../08-process/05-run-on-many-studies/). Headless uses the same AI tools with a JSON recipe.

## Next steps

1. [Troubleshooting](../troubleshooting.md) if something fails
2. [Tutorials](../tutorials/) for short walkthroughs
3. Back to [Home](../) for the full chapter list
