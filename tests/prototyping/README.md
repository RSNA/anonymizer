# Prototyping tests

Tests for scripts and CLIs under `src/prototyping/`. Mirrors the domain layout of that tree (`ct/`, `falcon/`, …).

## Layout

```
tests/prototyping/
├── ct/
│   ├── test_ct_eval_confusion_matrix.py
│   ├── test_ct_eval_geometry.py          # geometry column helpers
│   ├── test_ct_eval_geometry_impact.py   # routing / fail-rate reports (step 4)
│   └── test_ct_eval_integration.py       # @tseg_integration; needs totalsegmentator extra
├── ffr/
│   └── test_face_*.py                    # face blur / export / report POC
└── falcon/
    └── test_rsna_eligibility.py   # @rsna_local_data when RSNA_TEST_DATA_DIR set
```

## Shared fixtures

- **DICOM phantoms:** import from `tests.controller.tseg.support.synthetic_ct`. Do not duplicate synthetic CT under `tests/prototyping/`.
- **Labeled eval data:** prototyping-specific label-dir layouts only, under `tests/prototyping/ct/support/` when needed.

## Running

```bash
pytest tests/prototyping -q
pytest tests/prototyping/ct -q
pytest tests/prototyping/ct -m tseg_integration -q   # slow; needs uv sync --extra tseg
```

Prototyping integration tests that run TotalSegmentator should use `@pytest.mark.tseg_integration`.
