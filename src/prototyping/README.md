# Prototyping scripts

Experimental scripts, CLIs, and UI spikes. **Not** part of the shipped `rsna-anonymizer` package (`src/anonymizer/`).

## Layout

```
src/prototyping/
├── ct/              # CT eval CLIs (e.g. ct_eval.py)
├── falcon/          # FALCON one-off studies (e.g. rsna_eligibility.py)
├── ocr/             # OCR burned-in text detection / inpainting experiments
├── ffr/             # facial feature removal (CT face blur POC, legacy volume scripts)
│   └── face/        # face blur viz POC (QA gallery + report.html)
├── deid/            # deprecated shims → use ocr/ or ffr/
├── ts_seg_face.py   # licensed TS face CLI → <series>/A_TS_SEG/seg/face.nii.gz
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
uv sync --extra tseg --group dev
uv run totalseg_set_license -l aca_XXXXXXXXXXXXXX   # once, if not already set
uv run python src/prototyping/ts_seg_face.py /path/to/ct_head_series
uv run python src/prototyping/ts_seg_face.py /path/to/ct_head_series --force
uv sync --extra tseg --group dev --group prototyping-viz
uv run python -m prototyping.ffr.face /path/to/ct_head_series
# → opens <series>/ts_seg/viz_poc/report.html in a browser
# (runs face segmentation first if A_TS_SEG/seg/face.nii.gz is missing)
```

## Promotion to production

When a script stabilizes, move core logic to `src/anonymizer/controller/` and tests to `tests/controller/`. Leave a thin CLI here or remove once the app exposes the feature.

## Tests

Prototyping tests live under `src/prototyping/*/tests/` (see [tests/README.md](tests/README.md)). They are excluded from CI; run with `pytest src/prototyping`.

## Stdlib `locale`

There is no root ``locale.py`` (it previously shadowed the Python stdlib). The locale demo lives in ``scratch/locale_demo.py``.
