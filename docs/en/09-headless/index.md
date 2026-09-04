# Run without the window (headless)

Use headless mode on a **lab or server** when you do not need the desktop window. Create and configure the project in the GUI first.

## Goal

- Keep receiving DICOM into an existing project, and/or
- Run AI batch once on that project, then exit.

## Two commands

### 1. Receive only (DICOM listener)

```bash
rsna-anonymizer -c path/to/ProjectModel.json
```

The app loads the project and listens for incoming images using the project’s local server settings.

### 2. AI batch once, then exit

```bash
rsna-anonymizer -c path/to/ProjectModel.json --ai-batch path/to/AiBatchConfig.json --ai-batch-run
```

Both `-c` / `--config` and `--ai-batch` are required with `--ai-batch-run`.

## What each file is for

| File | Purpose |
| --- | --- |
| **ProjectModel.json** | Site, project name, storage path, DICOM nodes, modalities, timeouts—the project definition. |
| **AiBatchConfig.json** | Which AI tools to run, blur/OCR modes, study selection (`all` or a list), optional CT/MR resolution overrides. |

Example AI batch config (also in the repo at `docs/examples/AiBatchConfig.json`):

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

## Prerequisites

- Project already created in the GUI ([Create a project](../04-create-project/)).
- Models and face license already set up on **this machine** ([AI Features setup](../07-process/01-ai-features-setup)).
- Enough free memory for the selected algorithms.

## What good looks like

- Receive mode: process stays running; new studies appear under storage / Dataset when you open the GUI later.
- Batch mode: log shows phases and a summary; process exits when finished (exit code 0 on success).

## Common failures

| Problem | What to check |
| --- | --- |
| `--ai-batch-run` without files | Provide both `-c` and `--ai-batch` |
| Feature gate errors | Download models / license on that workstation |
| Empty study list | Import data first, or fix `studies` in AiBatchConfig |
| Low memory | Reduce concurrent load; see [Troubleshooting](../troubleshooting.md) |

## For clinicians

Headless does **not** replace reviewing a sample in the Dataset or Series View. Use the GUI for first-time setup and quality checks; use headless for routine receive or overnight batch.

!!! tip "Same job as GUI batch"
    Desktop steps: [Run on many studies](../07-process/05-run-on-many-studies/). Headless uses the same AI tools with a JSON recipe.

## Next steps

1. [Troubleshooting](../troubleshooting.md) if something fails
2. [Tutorials](../tutorials/) for short walkthroughs
3. Back to [Home](../) for the full chapter list
