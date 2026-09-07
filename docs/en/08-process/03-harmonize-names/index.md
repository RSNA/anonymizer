# 8.2 Harmonize names

Research datasets often use inconsistent **Series Description** text. **Harmonize** suggests a standard name from anatomy and contrast (RSNA Radiology Playbook / RadLex style). It does **not** change pixels.

## Demo series

**`Brain_Ax_EarlyArt`** — `tests/controller/assets/test_dcm_files/Brain_Ax_EarlyArt` (non-synthetic head CT).

Import this series, open it in **Series View**, then run Harmonize. The same series is used again in [8.3 Blur faces](../04-blur-faces/).

## Goal

On `Brain_Ax_EarlyArt` in Series View: run **Harmonize Description**, answer the brain-structures prompt when offered, Apply, then review segmentation overlays on the middle slice.

## Before you start

1. Complete [AI Features setup](../../03-ai-features-setup/) — Harmonize CT pack, resolution, and Brain structures.
2. Import **`Brain_Ax_EarlyArt`** ([Search](../../06-search/)) and open that series in **Series View** ([View](../../07-view/) — right-click the series row).

## Workflow on `Brain_Ax_EarlyArt`

### 1. Harmonize Description (from Series View)

1. With `Brain_Ax_EarlyArt` open in **Series View**, click **Harmonize Description**.
2. Wait until analysis finishes — the **Playbook harmonization** table fills with anatomy / contrast evidence (not an empty table mid-progress).
3. Review the suggested Series Description, then **Yes** to apply, or **No** / **Cancel**.

The Series View remains behind the dialog so you keep context for the open series.

![Series View with completed Harmonize Description results](shots/macos/Process_Harmonize_Description.png)

### 2. Brain structures prompt

On a CT head series, Harmonize asks whether to run **detailed brain structure segmentation** before the job continues:

1. Read the **Brain structures** Yes/No message (academic license / models required — see [AI Features](../../03-ai-features-setup/)).
2. Choose **Yes** to include brain structures in this run, or **No** for standard anatomy only.

![Harmonize Description with brain structures prompt](shots/macos/Process_Harmonize_BrainPrompt.png)

### 3. Segmented Series View

After you Accept a Harmonize run that included brain structures (**Yes** on the prompt):

1. Series View shows latch buttons for whole **brain** plus detailed structures (brainstem, lobes, ventricles, …) when the licensed pack ran.
2. Select **all** structures you want to review (including **brain**).
3. Go to the **middle slice** to see overlays on a representative frame.

![Series View with all brain segments on the middle slice](shots/macos/Process_Harmonize_SegmentedSeries.png)

## Notes (same as production use)

- Scouts, MIP/VR, dose reports, and similar series are usually skipped.
- **CT:** anatomy segmentation + contrast phase when models allow.
- **MR:** anatomy from MR packs; IV contrast from DICOM headers.
- After the last CT series in a study is harmonized, a **LOINC study description** may be suggested.
- Results cache under the series folder — **Clear Analysis Cache** for a fresh run.
- Batch: [8.4 Run on many studies](../05-run-on-many-studies/) (resolution comes from AI Features, not per batch).

## What good looks like

- SeriesDescription looks consistent for this head CT.
- Dataset **Harmonized** column updates.
- After brain Yes: latch buttons appear and overlays draw on the middle slice.

## If it fails

- Not suitable series → expected skip.
- Already harmonized → Clear Analysis Cache to re-run.
- Models not ready → [AI Features](../../03-ai-features-setup/).

## Next steps

Continue with [8.3 Blur faces](../04-blur-faces/) on the **same** `Brain_Ax_EarlyArt` series (Gaussian).
