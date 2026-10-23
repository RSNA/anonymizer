# Pseudo-PHI de-id (anonymizer script + private KB + bulk NER)

Generalizable de-identification experiment against Pseudo-PHI Evaluation → DeIdentified gold.

**This phase success:** header accuracy toward **~99.9%** using anonymizer script
(SAFE_PRIVATE KB walk) + OpenMed bulk NER + residual cleanup. **No pixel OCR.**

**Gate (historical):** cohort accuracy **>95%** (UIDs excluded from scoring).

## Pipeline (steps 1–8)

1. Anonymizer core + anonymizer script (public + SAFE_PRIVATE)
2–4. Extract → prepare NER → bulk detect + taxonomy scrub
5. `ner_residual_cleanup` (dangling `for` / `FORFILE` / `Sep1999`-style tokens)
6. Persist candidates
7. Score vs DeIdentified gold

```bash
# Primary: clinical script + private KB + NER + residual cleanup + score
uv run python -m prototyping.pseudo_phi_deid PseudoPHI-eval

# Integration gate (first 3 patients, header ≥99.9%; needs local PseudoPHI data)
uv run pytest -m pseudo_phi_integration \
  tests/controller/ai/embedded_phi/metadata/test_pseudo_phi_pipeline_integration.py \
  --override-ini='addopts='
```

Artifacts: [`results/`](results/) (gitignored). See [`EXPERIMENT.md`](EXPERIMENT.md) and [`TAXONOMY.md`](TAXONOMY.md).
