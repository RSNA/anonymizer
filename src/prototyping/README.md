# Prototyping scripts

Experimental scripts, CLIs, and UI spikes. **Not** part of the shipped `rsna-anonymizer` package (`src/anonymizer/`).

## Layout

```
src/prototyping/
├── medgemma_chat/   # MedGemma + Anonymizer MCP chat (CLI / Gradio prototype)
├── ct/              # CT eval CLIs (ct_eval.py)
├── falcon/          # FALCON offline research (moved from product; superseded by tseg Harmonize)
├── ocr/             # OCR burned-in text detection / inpainting experiments
├── metadata_phi/    # metadata / SR / PDF free-text PHI NER experiment (en_US first)
├── report_phi/      # Encapsulated PDF letterhead OCR×OpenMed API-param sweep
├── midi_b/          # MIDI-B Synthetic Validation harness + official scorer glue
├── pseudo_phi_deid/ # PseudoPHI header de-id pipeline experiments
├── ffr/             # facial feature removal (CT face blur POC)
│   ├── face/        # face blur viz POC (QA gallery + report.html)
│   └── ts_seg_face.py  # licensed TS face CLI → <series>/0_TS_SEG/seg/face.nii.gz
├── harmonize/       # Harmonize benchmarks and cancel smokes
├── dev/             # hot-reload launcher, welcome window sizing check
├── dicom/           # DICOM transcoding, H.264, network spikes
├── fhir/            # Epic / HAPI FHIR experiments
├── aws/             # S3 import/export helpers
├── build/           # packaging and CI helpers
├── ui/              # tkinter / CustomTkinter spikes (+ play/pause icons)
├── scratch/         # unmaintained demos (no tests required)
├── _shared/         # config, storage_dir, parse_log
└── conftest.py      # shared pytest fixtures for prototyping tests
```

MkDocs help screenshots (maintainer tooling) live in [`src/docs_help/`](../docs_help/README.md)::

```bash
uv run python -m docs_help --language en_US
# Writes docs/<lang>/<NN-workflow>/shots/<os>/*.png
```

## Running CLIs

From repo root with dev dependencies:

```bash
uv sync --group dev
uv run python src/prototyping/ct/ct_eval.py --help
uv run totalseg_set_license -l aca_XXXXXXXXXXXXXX   # once, if not already set
uv run python src/prototyping/ffr/ts_seg_face.py /path/to/ct_head_series
uv run python src/prototyping/ffr/ts_seg_face.py /path/to/ct_head_series --force
uv sync --group dev --group prototyping-viz
uv run python -m prototyping.ffr.face /path/to/ct_head_series
# → opens <series>/ts_seg/viz_poc/report.html in a browser
# (runs face segmentation first if 0_TS_SEG/seg/face.nii.gz is missing)

uv run python src/prototyping/dev/dev_anonymizer.py
uv run python src/prototyping/harmonize/benchmark_harmonize_series.py --help

# MedGemma × Anonymizer MCP chat (see medgemma_chat/README.md)
uv sync --extra mcp --group medgemma-chat
uv run python -m prototyping.medgemma_chat --model /path/to/medgemma_4b_it
```

## Promotion to production

When a script stabilizes, move core logic to `src/anonymizer/controller/` and tests to `tests/controller/`. Leave a thin CLI here or remove once the app exposes the feature.

## Tests

Prototyping tests live under `src/prototyping/*/tests/` (see [tests/README.md](tests/README.md)). They are excluded from CI; run with `pytest src/prototyping`.

## Stdlib `locale`

There is no root ``locale.py`` (it previously shadowed the Python stdlib). The locale demo lives in ``scratch/locale_demo.py``.
