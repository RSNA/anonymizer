# Pseudo-PHI de-id (Clinical script + private KB + bulk NER)

Generalizable de-identification experiment against Pseudo-PHI Evaluation → DeIdentified gold.

**This phase success:** header accuracy toward **~99.9%** using Clinical script +
`process_private_tags_tcia` + OpenMed bulk NER + residual cleanup. **No pixel OCR.**

**Gate (historical):** cohort accuracy **>95%** (UIDs excluded from scoring).

## Pipeline (steps 1–8)

1. Anonymizer core + Clinical script (privates skipped on walk)
2. `process_private_tags_tcia` (creator-aware KB)
3–5. Extract → prepare NER → bulk detect + taxonomy scrub
6. `ner_residual_cleanup` (dangling `for` / `FORFILE` / `Sep1999`-style tokens)
7. Persist candidates
8. Score vs DeIdentified gold

```bash
# Primary: clinical script + private KB + NER + residual cleanup + score
uv run python -m prototyping.pseudo_phi_deid PseudoPHI-eval

# Integration gate (first 3 patients, header ≥99.9%; needs local PseudoPHI data)
uv run pytest -m pseudo_phi_integration \
  tests/controller/ai/embedded_phi/metadata/test_pseudo_phi_pipeline_integration.py \
  --override-ini='addopts='
```

Artifacts: [`results/`](results/) (gitignored). See [`EXPERIMENT.md`](EXPERIMENT.md) and [`TAXONOMY.md`](TAXONOMY.md).
