# Screenshots style guide

For authors updating this manual.

## Capture rules

- **Theme:** light mode
- **Language:** capture UI in English (`en_US`) while finalizing the English manual
- **PHI:** test fixtures only — never real patient data
- **Storage:** screenshots live under each numbered workflow as `shots/macos/*.png` and `shots/windows/*.png`
- **Catalog:** [`docs/screenshots-manifest.yaml`](../screenshots-manifest.yaml) lists every UX element and shot
- **Scale / resolution:** capture stores **logical UI points** (Retina 2× → 1 PNG px ≈ 1 app pt), then `normalize_for_docs` forces every PNG to **`DOCS_SHOT_MAX_WIDTH`** (1200): wide windows downscale, narrow dialogs letterbox (no UI upscale). Same file width ⇒ same MkDocs scale ⇒ matching smallest UI text across pages.
- **No shadows:** macOS grabs use `screencapture -o` (omit window shadow); residual soft fringe is stripped before save. Do not ship shots with drop shadows.
- **Corners:** macOS uses window-ID capture (`screencapture -l`) so PNGs keep rounded corners and alpha; Windows uses PrintWindow of the HWND cropped to the DWM visible frame (not a screen BitBlt, which would include the desktop)

## Workflow folders

```
docs/en/02-install/shots/{macos,windows}/
docs/en/03-ai-features-setup/shots/{macos,windows}/
docs/en/05-create-project/shots/{macos,windows}/
docs/en/06-search/shots/{macos,windows}/
docs/en/07-view/shots/{macos,windows}/
docs/en/08-process/02-remove-burned-in-text/shots/{macos,windows}/
docs/en/08-process/03-harmonize-names/shots/{macos,windows}/
docs/en/08-process/04-blur-faces/shots/{macos,windows}/
docs/en/08-process/05-run-on-many-studies/shots/{macos,windows}/
docs/en/09-send/shots/{macos,windows}/
```

Markdown embeds the **macOS** path under the current language. Site JS swaps only
`shots/macos/` → `shots/windows/` for Windows visitors; if the Windows PNG is
missing, it falls back to the **same-language** macOS shot (never English):

`![…](shots/macos/Welcome.png)`

## Automated capture

Tooling lives in [`src/docs_help/`](https://github.com/RSNA/anonymizer/tree/dev/src/docs_help) (not the shipped app package).

**Developer-owned:** check out the latest code, run capture on **macOS** and again on **Windows**, then commit and push both PNG trees. There is no CI/cloud grab.

Requires a desktop display with screen-capture permission (macOS Screen Recording; Windows desktop access); Orthanc on `127.0.0.1:4242` (AE `ORTHANC`) for Search/Query shots. Capture stops any other Anonymizer GUI process before the first UI shot. If grabs are blank, re-grant capture permission and re-run with `--force`.

```bash
uv run python -m docs_help --language en_US
uv run python -m docs_help --language en_US --force
uv run python -m docs_help --language en_US --force --only Welcome
```

- Writes `docs/<lang>/<chapter>/shots/<os>/` where `<os>` is `macos` or `windows` (host OS; `--platform auto`)
- **Resume by default** (`--skip-existing`); use `--force` or `--force-shot ID` to redo
- Process demos use **non-synthetic** fixtures only:
  - **8.1** Remove Pixel PHI → `davidson_cxr` (black out) + `us_rgb_single_frame` (blend + Exclude Area under mindray)
  - **8.2** Harmonize → `CT_Head_With_Contrast` (Series View → completed results → brain prompt → segmented middle slice) + `davidson_cxr` / `us_rgb_single_frame` (planar Playbook sources)
  - **8.3** Face blur → `CT_Head_With_Contrast` (Gaussian)
  - **8.4** Batch → options + running dialog with both fixtures selected in Dataset
- Soft View / Dashboard demos:
  - **Metadata** → `davidson_cxr` Series View → Metadata tree / Detect PHI / Remove PHI (`MetadataAssessment`, `MetadataAssessment_DetectPHI`, `MetadataAssessment_RemovePHI`); Detect/Remove need Embedded PHI models
  - **Description Mappings** → Dataset toolbar dialog with seeded Series/Study rows (`DescriptionMappings`)
  - **Analytics** → after import; Dashboard expand Analytics board (`Dashboard_Analytics` under View); organ-volume tiles fill after Harmonize on CT/MR
  - Create project:
  - **De-identification Options** → New Project Settings → options dialog with Basic preset + Basic Profile help (`DeidentificationOptions`)
- Soft Process report demo:
  - **Report Text Review** → `demo_report_pdf` Encapsulated PDF (import with Clean Structured Content); optional Metadata from Report toolbar (`ReportTextReview`, `ReportTextReview_Metadata`)
- Pixel PHI Detect / Remove shots need EasyOCR models (AI Features Embedded PHI pack) — capture runs live Detect
- Soft-fail AI-heavy Process / Metadata Detect PHI / Report shots when models or document text are missing
- Hard-fail Orthanc-dependent Search shots when C-ECHO fails
- If a Windows PNG is missing, the published site falls back to the macOS image

## Priority shots (V19)

Welcome; AI Features; Create project (File → New Project menu on Welcome + settings + De-identification Options + Anonymizer Script Editor + Lookup Table); Dashboard; Search (File → Import menu on Dashboard is manual, like New Project menu); View (Dataset + Analytics after import + Description Mappings + series/study description edit + Projections + Series + Metadata Detect/Remove + Patient Lookup CSV); Process (Remove Pixel PHI, Report Text Review, Harmonize, Face, batch); Send (initial → selection → sending → sent).
