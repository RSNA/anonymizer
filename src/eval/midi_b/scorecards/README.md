# Published MIDI-B scorecards

Committed evidence from full Synthetic Validation / Test runs scored with the
official CBIIT MIDI validation script. Scratch harness output (projects, mappings,
xlsx) stays outside git under `.midi_b_runs/` or the volume `harness-runs/` folder
and is not published here.

## Current published cards

| Split | Score | File | Source run | Commit |
| --- | ---: | --- | --- | --- |
| Synthetic Validation (full) | 99.03% | [validation_20261101_full.md](validation_20261101_full.md) | `validation_20261101T154826Z_full` | `6afbe5c` |
| Synthetic Test (full) | 99.08% | [test_20261101_full.md](test_20261101_full.md) | `test_20261101T174432Z_full` | `6afbe5c` |

Known source / answer-key discrepancies that dominate residual fails:
[source_answer_errors.md](source_answer_errors.md).

## How these were produced

```bash
uv sync --group midi-b
uv run --group midi-b python -m eval.midi_b validate --slug full
uv run --group midi-b python -m eval.midi_b test --slug full
```

Project defaults: `assets/ProjectModel.json` (Retain stack + Retain TCIA Research;
**Retain Device Identity off**) and `assets/AiBatchConfig.json` (Embedded PHI:
pixel + metadata + reports). After a run, copy `SCORECARD.md` into this folder with
a stable `validation_YYYYMMDD_full.md` / `test_YYYYMMDD_full.md` name, update the
table above, and refresh the docs Reference page.
