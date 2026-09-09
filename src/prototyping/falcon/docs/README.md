# FALCON (prototyping only)

FALCON body-part / IV-contrast classification lived in the product Harmonize path and has been **superseded by TotalSegmentator + Playbook Harmonize**. The library and evaluation tools now live under `src/prototyping/falcon/` for offline research only — they are **not** wired into the RSNA Anonymizer app.

## Layout

| Path | Role |
|------|------|
| `predict.py` | `predict_falcon_series()`, `FalconPrediction` |
| `load_models.py` | Weight download/cache under `assets/models/` |
| `resnet9.py` | Vendored ResNet9 |
| `preprocessing/` | DICOM load / resample / crop |
| `eval_accuracy.py` / `eval_utils.py` | Offline accuracy eval CLI |
| `rsna_eligibility.py` | Preprocess-only RSNA dataset scan |
| `tests/` | Prototyping tests (not CI) |

## Upstream

| | |
|--|--|
| Repository | [https://github.com/FintelmannLabDevelopmentTeam/Falcon](https://github.com/FintelmannLabDevelopmentTeam/Falcon) |
| Weights commit | see `load_models.FALCON_UPSTREAM_COMMIT` |
| Local weights | `src/prototyping/falcon/assets/models/` |

## Eval

```bash
uv run python -m prototyping.falcon.eval_accuracy --data-dir /data/falcon_eval
```

See [FALCON_Evaluation.md](FALCON_Evaluation.md) and [RadLex_Notes.md](RadLex_Notes.md) for historical terminology notes.
