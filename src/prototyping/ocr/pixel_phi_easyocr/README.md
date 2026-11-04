# Pixel PHI EasyOCR sweep (MIDI-B corpus)

Tune EasyOCR `readtext` kwargs against **all** `pixel_phi` gold boxes
(validation + test, 62 cases). Target: **≥95% case accuracy** without making
every product OCR scan more expensive.

## Efficiency rule

Product non-US baseline already pays for `rotation_info=[90,270]` (~3× recog on
found boxes) with `canvas_size≤1200`, `mag_ratio=1`. Relative cost:

` (canvas/1200) * mag_ratio² * (1 + len(rotation_info)) `

Prefer configs with **`relative_cost ≤ ~3.0–3.5`**. Avoid raising `mag_ratio` or
`canvas_size` unless a cheap knob cannot hit 95%. Prefer **dropping** TTA when
accuracy holds.

## Commands

```bash
# Current product defaults on full corpus
uv run python -m prototyping.ocr.pixel_phi_easyocr eval

# Cheap-first grid (one frame in RAM at a time; MPS cache cleared per image)
uv run python -m prototyping.ocr.pixel_phi_easyocr sweep

# Single FTA smoke case
uv run python -m prototyping.ocr.pixel_phi_easyocr run
```

Outputs: `PIXEL_PHI_EASYOCR_EXPERIMENT.md`, `out/eval_latest.json`,
`out/sweep_corpus/best_params.json`.

## Focused FTA / R deskew

Diagonal initials are not helped by product `rotation_info` (90/180/270 only).
Crop the gold box and fine-deskew:

```bash
uv run python -m prototyping.ocr.pixel_phi_easyocr initials
```

On MIDI-B `113575183`, FTA appears at **+15°** on the gold crop; **R+FTA** at
**+30°…+60°** on a wider top-left crop. Full-frame still misses FTA. Merge
candidate: cheap **local** fine-angle TTA on free-form / short-marker crops —
not heavier full-image 90° TTA.

## Merge back

Copy non-empty `easyocr` keys from `best_params.json` into
`detect_text._easyocr_readtext` only when cost stays at or below baseline.
Re-check US (no rotation) as a control. For FTA-class markers, prefer the
`initials` deskew path over raising global `mag_ratio` / canvas.
