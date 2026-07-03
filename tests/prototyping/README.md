# Prototyping tests

Tests for scripts and CLIs under `src/prototyping/`. Mirrors the domain layout of that tree (`ct/`, `falcon/`, …).

## Target layout (migration in progress)

```
tests/prototyping/
├── conftest.py
├── ct/
│   └── test_ct_eval_confusion_matrix.py
├── falcon/
│   └── test_rsna_eligibility.py   # @rsna_local_data when RSNA_TEST_DATA_DIR set
└── …
```

## Shared fixtures

- **DICOM phantoms:** import from `tests.controller.tseg.support` (or root builders until moved). Do not duplicate synthetic CT under `tests/prototyping/`.
- **Labeled eval data:** prototyping-specific label-dir layouts only, under `tests/prototyping/ct/support/` when needed.

## Running

```bash
pytest tests/prototyping -q
pytest tests/prototyping/ct -q
```

Prototyping integration tests that run TotalSegmentator should use `@pytest.mark.tseg_integration`.
