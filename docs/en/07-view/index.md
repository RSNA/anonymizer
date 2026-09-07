# View

Dashboard **View** opens the **Dataset** — the list of everything in your project (patients, studies, and series). From Dataset you open **study projections** or a full **Series View** to review pixels and run Process tools.

(Earlier versions called Dataset the PHI Index.)

## Goal

See what you imported, check AI status columns, open projections for a study, and open a series for review or [Process](../08-process/) tools.

## Demo studies

After importing from `tests/controller/assets/test_dcm_files` (see [Search](../06-search/)), Dataset should list multiple studies, including:

| Fixture | Role in the manual |
| --- | --- |
| **`davidson_cxr`** | Open in Series View here; burned-in text in [Remove Pixel PHI](../08-process/02-remove-burned-in-text/) |
| **`Brain_Ax_EarlyArt`** | [Harmonize](../08-process/03-harmonize-names/) and [Face blur](../08-process/04-blur-faces/) |
| Synthetic CT / US folders | Extra rows so the tree shows a realistic multi-study list |

## Open Dataset

1. From the Dashboard, click **View**.
2. Expand a **study** row (triangle) to see nested **series**.
3. Note PHI / anonymized IDs and the AI status columns.

![Dataset tree with test studies](shots/macos/Dataset.png)

### Columns (V19)

| Status | Meaning |
| --- | --- |
| **Harmonized** | Series description standardized (or study-level description applied) |
| **Face blur** | Face de-identification applied |
| **Pixel PHI** | Burned-in text scan / removal recorded |

## Right-click in Dataset (most important)

Hover tips on the tree say what a right-click will do. Selection follows the row under the pointer.

### Right-click a **study** → View Projections

Right-click a **study** row (not a nested series) to open **Projection View** for that study.

- You see summary projection images for the series in the study (useful to scan a multi-series exam quickly).
- Click a projection tile when you want to jump into full **Series View** for that series.
- You can also select one or more studies and use the **View Projections** button in the Dataset toolbar.

![View Projections for a selected study](shots/macos/ViewProjections.png)

### Right-click a **series** → Series View

1. Expand the study that contains the series (for example `davidson_cxr`).
2. **Right-click the series row** (not the study row).
3. **Series View** opens and loads the images.

That is the main way to open a series for review and for Process tools (Remove Pixel PHI, Harmonize, Face blur).

![Series View on davidson_cxr](shots/macos/SeriesView_Review.png)

## Series View — what you can do

Series View is where you look at pixels and run per-series tools (models must be ready — see [AI Features setup](../03-ai-features-setup/)):

- Scroll frames; use the histogram and toolbars as needed
- **Detect / remove burned-in text** (OCR) and whitelist editing → [Remove Pixel PHI](../08-process/02-remove-burned-in-text/)
- **Harmonize Description** → [Harmonize names](../08-process/03-harmonize-names/)
- **Face blur** (when eligible) → [Blur faces](../08-process/04-blur-faces/)
- **Segmentation latch** overlays from cached anatomy masks (after Harmonize)
- Manual blackout rectangles
- Clear analysis cache (does not by itself rewrite DICOM pixels)

Inside Series View, multi-frame series can also show **slice / min / mean / max** projection modes in the viewer. That is separate from Dataset’s study-level **View Projections** window.

## Other Dataset actions

- Select studies for [AI Batch Process](../08-process/05-run-on-many-studies/) or [Send](../09-send/)
- Spot-check AI status columns after Series View or batch runs

## What good looks like

- Nested study → series tree matches what you imported.
- Right-click study opens projections; right-click series opens Series View.
- `davidson_cxr` loads and scrolls in Series View.
- AI columns update after Process tools.

## If it fails

- Empty list → import first ([Search](../06-search/)).
- Series missing on disk → **Series Not Found**; re-import or check storage path.
- Tools greyed out in Series View → download models / accept license in [AI Features](../03-ai-features-setup/).
- Harmonize already running → finish or cancel the other series first.

## Next steps

Continue with [Process](../08-process/) — Remove Pixel PHI, Harmonize, Face blur, and batch.
