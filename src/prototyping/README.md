# Prototyping scripts

Experimental scripts, CLIs, and UI spikes. **Not** part of the shipped `rsna-anonymizer` package (`src/anonymizer/`).

## Layout

```
src/prototyping/
├── ct/              # CT eval CLIs (e.g. ct_eval.py)
├── falcon/          # FALCON one-off studies (e.g. rsna_eligibility.py)
├── deid/            # OCR / pixel de-id experiments
├── dicom/           # DICOM transcoding, H.264, network spikes
├── fhir/            # Epic / HAPI FHIR experiments
├── aws/             # S3 import/export helpers
├── build/           # packaging and CI helpers
├── ui/              # tkinter / CustomTkinter spikes
├── scratch/         # unmaintained demos (no tests required)
├── _shared/         # config, storage_dir, parse_log
├── ct_eval.py       # shim → ct/ct_eval.py
└── ex_test_falcon_rsna_study_temp.py  # shim → falcon/rsna_eligibility.py
```

Root-level shims exist only for backward-compatible CLI entry points and ``prototyping.config``.

## Running CLIs

From repo root with dev dependencies:

```bash
uv sync --extra tseg --group dev
uv run python src/prototyping/ct/ct_eval.py --help
```

## Promotion to production

When a script stabilizes, move core logic to `src/anonymizer/controller/` and tests to `tests/controller/`. Leave a thin CLI here or remove once the app exposes the feature.

## Stdlib `locale`

There is no root ``locale.py`` (it previously shadowed the Python stdlib). The locale demo lives in ``scratch/locale_demo.py``.
