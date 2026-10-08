# Embedded PHI

Burnt-in OCR (`pixel/`) + English free-text NER (`ner/`) + report load/save (`report/`).

Import **concrete modules** — package `__init__` files are docstring-only.

Download via AI Features → **Embedded PHI** (OCR ∧ NER). Progress id: `embedded_phi`.

Labels: `NAME`, `LOCATION`, `ID`, `PHONE`, `DATE`, `EMAIL`. ClinicalE5 owns all labels except `PHONE` (locale regex). Bare `TIME` is left unlabeled. Detect locale: English (`en_US`) for all UI languages (Roman/Latin script).

---

## NAME guard / radiology lexicon

Pinned OpenMed (`OpenMed-PII-ClinicalE5-Small-33M-v1`) is trained for **PII recall** on clinical notes (Nemotron-PII), not to treat RadLex/LOINC as non-PHI. In short DICOM fields, series descriptions, and overlay OCR it commonly tags radiology surface forms as **NAME** (`chest`, `CT CHEST`, `axial`, `with contrast`, `kVp`, …). That is expected model behavior; the product does **not** fine-tune OpenMed for this.

After NER, `detect_phi.filter_spans` drops NAME spans that match a cached **radiology lexicon** (`ner/radiology_lexicon.py`):

| Tier | Sources | Match |
| --- | --- | --- |
| Exact | Bundled modality whitelists (`assets/locales/<locale>/whitelists/*.txt`, including `common_protocol.txt`), RadLex Playbook display glosses, LOINC StudyDescription tokens | O(1) casefold membership |
| Fuzzy | Whitelists + RadLex labels only (not 6k LOINC full names) | Shared `term_similarity.similarity_term_match` (threshold 0.85, min length ratio 0.75, min len 4) |

**Why there is no `radiology_deny.txt`:** a third hand-maintained deny list duplicated whitelists/RadLex/LOINC and does not scale to other languages. Protocol phrases that used to live in deny were migrated into `whitelists/common_protocol.txt`. Structural heuristics in `filter_spans` (view codes, short fragments, modality+anatomy patterns) remain in code.

**Maintaining / adding a language**

1. Ship or extend `assets/locales/<lang>/whitelists/` (OCR + NAME lexicon share these files).
2. Optionally add a locale LOINC StudyDescription CSV (same loader path as Harmonize).
3. Do **not** add `radiology_deny.<lang>.txt`. Detect NER stays English until a non-English OpenMed pack exists; the lexicon still resolves per whitelist/LOINC locale.

Shared similarity helper: `embedded_phi/term_similarity.py` (OCR whitelist matching delegates here too).

**Logging:** each suppressed NAME is logged at INFO as `NAME guard: dropped OpenMed NAME '…' (lexicon exact|fuzzy…|view code|modality/anatomy heuristic)`. Only the fragment is logged (not the full field), so radiology FPs are visible without dumping surrounding PHI.

---

## Routing — `classify_series`

Shared by Series View, Report Text Review, and AI batch (not under `pixel/`).

```python
from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series

kind = classify_series(series_path, modality="CT")
# SeriesKind: IMAGING | PIXEL_TEXT_REPORT | NATIVE_SR | NATIVE_PDF | OTHER_PIXEL
```

---

## `pixel/` — burnt-in OCR + removal

| Module | API |
| --- | --- |
| `pixel.cache` | `probe_ocr_models`, `ocr_models_ready`, `download_ocr_models`, `remove_ocr_models`, `OCR_MODEL_DIR`, `OCR_LANGS`, `OcrModelStatus` |
| `pixel.detect_text` | `detect_text`, `ocr_image_for_frame`, `build_series_view_ocr_pixels`, `filter_ocr_detections`, `filter_ocr_whitelist_only`, `filter_ocr_phi_ner`, `load_modality_whitelist`, whitelist match helpers, `PixelPhiRemovalMode` + menu helpers |
| `pixel.remove_pixel_phi` | `remove_pixel_phi`, `remove_ocr_text_from_frame`, `blackout_ocr_text_areas`, `blackout_rectangular_areas`, `apply_instance_embedded_phi` / `_for_dcm`, `apply_series_view_embedded_phi` |

```python
from anonymizer.controller.ai.embedded_phi.pixel.cache import download_ocr_models, ocr_models_ready
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import detect_text, PixelPhiRemovalMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import remove_pixel_phi

hits = detect_text(bgr_frame, reader, modality="CT")  # NER-gated: PHI-only
modified, texts, n = remove_pixel_phi(dcm_path, reader, removal_mode=PixelPhiRemovalMode.BLACKOUT)
```

`detect_text` always runs NER on remaining hits; if NER weights are missing, it returns no detections.

**One EasyOCR entry.** Series View / `remove_pixel_phi` call `detect_text` with no overrides (`width_ths=0.1`, word-level overlays). Report **`pixel_report`** (DICOM-frame) paths pass `easyocr_overrides=REPORT_PIXEL_EASYOCR_OVERRIDES` (`width_ths=0.3`, `link_threshold=0.6`, upright `rotation_info=[0]`). Encapsulated **PDF** reports do **not** use EasyOCR — text-layer NER only (see `report/` below). Product regex is **phone only**; OpenMed owns ID/LOCATION/NAME/EMAIL.

---

## `ner/` — free-text PHI detect / replace

| Module | API |
| --- | --- |
| `ner.cache` | `probe_ner_models`, `ner_ready`, `download_ner_models`, `remove_ner_models`, `NerModelStatus`, `model_cache_dir` |
| `ner.phi_entity` | `PhiEntity`, `SCORED_LABELS`, `SUPPORTED_DETECT_LOCALES` |
| `ner.detect_phi` | `detect_phi`, `scan_slots`, `SlotScan`, `entity_counts`, `removed_texts`, `filter_spans` |
| `ner.replace` | `replace_phi`, `apply_entities`, `apply_scans`, `ReplaceMode` (`"blank"` \| `"synth"`) |
| `ner.synthetic_phi` | `SyntheticPhiFactory` (HMAC pools under `ner/pools/`) |
| `ner.dicom_text_attributes` | `iter_hitchhiker_slots` (narrative DICOM keywords → `TextSlot`) |
| `ner.process_series_text` | `process_series_text`, `TextBatchResult` |
| `ner.locale_registry` | `detect_locale_supported`, `get_locale_pack`, `list_locales`, `load_ocr_whitelist_terms` |
| `ner.radiology_lexicon` | `get_radiology_lexicon`, `name_matches_radiology_lexicon` (NAME FP guard) |
| `term_similarity` | `similarity_term_match` (OCR whitelist + NAME lexicon) |
| `ner.openmed` / `ner.patterns` | engine internals used by `detect_phi` |

```python
from anonymizer.controller.ai.embedded_phi.ner.cache import download_ner_models, ner_ready
from anonymizer.controller.ai.embedded_phi.ner.detect_phi import detect_phi
from anonymizer.controller.ai.embedded_phi.ner.replace import replace_phi
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import SyntheticPhiFactory
from anonymizer.controller.ai.embedded_phi.ner.process_series_text import process_series_text

entities = detect_phi("Patient Jane Doe DOB 03/14/1962")
scrubbed, entities = replace_phi(text, mode="blank")
scrubbed, _ = replace_phi(
    text,
    mode="synth",
    synth=SyntheticPhiFactory(project_id="p", anon_ptid="A1"),
)
result = process_series_text(series_path, mode="blank", anon_model=anon)
```

Feature gates: `embedded_phi_has_models()` ≡ `ocr_models_ready() and ner_ready()` (Series View / pixel_report). PDF/SR Report Detect uses `report_text_phi_ready()` ≡ `ner_ready()` only.

---

## `report/` — load / save report documents

PDF/SR PHI detect is text-only: extract native text → OpenMed + phone regex (`apply_guard=False`) → UI spans. No PDF embedded-image OCR / letterhead cues.

| Module | API |
| --- | --- |
| `report.content_text` | `TextSlot` (editable region: `key`, `text`, `write`) |
| `report.report_sr` | `load_sr_document`, `iter_sr_slots`, `SrDocument`, `is_sr_dataset` |
| `report.encapsulated_pdf` | Layout (`extract_pdf_layout`, `rects_for_span`), `render_redacted_pdf`, `load_pdf_document`, `PdfDocument` |
| `report.report_ner` | `analyze_report_text`, `format_phi_xml` — XML in/out logs; wraps `detect_phi(..., apply_guard=False)` |
| `report.pdf_ocr` | `detect_pdf_hits` — text-layer NER → page rects (`source="native"`) |
| `report.hits` | `ReportHit` (PDF native; `source="ocr"` for pixel_report only) |
| `report.report_from_ocr` | `build_basic_text_sr`, `write_ocr_report_sr`, `deid_transcript_lines` / `cleansed_ocr_lines` |
| `report.report_session` | `ReportSession`, `DocumentKind` (`sr`\|`pdf`\|`pixel_report`) — Detect → zones → Remove → Save |

```python
from anonymizer.controller.ai.embedded_phi.report.report_sr import load_sr_document, iter_sr_slots
from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import load_pdf_slots
from anonymizer.controller.ai.embedded_phi.report.report_session import ReportSession

sr = load_sr_document(series_path)
session = ReportSession(series_path, document_kind="sr")
session.detect()
session.remove(mode="blank")  # or "synth"
session.save(anon_model=anon)

# PDF: same Detect → Remove → Save (Save rewrites EncapsulatedDocument as plain text)
pdf_session = ReportSession(series_path, document_kind="pdf")
```
