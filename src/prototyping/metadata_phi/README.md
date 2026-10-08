# Metadata / report PHI detection (experiment harness)

**Product API:** `anonymizer.controller.ai.embedded_phi.detect_phi` (AI Features → PHI Text Detection; script `@phi()` / `@phi(this,synth)`).

This package remains the eval / dataset harness. Detect PHI in **any English text** that may appear in DICOM: short tag values, comments, SR/PDF/report paragraphs. All texts are scored the same way; they differ only by length (and thus available context).

**Labels:** `NAME`, `LOCATION`, `ID`, `PHONE`, `DATE`, `EMAIL`

## Definitive dataset

`fixtures/en_US/dataset/phi_text_eval.jsonl` — `id`, `length_class` (`short` ≤64 / `medium` 65–400 / `long` >400), `text`, `spans`.

```bash
uv sync --group metadata-phi
uv run python -m spacy download en_core_web_sm

uv run python -m prototyping.metadata_phi prep-phi-dataset
uv run python -m prototyping.metadata_phi eval-dataset \
  --engines patterns spacy_ner presidio_transformers openmed_pii
```

Primary metrics: **accuracy** and **2×2 confusion matrices**.

## Detectors

| Engine | Role |
| --- | --- |
| `patterns` | Regex / cue pack only |
| `spacy_ner` | spaCy NER only |
| `presidio_transformers` | Presidio + locale patterns; UID tags skipped |
| `openmed_pii` | HF `OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1` (~33M); pin with `pin-models` |

```bash
uv run python -m prototyping.metadata_phi pin-models --kind deid
export METADATA_PHI_LOCAL_FILES_ONLY=1
```

## MIDI-B held-out (final check)

```bash
uv run python -m prototyping.metadata_phi eval-heldout
```

Local `/Users/michaelevans/DATA/MIDI-B-2024-VAL` is the de-identified validation side — report is document false-alarm rate (expected: no PHI).

## Keep-and-scrub (experiment only)

Product default script still `@remove()`s `ContentSeq` / `EncapsulatedDocument`. Experiment path:

```bash
uv run python -m prototyping.metadata_phi scrub-file path/to.dcm --out /tmp/scrubbed.dcm \
  --engine presidio_transformers
```

Do **not** enable product keep until held-out + dataset document FN rates meet the bar in `metadata_phi_EXPERIMENT.md`.

Branch notes: [`metadata_phi_EXPERIMENT.md`](metadata_phi_EXPERIMENT.md).
