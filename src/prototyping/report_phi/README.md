# Report PHI experiment — **obsolete (PDF-image OCR)**

This harness swept **EasyOCR × OpenMed** on Encapsulated PDF **embedded letterhead images**. Product Report View no longer runs PDF-image OCR.

**Current product path (text-only):**

- PDF: `extract_pdf_layout` → `analyze_report_text` / `detect_pdf_hits` (native text layer + char boxes)
- SR: slot text → `analyze_report_text`
- NER: OpenMed + locale `PHONE_RE` only (`apply_guard=False`); see `report/report_ner.py`

Series View / `pixel_report` DICOM-frame OCR is unchanged (`REPORT_PIXEL_EASYOCR_OVERRIDES` still used there).

## Historical commands (frozen)

```bash
# Was: EasyOCR grid + gold score — do not use for product tuning
uv run python -m prototyping.report_phi run --out /tmp/report_phi_run
uv run python -m prototyping.report_phi sweep --grid sweeps/easyocr_openmed.json --out /tmp/report_phi_sweep
```

Gold and sweep JSON under `gold/` / `sweeps/` remain as archive for past letterhead experiments. Prefer product logs (`report_ner: in` / `out`) when evaluating text-layer NER.
