# MIDI-B evaluation (`eval.midi_b`)

Orchestrates MIDI-B **Validation** and **Test** by subprocess only:

1. `rsna-anonymizer -c ProjectModel.json --import-dir … --export-mappings …`
2. `rsna-anonymizer -c ProjectModel.json --ai-batch AiBatchConfig.json --ai-batch-run`
3. Official CBIIT `MIDI_validation_script` (clone under `vendor/MIDI_validation_script/`)

AI batch: per-series `Failed:` / `ERROR` lines in `project/private/batch_runs/*.log` are always printed. If the batch exits non-zero **with** those lines (some series failed), scoring still runs. Non-zero exit **without** series error lines aborts (config error, cancel, crash). The validate/test entrypoint wraps other exceptions and returns exit code 1.

```bash
uv sync --group midi-b

# Smoke validation (subset)
uv run --group midi-b python -m eval.midi_b validate \
  --patients 1011144680,105230877 --slug smoke2

# Full validation
uv run --group midi-b python -m eval.midi_b validate --slug full

# Test split (no public answer key scoring)
uv run --group midi-b python -m eval.midi_b test --slug full

# Rebuild SCORECARD for an existing run
uv run --group midi-b python -m eval.midi_b score \
  /Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/harness-runs/<run_dir>
```

Pregenerated project: `assets/ProjectModel.json` (Retain stack + TCIA Research;
**Retain Device Identity off** — manufacturer/model/software come from TCIA Research
`@safe()`). Runs write under `/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/harness-runs/`.
