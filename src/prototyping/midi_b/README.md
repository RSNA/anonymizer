# MIDI-B challenge harness

Same header pipeline as PseudoPHI (Clinical script → TCIA private KB → OpenMed NER →
residual cleanup), scored with the official
[CBIIT MIDI_validation_script](https://github.com/CBIIT/MIDI_validation_script).

**Data + run artifacts (external volume):** `/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B`

| Path | Role |
|------|------|
| `Synthetic Validation/…` | Challenge input + answer key DB |
| `Curated Validation/…` | Reference de-id (not used as pairwise gold) |
| `harness-runs/<split>_<UTC>[_slug]/` | **Each iteration:** candidates, mappings, official score |

Package `results/` only holds symlinks into `harness-runs/` (keeps primary disk free).

## Pipeline

1–7. Same as [`pseudo_phi_deid`](../pseudo_phi_deid/README.md).
8. Emit `mappings/uid_mapping.csv` + `patid_mapping.csv` (`id_old,id_new`, bare IDs).
9. Official `run_validation.py` (+ `run_reports.py`) against the answer key.

Vendor clone (gitignored): `vendor/MIDI_validation_script/`.

```bash
uv sync --group midi-b

# Smoke (writes under harness-runs/validation_<UTC>_smoke5)
uv run --group midi-b python -m prototyping.midi_b validate \
  --split validation \
  --patients 1011144680,105230877,1055270895,1132133087,1163484890 \
  --slug smoke5

# Full Validation
uv run --group midi-b python -m prototyping.midi_b validate --split validation --slug full

# Score an existing run dir on the external volume
uv run --group midi-b python -m prototyping.midi_b score \
  /Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/harness-runs/validation_20261013T220313Z_full
```

### Scoring vs PseudoPHI

PseudoPHI compared **eval vs gold DICOM headers field-by-field**. MIDI-B scoring is **action-based**: each answer-key row says what must happen to a tag (`text_retained`, `text_removed`, `uid_changed`, …). The official script indexes your submission, joins via UID/PatientID mapping CSVs, and scores those actions (not a full pairwise header dump).

Subset runs write `answer_key_filtered.db` so missing-file checks stay scoped to selected patients.
