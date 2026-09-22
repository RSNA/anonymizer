# View

Dashboard **View** opens the **Dataset** — the list of everything in your project (patients, studies, and series). From Dataset you open **study projections** or a full **Series View** to review pixels and run Process tools.

(Earlier versions called Dataset the PHI Index.)

## Goal

See what you imported, check AI status columns, open projections for a study, open a series for review or [Process](../08-process/) tools, and export a **Patient Lookup** CSV when needed.

## Demo studies

After importing from `tests/controller/assets/test_dcm_files` (see [Search](../06-search/)), Dataset should list these three studies (help shots do **not** use synthetic phantoms):

| Fixture | Role in the manual |
| --- | --- |
| **`davidson_cxr`** | Open in Series View here; burned-in text in [Remove Pixel PHI](../08-process/02-remove-burned-in-text/) |
| **`CT_Head_With_Contrast`** | [Harmonize](../08-process/03-harmonize-names/) and [Face blur](../08-process/04-blur-faces/) |
| **`us_rgb_single_frame`** | Ultrasound single-frame; burned-in overlays in [Remove Pixel PHI](../08-process/02-remove-burned-in-text/) (exclude-area demos) |

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

**Left-click** the study or series **description** (first column) when a single row is selected — see [Edit study and series descriptions](#edit-study-and-series-descriptions) below. Use **Shift** or **Cmd/Ctrl+Click** to multi-select; then **right-click** the selection to set one description on all selected rows.

### Right-click a **study** → View Projections

Right-click a **study** row (not a nested series) to open **Projection View** for that study.

- You see summary projection images for each series in the study (useful to scan a multi-series exam quickly).
- Click a projection tile when you want to jump into full **Series View** for that series.

![View Projections for a selected study](shots/macos/ViewProjections.png)

### Multiple studies → View Projections

To browse several exams at once:

1. In Dataset, select two or more **study** rows (Shift+Click and/or Cmd/Ctrl+Click), or use **Select All**.
2. Click **View Projections** in the Dataset toolbar.

The window title becomes **View N Studies with M Series** (and **over P Pages** when the grid needs paging). Each series still gets one projection tile.

![View Projections for multiple selected studies](shots/macos/ViewProjections_Multi.png)

### Projection tiles, S / M / L, and how they are built

Each tile is a strip of **three** preview images for one series:

| Series type | Left | Center | Right |
| --- | --- | --- | --- |
| **Multi-frame** (e.g. CT stack) | **Min** intensity across frames | **Mean** | **Max** |
| **Single-frame** (e.g. CXR, many US) | Grayscale | **CLAHE** contrast | **Edge** (Canny) |

The **S / M / L** control sets how large each of those three panels is drawn (before display scaling):

| Size | Tile panel size | Typical use |
| --- | --- | --- |
| **S** | 200×200 | Fit many series on one page |
| **M** | 400×400 | Default help / review size |
| **L** | 800×800 | Inspect anatomy in the strip |

Changing size recalculates how many tiles fit per page and may add a page slider. Click any tile to open that series in **Series View**.

**What happens when a projection is created**

1. The app looks for a cached `Projection.pkl` next to the series files.
2. On a cache hit, it loads that object and draws the three images (resized to S/M/L).
3. On a miss, it loads every frame in the series, computes the three images above (windowed for multi-frame), writes `Projection.pkl`, then draws the tile.
4. Pixel edits that change the series on disk invalidate the cache so the next open rebuilds from current pixels.

This Dataset **View Projections** window is separate from the slice / min / mean / max modes inside Series View.

### Right-click a **series** → Series View

1. Expand the study that contains the series (for example `davidson_cxr`).
2. **Right-click the series row** (not the study row).
3. **Series View** opens and loads the images.

That is the main way to open a series for review and for Process tools (Remove Pixel PHI, Harmonize, Face blur).

![Series View on davidson_cxr](shots/macos/SeriesView_Review.png)

## Edit study and series descriptions

After [Harmonize](../08-process/03-harmonize-names/) (Series View or [AI Batch](../08-process/05-run-on-many-studies/)), green **Harmonized** rows show the standardized name. You can also set RadLex / LOINC names on **unharmonized** rows from Dataset — choosing a standard name writes DICOM and marks the row harmonized (green after refresh).

Hover tooltips explain what a click or toolbar action will do (including why a button is disabled).

**Single-click** selects a row. **Double-click** a study or series description (harmonized or not) to open **Set description**. **Esc** or click away cancels an open inline menu. **Shift+Click** and **Cmd/Ctrl+Click** only change selection — they do not open the editor. With several series or studies selected (same modality), **right-click** the selection to open **Set description**.

### Series description (RadLex)

1. Expand the study and **double-click** the **series** description in the first column (one row selected).
2. Choose a RadLex / Playbook-style name for **that modality** (for example XR views: Chest AP → PA / Lat / Obl / 2V; CT/MR: plane or contrast swaps).
3. The tree refreshes when you pick a value.

![Dataset series description dropdown (RadLex)](shots/macos/Dataset_EditDescription.png)

### Study description (LOINC)

1. **Double-click** the **study** description in the first column (the parent row).
2. Choose a **LOINC** Long Common Name for **that modality prefix** (XR / US / MG / CT / MR). Each option is shown as `Long Common Name  (LoincNumber)`.
3. The list is ranked from the study’s harmonized series names when available (and view count for CXR when known), then padded from the same modality’s LOINC catalog.
4. Applying a choice updates Study Description (and Procedure Code Sequence when a LOINC number is present).

![Dataset study description dropdown (LOINC)](shots/macos/Dataset_EditStudyDescription.png)

### Set description (group edit)

1. Select **only series** or **only studies**, all with the same modality cohort.
2. **Right-click** any selected row and pick one RadLex (series) or LOINC (study) value.
3. That exact string is applied to every selected row. Hover tips change in multi-select mode to say so.

### Select Similar

With a **single** study or series selected, **Select Similar** adds other rows that already share the same series descriptions (studies) or the same series description text (series). Then right-click the selection to set one description on all selected rows.

## Series View — what you can do

Series View is where you look at pixels and run per-series tools (models must be ready — see [AI Features setup](../03-ai-features-setup/)):

- Scroll frames; zoom and pan the viewport; adjust window/level
- **Detect / remove burned-in text** (OCR) and whitelist editing → [Remove Pixel PHI](../08-process/02-remove-burned-in-text/)
- **Harmonize Description** → [Harmonize names](../08-process/03-harmonize-names/)
- **Face blur** (when eligible) → [Blur faces](../08-process/04-blur-faces/)
- **Segmentation latch** overlays from cached anatomy masks (after Harmonize) — see [Annotation](#annotation) below
- Manual blackout rectangles (left-drag in **View** mode)
- Clear analysis cache (does not by itself rewrite DICOM pixels)

Inside Series View, multi-frame series can also show **slice / min / mean / max** projection modes in the viewer (same idea as the multi-frame strip above, but for interactive scrolling).

Open a series as described above ([Right-click a series → Series View](#right-click-a-series--series-view)); the review chrome is shown there (`SeriesView_Review.png`). After Harmonize with brain structures accepted, latch chips and overlays appear on the right — see the segmented middle-slice shot in [Harmonize names](../08-process/03-harmonize-names/#3-segmented-series-view) (`Process_Harmonize_SegmentedSeries.png`). Dedicated Annotate / zoom help shots are not captured yet; use the tables below until those land.

### Mouse and keyboard (viewport)

Bindings follow a PACS-style map: left button is the active tool, right button is window/level, wheel changes slices (or brush size in Annotate). Zoom and pan are modifiers so they never steal the tool button.

| Input | Action |
| --- | --- |
| **Mouse wheel** | Change slice / frame (View). In **Annotate**, change **brush size**; hold **Shift** + wheel to change slice instead |
| **Ctrl+wheel** (Windows/Linux) or **Cmd+wheel** (macOS) | Zoom in / out toward the pointer |
| **Middle mouse** drag | Pan when zoomed |
| **Double-click middle mouse** | Fit image to the viewport (reset zoom and pan) |
| **Shift+left-drag** | Pan (same as middle-mouse drag) |
| **Right-drag** | Window/level — vertical = brightness (WL), horizontal = contrast (WW) |
| **Left-click / left-drag** | **View:** draw or remove blackout / OCR boxes. **Annotate:** paint or erase on the selected segment |
| **Fit** button or **F** | Reset zoom and pan to fit the viewport |
| **← / →** | Previous / next frame |
| **↑ / ↓** | Jump by a small number of frames |
| **Page Up / Page Down** | Jump by a larger number of frames |
| **Home / End** | First / last frame |
| **Space** | Play / pause cine (multi-frame series) |

Zoom uses nearest-neighbor magnification so voxel edges and 1 px segment outlines stay crisp for accurate brush work. Fit at 1× still uses smooth resampling for comfortable review.

### Annotation

ROI annotation works once the series has a voxel grid for labels (from Harmonize cache, or created automatically when you annotate / import). The **Segmentation** panel shows TotalSegmentator structure chips (after Harmonize) and **user segments** you create or import.

#### Import Segments (research NIfTI / NRRD)

Use **Import…** to bring masks from tools researchers already use. Files land as user chips (same store as **New Segment**) for View latch and Annotate.

| Source tool | Export like this | Import preset |
| --- | --- | --- |
| **3D Slicer** / **MITK** | Labelmap as `.nii` / `.nii.gz` / `.nrrd`, or one binary volume per segment | Auto-detect or Multi-label / Binary masks |
| **ITK-SNAP** | Segmentation image + **Label Descriptions** (`.label` / `.txt`) beside it | ITK-SNAP (+ .label) |
| **TotalSegmentator** | Output folder of `structure.nii.gz`, or `--ml` multi-label NIfTI | TotalSegmentator folder, or Multi-label |
| **nnU-Net** | `labelsTr/case.nii.gz` + `dataset.json` (`labels` name→int) | nnU-Net (+ dataset.json) |
| **This app** | ML bundle `labels.nii.gz` + `label_map.json` | Auto-detect |

Volumes that do not match the series grid are nearest-neighbor resampled. Import merges with existing user labels (new ids); it does not overwrite TotalSegmentator `seg/` masks.

#### View vs Annotate

| Mode | Purpose |
| --- | --- |
| **View** | Review overlays. Click chips to **multi-select** (latch) any combination of TotalSegmentator structures and user segments. Outlines draw for every latched chip. Left-drag draws blackout rectangles, not paint. |
| **Annotate** | Edit labels. Only the **selected paint target** is drawn. Brush / Erase / size / Undo appear. Left-drag paints. Leaving Annotate restores your previous View multi-select. |

Use **View** / **Annotate** in the Segmentation header to switch. **Esc** cancels an in-progress stroke, or returns to View if you are not painting.

#### Paint workflow

1. Open a CT/MR series that has been Harmonized (structure chips visible).
2. Click **Annotate**.
3. Select the paint target: click a chip, or press **1–9** for the first nine chips in the list.
4. Optional: **New Segment** to create a named user label, or **Import…** for external NIfTI/NRRD (see table above).
5. Choose **Brush** or **Erase** (or **B** / **E**). Adjust size with **− / +**, **[ / ]**, or the mouse wheel.
6. Left-drag on the image. A cyan ring shows the brush footprint (canvas overlay — not part of the pixel paint).
7. Scroll slices with **Shift+wheel** (or the scrollbar / arrow keys). Zoom with **Ctrl/Cmd+wheel**; pan with middle-mouse or **Shift+left-drag**.
8. **Undo** or **Ctrl/Cmd+Z** reverts the last stroke. Strokes save automatically into the series annotate session.

| Input (Annotate) | Action |
| --- | --- |
| **Brush** / **B** | Paint the selected label |
| **Erase** / **E** | Remove paint from the selected label |
| **− / +** or **[ / ]** | Smaller / larger brush (1–64 px in image space) |
| **Mouse wheel** | Nudge brush size |
| **Shift+wheel** | Change slice while keeping Annotate mode |
| **1–9** | Select paint target by chip order |
| **New Segment** | Create a user segment and select it for painting |
| **Import…** | Import NIfTI/NRRD segments from Slicer, ITK-SNAP, TotalSegmentator, nnU-Net, etc. |
| **Undo** / **Ctrl+Z** / **Cmd+Z** | Undo last stroke |
| **Esc** | End stroke, or leave Annotate → View |

**View** multi-select vs **Annotate** exclusive target: in View you can latch brain + ventricles + a user ROI together for review; in Annotate only the chip you are editing is outlined so paint stays unambiguous.

User segments and TotalSegmentator edits persist with the series cache. Clearing analysis cache can offer to keep or delete ROI annotations. Export can include segments as DICOM-SEG when that option is enabled on project export.

## Other Dataset actions

- Select studies for [AI Batch Process](../08-process/05-run-on-many-studies/) or [Send](../09-send/)
- Spot-check AI status columns after Series View or batch runs
- **Create Patient Lookup** CSV (below)

## Create Patient Lookup CSV

Use Dataset to export a spreadsheet that maps PHI identifiers to anonymized IDs (and series AI status). This is separate from the optional [CTP Patient Lookup Table](../05-create-project/#patient-lookup-table) used at import time.

### When to use it

- Hand a mapping file to the receiving site or study coordinator
- Audit which series were harmonized, face-blurred, or had pixel PHI removed
- Keep a durable copy under the project’s private storage

### Steps

1. Open **Dataset** from the Dashboard (**View**).
2. Click **Create Patient Lookup** in the Dataset toolbar (no study selection required — the CSV covers the whole project index). Prefer exporting after [Process](../08-process/) so AI status columns are populated.

![Dataset with Create Patient Lookup](shots/macos/Dataset_CreatePatientLookup.png)

3. On success, a dialog shows the saved path. Files are written under:

   `…/<project>/private/phi_export/`

   Filename pattern:

   `{site_id}_{project_name}_PHI_{patients}_{studies}_{series}.csv`

4. Open the CSV in a spreadsheet. **One row per series** (study and patient fields are repeated on each series row). Studies with no series still emit one row with empty series columns. Help examples use **davidson CXR**, **CT head** (`CT_Head_With_Contrast`), and **ultrasound single-frame** (not synthetic phantoms).

![Patient Lookup CSV preview](shots/macos/Dataset_PatientLookup_CSV.png)

### Columns (summary)

| Group | Examples |
| --- | --- |
| Anonymized IDs | `ANON-PatientID`, `ANON-PatientName`, `ANON-StudyUID`, `ANON-SeriesUID`, `ANON-AccNo` |
| PHI counterparts | `PHI-PatientName`, `PHI-PatientID`, `PHI-StudyDate`, `PHI-StudyUID`, `PHI-AccNo` |
| Study / series | `DateOffset`, `Series`, `StudyInstances`, `Modality`, `SeriesDescription`, `Instances` |
| AI status | `SeriesHarmonized`, `FaceBlurred`, `PixelPHIRemoved`, `PixelPHI` |

## What good looks like

- Nested study → series tree matches what you imported (`davidson_cxr`, `CT_Head_With_Contrast`, `us_rgb_single_frame`).
- Right-click study opens projections; multi-select + **View Projections** opens all selected studies; right-click series opens Series View; multi-select + right-click opens **Set description**.
- Double-clicking a **series** or **study** description (single selection) opens RadLex / LOINC **Set description**; single-click only selects the row; modifier clicks keep multi-select.
- **S / M / L** changes tile size; first open may build `Projection.pkl` under each series.
- `davidson_cxr` loads and scrolls in Series View; Ctrl/Cmd+wheel zooms, middle-mouse or Shift+left-drag pans, **F** / **Fit** resets.
- After Harmonize on CT/MR, **View** multi-latches overlays and **Annotate** paints one selected segment (Brush / Erase, wheel for size).
- AI columns update after Process tools.
- **Create Patient Lookup** writes a CSV under `private/phi_export/` that opens with the expected columns.

## If it fails

- Empty list → import first ([Search](../06-search/)).
- Series missing on disk → **Series Not Found**; re-import or check storage path.
- Tools greyed out in Series View → download models / accept license in [AI Features](../03-ai-features-setup/).
- Harmonize already running → finish or cancel the other series first.
- Create Patient Lookup error → ensure the project has studies in the Dataset index and that `private/phi_export/` is writable.

## Next steps

Continue with [Process](../08-process/) — Remove Pixel PHI, Harmonize, Face blur, and batch. After review, [Send](../09-send/) anonymized patients.
