# Embedded PHI

Burnt-in pixel OCR (`pixel/`) and free-text NER (`ner/`) for post-ingest de-identification. Report View (`report/`) handles **native** SR and Encapsulated PDF text only — no OCR.

## Main APIs

| Module | Role |
| --- | --- |
| [`ner/engine.py`](ner/engine.py) | `Entity`; `detect_entities` / `detect_entities_in_segments`; `replace_entities` |
| [`ner/cache.py`](ner/cache.py) | `NerModelOptions`; `ner_ready` / `probe_ner_models` / `download_ner_models` / `remove_ner_models` |
| [`ner/synthetic_phi.py`](ner/synthetic_phi.py) + `pools/` | `generate_synthetic_phi(...)` offline replacements |
| [`report/process_report_text.py`](report/process_report_text.py) | `detect_phi_in_text` / `detect_phi` / `remove_phi` / `write_report_text` |
| [`pixel/detect_text.py`](pixel/detect_text.py) | EasyOCR → whitelist → `detect_entities` for PHI labels |
| [`pixel/remove_pixel_phi.py`](pixel/remove_pixel_phi.py) | Frame blackout / inpaint |
| [`metadata/iod_allowlist.py`](metadata/iod_allowlist.py) | SOP Class IOD allow-list → `iod_unexpected` on public text/dates |
| [`metadata/series_index.py`](metadata/series_index.py) | Per-SOP rows + interned unique free-text index for series load / Detect |
| [`controller/private_tags/`](../../private_tags/) | TCIA Private KB (`lookup_private_tag`, `private_tag_operation`) |

**PseudoPHI header path (no pixels / no regex):** (1) Default anonymizer script with SAFE_PRIVATE / Retain options walk → (2–5) extract / prepare NER / bulk detect / scrub.

IOD JSON is vendored at [`assets/dicom_standard/2025e/json/`](../../../assets/dicom_standard/2025e/json/) (~**2.4 MiB** total; see [`SOURCE.md`](../../../assets/dicom_standard/SOURCE.md)).

`load_series_frames` attaches `LoadedSeries.metadata_by_sop` and `metadata_unique_texts` (dates excluded from the unique index; identical strings interned across SOPs).

### NER package (`ner/`)

Each submodule documents its **Public API** at the top of the file (same layout as `process_report_text`). Import from the concrete module:

```python
from anonymizer.controller.ai.embedded_phi.ner.engine import (
    Entity,
    detect_entities,
    detect_entities_in_segments,
    replace_entities,
)
from anonymizer.controller.ai.embedded_phi.ner.cache import (
    NerModelOptions,
    ner_ready,
    download_ner_models,
)
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import generate_synthetic_phi
```

| Call | Returns |
| --- | --- |
| `detect_entities(text, *, locale="en_US")` | `list[Entity]` (offsets into `text`) |
| `detect_entities_in_segments(segments, …)` | per-segment `list[Entity]` (chunks of whole fields; breaks only on field boundaries) |
| `replace_entities(text, entities=None, *, mode="blank"\|"synth", …)` | `(new_text, entities_used)` |
| `NerModelOptions(model_id=…, cache_dir=…, local_files_only=…)` | frozen overrides for cache helpers (defaults = packaged model) |
| `ner_ready()` | `bool` — weights present and transformers/torch import |
| `probe_ner_models()` | `(NerModelStatus, localized_message)` |
| `download_ner_models(*, locale="en_US", options=None)` | `(ok, message)` |
| `generate_synthetic_phi(label, *, project_id, anon_ptid, …)` | synthetic replacement string |

```python
from anonymizer.controller.ai.embedded_phi.report.process_report_text import (
    detect_phi,
    remove_phi,
    write_report_text,
)

text, entities = detect_phi(ds, phi_header=study_phi_header)
cleaned = remove_phi(text, entities, synthetic=False)
sr = write_report_text(ds, cleaned)  # mutates ds; returns Basic Text SR for ML
```

## Report detect / remove (metadata + NER)

Headers on the DICOM instance are already anonymized; original PHI can still appear in
report body text. Detect and remove share one entity list; **text is never rewritten
during detect**, so NER always sees the original body (never anonymized strings).

| Phase | What happens |
| --- | --- |
| **Detect — metadata** | Match original PHI strings from `StudyPhiHeader` (`patient_id`, `accession_number`, `patient_name`, `study_date`, `patient_birth_date`) in the body. Each hit is labeled with the **DICOM keyword** (`PatientID`, `AccessionNumber`, `PatientName`, `StudyDate`, `PatientBirthDate`) and carries `Entity.replacement` = the anonymized value already on `ds`. |
| **Detect — NER** | Run `detect_entities` on the **same original** text. Spans that overlap a metadata hit are **dropped** (metadata wins — e.g. NER `ID` on a PatientID string is discarded). |
| **Remove** | Metadata entities **always** write `replacement` (anon DICOM value), in both blank and synth modes. NER entities blank or synthesize as usual. |

UI hover shows the entity `label` (DICOM keyword for metadata, product label for NER). Metadata highlights reuse the scored color family (`PatientID` → ID blue, `PatientName` → FIRST_NAME, dates → DATE).

## Modalities (`process_report_text`)

| Kind | Recognition | Text source |
| --- | --- | --- |
| SR | `Modality == "SR"` or SOP under `…88.*` | `ContentSequence` TEXT / PNAME |
| DOC / PDF | `Modality in {DOC, PDF}` or SOP `…104.1` | `EncapsulatedDocument` PDF text layer |

Write-back: always builds a **Basic Text SR** (ML/labelling). Also de-ids the source (SR slots in place, or plain-text PDF for DOC).

## Callers

| Caller | Path |
| --- | --- |
| **Report View** | Resolves `phi_header` from the anonymizer model; `detect_phi` / `remove_phi` / `write_report_text`; graphic PDF + text side panel |
| **AI batch** | `NATIVE_SR` / `NATIVE_PDF` → same report API with `phi_header`; imaging / SC → `remove_pixel_phi` |
| **Series View** | Pixel OCR; `remove_phi` via `ocr_transcript_sr` for OCR→SR scrub (NER only; no study metadata header) |

## NER rules

- **Model only** (OpenMed ClinicalE5 token-classification), used exactly as published — no suppressed output classes, no radiology lexicon, view-code lists, or phone regex. Model spans are returned as classified — no merging, and OCR boxes never re-label neighbouring boxes.
- Pixel path calls the model **once per frame** on all OCR box texts in reading order, joined as a comma list (boxes are distinct fields; comma boundaries return more dates as single spans than a space join) (the model is a text model; isolated fragments deny it context), then maps entities back to the boxes they fall in. The OCR box is the display/removal unit: a labelled box is removed whole, including prefixes/markers the model did not tag (`DOB:`, `[M]`). Hover shows only the entities detected inside that box. At the pixel boundary, `FIRST_NAME`/`LAST_NAME` collapse to the category `NAME` (pixel removal does not distinguish them, and burned-in DICOM-order names would otherwise appear reversed); report NER keeps the distinction for synthetic replacement.
- Product labels: `FIRST_NAME`, `LAST_NAME`, `LOCATION`, `ID`, `PHONE`, `DATE`, `EMAIL`.
- Report metadata entities use DICOM keywords as `label` (not product labels); see table above.
- Feature gate: `report_text_phi_ready()` ≡ NER ready; Series View / batch also need OCR.

### Scores and threshold

- Each Hugging Face span carries a **softmax confidence** for the model’s **fine-grained** label (e.g. `first_name`, `medical_record_number`, `customer_id`), not for the product super-category (`FIRST_NAME`, `ID`, …) after `_TO_SCORED` mapping.
- Aggregation uses `aggregation_strategy="max"` (merge WordPieces). **No score threshold is configured** — the pipeline keeps all aggregated spans (Hugging Face default `threshold=0.0`). Product code does not drop low-score entities.
- Report View hover shows the entity `label` only (product or DICOM keyword; not the fine-grained score).
