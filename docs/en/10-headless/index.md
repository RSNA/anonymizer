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
  "ocr_remove_mode": "non_whitelisted",
  "include_brain_structures": false,
  "ct_segmentation_mode": "3mm",
  "mr_segmentation_mode": "3mm",
  "studies": "all",
  "skip_already_processed": true
}
```

OCR whitelists and exclude areas remain under the project `whitelists/` directory (same as the GUI). Set `ocr_use_exclude_areas` to true to apply saved `whitelists/{modality}.exclude.json` rectangles. `use_modality_whitelist` is still accepted and maps true to `non_whitelisted`, false to `all_text`.

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

### Which LLM clients can connect?

The server speaks the two standard local MCP transports — stdio (client spawns the
server) and streamable HTTP on `127.0.0.1` — so any **locally running** MCP client
can use it. Cloud-hosted chat products cannot reach a server on your machine's
`127.0.0.1`; they can only connect to MCP servers exposed on the public internet
over HTTPS.

| Client | Runs where | Connects to this server? |
|---|---|---|
| Cursor, Claude Desktop, Gemini CLI, LM Studio | Your machine | ✅ Yes — stdio spawn or `http://127.0.0.1:8000/mcp` |
| ChatGPT (web/desktop chat) | OpenAI cloud | ⚠️ Only via a public HTTPS tunnel (see below) |
| Gemini (web/mobile chat) | Google cloud | ❌ No generic custom-MCP option; use Gemini CLI instead |

**ChatGPT:** Custom MCP connectors (Developer Mode / Apps) connect from OpenAI's
cloud to a public HTTPS endpoint. To demo with ChatGPT you would expose the local
server with a tunnel (for example `ngrok http 8000` or Cloudflare Tunnel) and
register the resulting `https://…/mcp` URL as a custom connector.

> **Security warning:** The MCP server can create projects and read/import local
> DICOM files, and it has no authentication of its own. A tunnel makes that
> endpoint internet-reachable. Only ever do this briefly, with test data and
> tunnel-level access controls, and close the tunnel immediately afterwards.
> **Never expose the server this way with real patient data.**

**Gemini:** The consumer Gemini chat has no "add your own MCP server" option —
its connected apps are curated integrations. Google's **Gemini CLI** (a local
terminal agent) does support local MCP servers over stdio/HTTP and works with
the configurations above.

**Recommendation:** For real clinical work, use a local client with a local
model (for example LM Studio) so prompts, project metadata, and preview images
never leave the workstation. Local clients with hosted models (Cursor, Claude
Desktop, Gemini CLI) still send conversation content to their model providers,
so use them with test data for demos unless your organisation has approved
that data flow.

### Server logs (two different files)

- **MCP server output:** When you start `rsna-anonymizer --mcp …` yourself, the server writes to that terminal's stderr. No file named `mcp_server.log` is created automatically.
- **Application log:** Starting the executable also initializes the normal Anonymizer rotating log at `~/Documents/RSNA Anonymizer/logs/anonymizer.log`. Application records overlap with stderr.

### What the model sees

Per the [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools):

1. **`initialize`** — server instructions (API howto + selectors)
2. **`tools/list`** — each tool’s `name`, `description`, and `inputSchema`
3. **`tools/call`** — plain text results (`list_inventory` is a TSV table; other tools return compact JSON or `error: …`)

Tool groups: guidance (`anonymizer_usage`), jobs (`job_status`), session (`list_projects`, `project_settings_defaults`, `create_project`, `project_open`, `project_info`, `update_project_settings`), local ingest (`import_directory`, `import_file`), PACS (`configure_remote`, `pacs_find`, `pacs_move`), inventory (`list_inventory`), process (`remove_pixel_phi`, `harmonize_studies`, `export_series_preview`). Full argument tables live in the server instructions asset shipped with the package (`anonymizer/mcp/assets/instructions.md`).

Long-running batch/AI tools (`import_directory`, `remove_pixel_phi`, `harmonize_studies`) run as background jobs: they return `status: "pending"` with a `job_id` immediately, and the client polls `job_status` until the job completes — so multi-minute work no longer hits client request timeouts.

Always pass `arguments` (use `{}` for zero-argument tools). Do not invent client result markers such as `TOOL_RESULT` / `END_TOOL_RESULT`.

### How clinicians should phrase requests

Local tool-trained models work best with **complete field values in one message**. Copy-ready examples (create, DIMSE/DICOMweb, import, inventory):

→ **[How to talk to the Anonymizer MCP](mcp-user-instructions.md)**

### Interactive project setup (MCP)

You can create and tune a project through chat (no prior GUI create required for MCP-only workflows):

1. Give a project name and any settings that matter. The server prepares the complete configuration (your choices combined with defaults) and returns it for review; nothing is created yet.
2. Change any setting and review the revised configuration, or confirm the exact revision to create/open the project.
3. For PACS remotes, give **DIMSE or DICOMweb** plus exact fields (`ip`, `port`, `aet`, …) before `configure_remote` — see the user guide above.
4. Later edits use `project_info` → `update_project_settings` (modalities, transfer syntaxes, local SCP, timeouts, confidentiality_options). Identity fields (`project_name`, `site_id`, `uid_root`, storage path) and the language chosen at creation stay fixed after create — the language is picked once, like the desktop welcome-screen selector, and is not part of the Settings dialog.
5. To learn the workflow in chat, ask: “How do I create a new project and change its settings later? Do not create anything yet.”

Field ranges match the desktop GUI (ports 104–65535, name/site/UID lengths, timeout maxes). Invalid values are rejected.

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

Gradio UI (`gradio` is in the `medgemma-chat` group):

```bash
uv sync --extra mcp --group medgemma-chat
uv run python -m prototyping.medgemma_chat \
  --model /path/to/medgemma_hf_weights \
  --mcp-url http://127.0.0.1:8000/mcp \
  --ui gradio
```

Full flags: [`src/prototyping/medgemma_chat/README.md`](https://github.com/RSNA/anonymizer/blob/dev/src/prototyping/medgemma_chat/README.md).

## Prerequisites

- For receive / AI batch (`-c`): project already created ([Create a project](../05-create-project/index.md) or via MCP `create_project`).
- For MCP-only: create/open projects with tools after connect (interactive setup wizard in server instructions).
- Models and face license already set up on **this machine** ([AI Features setup](../03-ai-features-setup/index.md)).
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
    Desktop steps: [Run on many studies](../08-process/05-run-on-many-studies/index.md). Headless uses the same AI tools with a JSON recipe.

## Next steps

1. [Troubleshooting](../troubleshooting.md) if something fails
2. Back to [Home](../index.md) for the full chapter list
