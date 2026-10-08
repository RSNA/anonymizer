# Experiment: PHI in DICOM text

**Branch:** `experiment/metadata-phi-ner`  
**Locale (v1):** `en_US`

## Product path

The detect API is now a product AI feature:

- Module: `anonymizer.controller.ai.embedded_phi`
- Advertised: `detect_phi(text) -> list[PhiEntity]`, `replace_phi(...)`
- AI Features UI: **PHI Text Detection** (download OpenMed ClinicalE5-Small)
- Script operands: `@phi()` (blank spans), `@phi(this,synth)` (synthetic PHI)
- Remove Burnt-in Annotation: when models ready + `en_US`, OCR survivors are classified with `detect_phi` (whitelist KEEP override; fallback to whitelist-only if models missing)

Default anonymizer script still `@remove()`s ContentSeq / EncapsulatedDocument.

**Non-English (`de` / `fr` / `es`):** UI locales exist; detect is **English-only** in v1. Unsupported detect locales return no entities / skip `@phi` / keep whitelist-only pixels.

## Task

For English text in DICOM (metadata fields, SR, PDF, reports):

1. Does the text contain PHI?
2. Where: **NAME**, **LOCATION**, **ID**, **PHONE**, **DATE**, **EMAIL**

All texts scored the same; only **length** differs (`short` ≤64 / `medium` 65–400 / `long` >400).

## Dataset (prototyping harness)

```bash
uv run python -m prototyping.metadata_phi prep-phi-dataset
uv run python -m prototyping.metadata_phi eval-dataset \
  --engines patterns spacy_ner presidio_transformers openmed_pii
```

## MIDI-B held-out

```bash
uv run python -m prototyping.metadata_phi eval-heldout
```

## Product SR/PDF keep enablement

**Status: No-go** for flipping default ContentSeq / EncapsulatedDocument from `@remove()`.

Experiment keep-and-scrub remains in prototyping (`scrub-file`). Product enablement uses `@phi()` on text VRs when criteria pass.
