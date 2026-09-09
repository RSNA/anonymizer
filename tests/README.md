# Tests

| Tree | Mirrors | README |
|------|---------|--------|
| `tests/controller/` | `src/anonymizer/controller/` | [controller/README.md](controller/README.md) |
| `tests/model/` | `src/anonymizer/model/` | — |
| `tests/view/` | `src/anonymizer/view/` | — (local only; excluded from CI) |
| `src/prototyping/*/tests/` | `src/prototyping/` | [prototyping/tests/README.md](../src/prototyping/tests/README.md) |

## Running

```bash
uv sync --extra tseg --group dev
uv run pytest tests/controller/tseg -q                             # mocked unit tests (CI-safe)
uv run pytest tests/controller tests/model -q   # CI suite (no view)
uv run pytest src/prototyping -q              # prototyping only
uv run pytest -q                              # full local suite (controller + view + model)
```

## Markers

Defined in `pyproject.toml`:

| Marker | Use |
|--------|-----|
| `tseg_integration` | TotalSegmentator inference in prototyping (slow; not in CI) |
| `ocr_integration` | EasyOCR on real fixtures in `tests/controller/ocr/` (opt-in; excluded from default) |
| `dicom_integration` | Local Orthanc or heavy DICOM network tests |
| `rsna_local_data` | RSNA test data directory required |

```bash
pytest src/prototyping -m tseg_integration
pytest tests/controller/ocr -m ocr_integration   # needs EasyOCR weights under assets/ai/ocr/model
pytest tests/controller/dicom -m dicom_integration
pytest src/prototyping -m rsna_local_data
```

Default pytest `addopts` includes `-m "not ocr_integration"` so OCR weight-dependent tests are not collected (and do not show as skipped).

## Shared assets

Binary fixtures live under `tests/controller/assets/`. Import paths from `tests.controller.paths`:

```python
from tests.controller.paths import CONTROLLER_ASSETS, CONTROLLER_TEST_DCM_FILES_DIR
```

Synthetic CT builders: `tests/controller/tseg/support/synthetic_ct.py`.
