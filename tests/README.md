# Tests

| Tree | Mirrors | README |
|------|---------|--------|
| `tests/controller/` | `src/anonymizer/controller/` | [controller/README.md](controller/README.md) |
| `tests/model/` | `src/anonymizer/model/` | — |
| `tests/view/` | `src/anonymizer/view/` | — (local only) |
| `src/prototyping/*/tests/` | `src/prototyping/` | [prototyping/tests/README.md](../src/prototyping/tests/README.md) |

## Running

```bash
uv sync --extra tseg --group dev
uv run pytest tests/controller/tseg -q                             # may download TS weights
uv run pytest tests/controller -q                 # CI suite (controller + tseg)
uv run pytest src/prototyping -q              # prototyping only
uv run pytest -q                              # full local suite (controller + view + model)
```

## Markers

Defined in `pyproject.toml`:

| Marker | Use |
|--------|-----|
| `tseg_integration` | TotalSegmentator inference (slow) |
| `dicom_integration` | Local Orthanc or heavy DICOM network tests |
| `rsna_local_data` | RSNA test data directory required |
| `falcon_memory` | RSS leak guard on real FALCON inference |

```bash
pytest tests/controller -m tseg_integration
pytest tests/controller/dicom -m dicom_integration
pytest src/prototyping -m rsna_local_data
```

## Shared assets

Binary fixtures live under `tests/controller/assets/`. Import paths from `tests.controller.paths`:

```python
from tests.controller.paths import CONTROLLER_ASSETS, CONTROLLER_TEST_DCM_FILES_DIR
```

Synthetic CT builders: `tests/controller/tseg/support/synthetic_ct.py`.
