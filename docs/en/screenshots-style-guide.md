# Screenshots style guide

For authors updating this manual.

## Capture rules

- **Theme:** light mode
- **Language:** capture UI in English (`en_US`) while finalizing the English manual
- **PHI:** test fixtures only — never real patient data
- **Storage:** screenshots live **inside** each numbered workflow directory as `shots/*.png`
- **Catalog:** [`docs/screenshots-manifest.yaml`](../screenshots-manifest.yaml) lists every UX element and shot
- **Scale:** capture stores **logical UI points** (Retina 2× grabs are downscaled so 1 PNG pixel ≈ 1 app point). Dialogs then match live app size next to body text; do not upscale in Markdown.
- **Corners:** macOS uses window-ID capture (`screencapture -l`) so PNGs keep rounded corners and alpha

## Workflow folders

```
docs/en/02-install/shots/
docs/en/03-ai-features-setup/shots/
docs/en/05-create-project/shots/
docs/en/06-search/shots/
docs/en/07-view/shots/
docs/en/08-process/02-remove-burned-in-text/shots/   # davidson_cxr
docs/en/08-process/03-harmonize-names/shots/         # Brain_Ax_EarlyArt
docs/en/08-process/04-blur-faces/shots/              # Brain_Ax_EarlyArt Gaussian
docs/en/08-process/05-run-on-many-studies/shots/
docs/en/09-send/shots/
```

Markdown embeds: `![…](shots/Welcome.png)` (path relative to the chapter).

## Automated capture

Requires a desktop display **with Screen Recording granted** to the terminal/Cursor process; Orthanc on `127.0.0.1:4242` (AE `ORTHANC`) for Search/Query shots. If `screencapture` returns a blank image, re-grant Screen Recording and re-run with `--force`.

```bash
uv run python src/prototyping/capture_help_screenshots.py --language en_US
uv run python src/prototyping/capture_help_screenshots.py --language en_US --force
```

- **Resume by default** (`--skip-existing`); use `--force` or `--force-shot ID` to redo
- Process demos use **non-synthetic** fixtures only:
  - **8.1** Remove Pixel PHI → `davidson_cxr` (whitelist → Frame → Detect → Remove)
  - **8.2** Harmonize → `Brain_Ax_EarlyArt` (Harmonize Description → Segment Brain Features)
  - **8.3** Face blur → `Brain_Ax_EarlyArt` (Gaussian)
  - **8.4** Batch → both fixtures selected in Dataset
- Soft-fail AI-heavy Process shots when models are missing
- Hard-fail Orthanc-dependent Search shots when C-ECHO fails

## Priority shots (V19)

Welcome; AI Features; Create project settings (+ subdialogs); Dashboard; Search; View (Dataset + Series); Process (Remove Pixel PHI, Harmonize, Face, batch); Send.
