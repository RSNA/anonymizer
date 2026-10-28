# 8.4 Run on many studies

**AI Batch Process** runs the same tools from chapters 8.1–8.3 across selected studies from the Dataset—without opening each series by hand.

## Demo studies

Use the same fixtures you practiced one-at-a-time:

| Tool in batch | Fixture to include |
| --- | --- |
| Embedded PHI (Pixel / Metadata / Reports) | **`davidson_cxr`**, **`demo_report_pdf`** |
| Harmonize + Face blur | **`CT_Head_With_Contrast`** |

Import those studies (or the full repository tree `tests/controller/assets/test_dcm_files/` — [GitHub](https://github.com/RSNA/anonymizer/tree/dev/tests/controller/assets/test_dcm_files); [how to get them](../../06-search/index.md#demo-studies-from-the-repository)), open **Dataset**, select them, then start AI Batch Process.

## Goal

Process a cohort for burned-in text, Harmonize, and/or face blur with progress and a summary.

## Before you start

1. Import the demo series above (and any other studies you need).
2. Finish [AI Features setup](../../03-ai-features-setup/index.md) for every tool you will run.
3. Prefer the [site workflow](../index.md#recommended-site-workflow): validate Harmonize / description mappings, face-blur mode, modality whitelists, Metadata Detect PHI, and report NER on sample series in Series View **before** batching the whole Dataset.

## Start a batch

1. Open **Dataset** and select studies (include `davidson_cxr` and `CT_Head_With_Contrast` for a full demo).
2. Start **AI Batch Process**.
3. In options, choose algorithms:
   - Embedded PHI — Pixel (blackout vs blend; **Remove Scope**; optional **Enable Exclude Areas**), Metadata, Reports — exercises `davidson_cxr` / report fixtures
   - Harmonize (workstation CT/MR resolution from AI Features) — exercises `CT_Head_With_Contrast`
     - **Prefer description mappings (skip AI when matched)** (default on): when a saved original→harmonized mapping matches, apply it and skip the anatomy model for that series
   - Face blur (**Gaussian** to match chapter 8.3) — exercises `CT_Head_With_Contrast`
4. Preview modality whitelists with **View whitelist**. Tick **Enable Exclude Areas** if Series View **Save Changes** stored exclude areas.
5. Confirm memory warning if shown, then start.

![AI Batch options](shots/macos/AiBatchOptions.png)

## Order of work

For each series, selected tools run in a stable order (pixel PHI → Harmonize → face blur) so memory use stays predictable.

## During the run

- Progress shows study / series / phase.
- Cancel stops after the current step when possible.
- Low memory can abort with a clear warning.
- Already-processed series are skipped by default.

![AI Batch Process running](shots/macos/AiBatchRunning.png)

## Afterward

- Read the summary (completed / skipped / failed).
- Spot-check Series View on `davidson_cxr` and `CT_Head_With_Contrast` before export.
- Same job on a **server without a window** → [Run headless](../../10-headless/index.md).

## What good looks like

- Summary matches expectations; Dataset AI columns updated for the demo studies.
- Log file has detail for any skips.

## If it fails

- Features not ready → [AI Features](../../03-ai-features-setup/index.md).
- No series for selection → check Dataset selection.
- Insufficient memory → close other apps or process fewer studies.

## Next steps

Continue with [Send](../../09-send/index.md) to export anonymized studies (or [run headless](../../10-headless/index.md) for server batch).
