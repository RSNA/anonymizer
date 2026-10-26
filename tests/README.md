# Tests

| Tree | Mirrors | README |
|------|---------|--------|
| `tests/controller/` | `src/anonymizer/controller/` | [controller/README.md](controller/README.md) |
| `tests/model/` | `src/anonymizer/model/` | — |
| `tests/mcp/` | `src/anonymizer/mcp/` | [mcp/README.md](mcp/README.md) |
| `tests/view/` | `src/anonymizer/view/` | — (local GUI suite; not in default `testpaths`) |
| `src/prototyping/*/tests/` | `src/prototyping/` | [prototyping/tests/README.md](../src/prototyping/tests/README.md) |

## Running

Default suite matches the main CI job (`tests/controller` + `tests/model` + `tests/mcp`, **without** managed Orthanc):

```bash
uv sync --extra tseg --group dev
uv run pytest -q                              # same suite as GitHub Actions unit job
uv run pytest tests/controller/tseg -q        # subset
uv run pytest src/prototyping -q              # prototyping only (outside testpaths)
```

### Optional / opt-in suites

```bash
# Managed Orthanc PACS (ports 11242/18042; auto-download under orthanc_runtime/)
uv run pytest -m dicom_integration -o 'addopts=--tb=short' -q

# EasyOCR on real fixtures (needs weights under assets/ai/ocr/model) — pixel adversarial suite
uv run pytest tests/controller/ocr -m ocr_integration \
  -o 'addopts=--verbose --cov=src/anonymizer/controller --cov=src/anonymizer/utils --cov=src/anonymizer/model --cov=src/anonymizer/mcp' -q

# MIDI-B adversarial (not in CI; needs TCIA MIDI-B volume + vendor MIDI_validation_script)
# Always pass --group midi-b so nltk/pandas are available for the official scorer.
uv sync --group midi-b --group dev
uv run --group midi-b pytest tests/prototyping/midi_b -m midi_b_integration -o 'addopts=--tb=short' -q
# First smoke5 score floors / taxonomy ratchet:
MIDI_B_WRITE_BASELINE=1 uv run --group midi-b pytest tests/prototyping/midi_b -m midi_b_integration -o 'addopts=--tb=short' -q
# Reuse a scored harness run (skip re-de-id):
MIDI_B_RUN_DIR=/Volumes/…/harness-runs/validation_<UTC>_pytest_smoke5 \
  MIDI_B_WRITE_BASELINE=1 uv run --group midi-b pytest tests/prototyping/midi_b -m midi_b_integration -o 'addopts=--tb=short' -q
# Full Validation gate (overnight):
MIDI_B_FULL=1 uv run --group midi-b pytest tests/prototyping/midi_b -m midi_b_integration -k full -o 'addopts=--tb=short'

# PseudoPHI header gate (opt-in; local Pseudo-PHI-DICOM-Dataset)
uv run pytest -m pseudo_phi_integration \
  tests/controller/ai/embedded_phi/metadata/test_pseudo_phi_pipeline_integration.py \
  -o 'addopts=--tb=short' -q
PSEUDO_PHI_FULL=1 uv run pytest -m pseudo_phi_integration \
  tests/controller/ai/embedded_phi/metadata/test_pseudo_phi_pipeline_integration.py \
  -k full -o 'addopts=--tb=short'

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
| `dicom_integration` | Managed Orthanc; **opt-in** (excluded from default `addopts`). CI runs a path-filtered job when DICOM sources/tests change, on `dev`/`main`/`master` pushes, or `workflow_dispatch` |
| `ocr_integration` | EasyOCR on real burnt-in PHI fixtures (opt-in; excluded from default). Pixel adversarial track: davidson residual names, US RGB goldens, batch UX expectations |
| `pseudo_phi_integration` | PseudoPHI script+KB+NER header gate (opt-in; local dataset path) |
| `midi_b_integration` | MIDI-B Synthetic Validation adversarial suite (opt-in; **not CI**). Needs `/Volumes/…/TCIA/MIDI-B` + `uv sync --group midi-b` + cloned official validator under `src/prototyping/midi_b/vendor/` |
| `mcp_e2e` | Live HTTP MCP server (opt-in; excluded from default) |
| `view_dev` | Series View vs local MRI_TEST (opt-in; not in `testpaths`) |
| `tseg_integration` | TotalSegmentator inference in prototyping (slow; not in CI) |
| `rsna_local_data` | RSNA test data directory required |

Default `addopts` excludes `ocr_integration`, `view_dev`, `pseudo_phi_integration`, `midi_b_integration`, `mcp_e2e`, and `dicom_integration`.

## Shared assets

Binary fixtures live under `tests/controller/assets/`. Import paths from `tests.controller.paths`:

```python
from tests.controller.paths import CONTROLLER_ASSETS, CONTROLLER_TEST_DCM_FILES_DIR
```

Synthetic CT builders: `tests/controller/tseg/support/synthetic_ct.py`.
