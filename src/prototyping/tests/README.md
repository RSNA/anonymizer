# Prototyping tests

Tests for scripts and CLIs under `src/prototyping/`. Colocated with the domain they exercise (`ct/tests/`, `ffr/tests/`, …).

## Layout

```
src/prototyping/
├── ct/tests/
│   ├── test_ct_eval_confusion_matrix.py
│   ├── test_ct_eval_geometry.py          # geometry column helpers
│   ├── test_ct_eval_geometry_impact.py   # routing / fail-rate reports (step 4)
│   └── test_ct_eval_integration.py       # @tseg_integration; needs totalsegmentator extra
├── ffr/tests/
│   └── test_face_*.py                    # face blur / export / report POC
└── falcon/tests/
    ├── test_rsna_eligibility.py          # @rsna_local_data when RSNA_TEST_DATA_DIR set
    ├── test_predict.py                   # offline FALCON predict (not CI)
    ├── test_dicom_loading.py
    ├── test_eval_accuracy.py
    └── test_eval_utils.py
```

Prototyping tests are **not** run in CI. Run them locally when working on prototyping scripts.

## Shared fixtures

- **DICOM phantoms:** import from `tests.controller.tseg.support.synthetic_ct`. Do not duplicate synthetic CT under `src/prototyping/`.
- **Session fixtures:** `src/prototyping/conftest.py` reuses `tests.controller.tseg.fixtures`.

## Running

```bash
pytest src/prototyping -q
pytest src/prototyping/ct -q
pytest src/prototyping/ct -m tseg_integration -q   # slow; needs uv sync --extra tseg
```

Prototyping integration tests that run TotalSegmentator should use `@pytest.mark.tseg_integration`.
