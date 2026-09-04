# Look at images

## Goal

Review a series from the Dataset before or after Process tools.

## Demo series

**`davidson_cxr`** — `tests/controller/assets/test_dcm_files/davidson_cxr`.

Open it from the Dataset tree (double-click / Series View). The same series is used later for [7.2 Remove burned-in text](../07-process/02-remove-burned-in-text/).

## Series View

1. In Dataset, expand the study that contains `davidson_cxr` and open **Series View**.
2. Scroll frames; use the histogram and toolbars as needed.
3. Confirm OCR / Harmonize / Face tools enable only when models are ready ([7.1 AI Features setup](../07-process/01-ai-features-setup/)).

![Series View on davidson_cxr](shots/SeriesView_Review.png)

Series View includes:

- **Detect / remove burned-in text** (OCR) and whitelist editing
- **Harmonize Description**
- **Face blur** (when eligible)
- **Segmentation latch** overlays from cached anatomy masks
- Manual blackout rectangles
- Clear analysis cache (does not by itself rewrite DICOM pixels)

## Projections

**View Projections** shows summary images for a series. Single-frame color ultrasound is converted for display when needed.

## What good looks like

- `davidson_cxr` image loads and scrolls.
- Tools enable when models are ready.
- After OCR detect (chapter 7.2), green rectangles mark text.

## If it fails

- Tools greyed out → download models / accept license in AI Features.
- Harmonize already running → finish or cancel the other series first.
- Projection issues on color ultrasound → use a current V19 build.
