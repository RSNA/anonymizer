# Prototyping scripts

Experimental scripts, CLIs, and UI spikes. **Not** part of the shipped `rsna-anonymizer` package (`src/anonymizer/`).

Maintained tooling (eval CLIs, studies) moves into domain subdirectories. Throwaway UI demos and asyncio examples go in `scratch/` (planned).

## Target layout (migration in progress)

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
└── _shared/         # config and small shared helpers
```

Until migration completes, many scripts remain in this directory root.

## Running CLIs

From repo root with dev dependencies:

```bash
uv sync --extra tseg --group dev
uv run python src/prototyping/ct/ct_eval.py --help
```

The root ``src/prototyping/ct_eval.py`` shim delegates to ``ct/ct_eval.py`` for backward compatibility.

## Promotion to production

When a script stabilizes, move core logic to `src/anonymizer/controller/` and tests to `tests/controller/`. Leave a thin CLI here or remove once the app exposes the feature.

## Note on `locale.py`

This folder contains a `locale.py` that can shadow the Python stdlib `locale` module if `src/prototyping` is prepended to `sys.path`. CLIs that import torch/subprocess should avoid that (see `ct_eval.py` header). Planned rename: `_shared/i18n_config.py`.
