# T3 — Clean burned-in labels

## Goal
Spot burned-in text across a cohort, then detect and remove it on one series while keeping L/R markers.

## Steps
1. Ensure OCR models are ready in AI Features.
2. Optional cohort triage — Dataset **Select All** (or multi-select studies) → **View Projections**. Scan CLAHE / edge (planar) or max/mean (volume) tiles for names, dates, and IDs; click a tile to open Series View. See [View — Scan for pixel PHI](../07-view/index.md#scan-pixel-phi-with-projections).
3. Open Series View → set **Remove Scope** to **Non-whitelisted text** → **Detect**.
4. Click green rectangles to whitelist keepers → **Remove** → Save.

## Video
<!-- YouTube embed placeholder -->

See [Remove burned-in text](../08-process/02-remove-burned-in-text/index.md) and [How Detect decides](../08-process/02-remove-burned-in-text/index.md#how-detect-decides-pixel).
