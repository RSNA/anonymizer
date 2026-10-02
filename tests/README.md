# Tests

| Tree | Mirrors | README |
|------|---------|--------|
| `tests/controller/` | `src/anonymizer/controller/` | [controller/README.md](controller/README.md) |
| `tests/model/` | `src/anonymizer/model/` | — |
| `tests/mcp/` | `src/anonymizer/mcp/` | — |
| `tests/view/` | `src/anonymizer/view/` | — (local GUI suite; not in default `testpaths`) |
| `src/prototyping/*/tests/` | `src/prototyping/` | [prototyping/tests/README.md](../src/prototyping/tests/README.md) |

## Running

Default suite matches CI (`tests/controller` + `tests/model` + `tests/mcp`, including managed Orthanc):

```bash
uv sync --extra tseg --group dev
uv run pytest -q                              # same suite as GitHub Actions
uv run pytest tests/controller/tseg -q        # subset
uv run pytest src/prototyping -q              # prototyping only (outside testpaths)
```

### Optional / opt-out suites

```bash
# Skip managed Orthanc (ports 11242/18042; auto-download under orthanc_runtime/)
uv run pytest -m 'not dicom_integration' -q

# EasyOCR on real fixtures (needs weights under assets/ai/ocr/model)
uv run pytest tests/controller/ocr -m ocr_integration \
  -o 'addopts=--verbose --cov=src/anonymizer/controller --cov=src/anonymizer/utils --cov=src/anonymizer/model --cov=src/anonymizer/mcp' -q

# Local GUI (Tk/CustomTkinter); excluded from default testpaths
uv run pytest tests/view -m 'not view_dev' -q
uv run pytest tests/view -m view_dev -q       # developer MRI_TEST fixtures only

pytest src/prototyping -m tseg_integration
pytest src/prototyping -m rsna_local_data
```

## Markers

Defined in `pyproject.toml`:

| Marker | Use |
|--------|-----|
| `dicom_integration` | Managed Orthanc; **included** in default suite; skip with `-m 'not dicom_integration'` |
| `ocr_integration` | EasyOCR on real fixtures (opt-in; excluded from default `addopts`) |
| `view_dev` | Series View vs local MRI_TEST (opt-in; not in `testpaths`) |
| `tseg_integration` | TotalSegmentator inference in prototyping (slow; not in CI) |
| `rsna_local_data` | RSNA test data directory required |

Default `addopts` excludes only `ocr_integration` and `view_dev`.

## Shared assets

Binary fixtures live under `tests/controller/assets/`. Import paths from `tests.controller.paths`:

```python
from tests.controller.paths import CONTROLLER_ASSETS, CONTROLLER_TEST_DCM_FILES_DIR
```

Synthetic CT builders: `tests/controller/tseg/support/synthetic_ct.py`.
