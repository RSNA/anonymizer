# Tests

| Tree | Mirrors | README |
|------|---------|--------|
| `tests/controller/` | `src/anonymizer/controller/` | [controller/README.md](controller/README.md) |
| `tests/model/` | `src/anonymizer/model/` | — |
| `tests/mcp/` | `src/anonymizer/mcp/` | [mcp/README.md](mcp/README.md) |
| `tests/view/` | `src/anonymizer/view/` | — (local GUI suite; not in default `testpaths`) |
| `src/prototyping/*/tests/` | `src/prototyping/` | [prototyping/tests/README.md](../src/prototyping/tests/README.md) |

## Default suite (CI)

Matches the main GitHub Actions unit job: `tests/controller` + `tests/model` + `tests/mcp`, without managed Orthanc or other opt-in markers.

```bash
uv sync --group dev
uv run pytest -q
```

Default `addopts` enable coverage and **exclude** opt-in markers (`ocr_integration`, `view_dev`, `pseudo_phi_integration`, `midi_b_integration`, `deid_option_iod`, `mcp_e2e`, `dicom_integration`). When you run a markered suite, override with `-o 'addopts=--tb=short'` so those exclusions (and coverage flags) do not fight selection.

De-identification option coverage in this default suite lives under `tests/controller/script/` (retain matrix, ingest smokes, clean-option stamps).

## Opt-in suites

Marker definitions live in `pyproject.toml`. MIDI-B details are in the next section.

| Marker | Needs | Command |
|--------|-------|---------|
| `dicom_integration` | Managed Orthanc (ports 11242/18042) | `uv run pytest -m dicom_integration -o 'addopts=--tb=short' -q` |
| `ocr_integration` | EasyOCR weights under `assets/ai/ocr/model` | `uv run pytest tests/controller/ocr -m ocr_integration -o 'addopts=--tb=short' -q` |
| `pseudo_phi_integration` | Local Pseudo-PHI DICOM dataset | `uv run pytest -m pseudo_phi_integration tests/controller/ai/embedded_phi/metadata/test_pseudo_phi_pipeline_integration.py -o 'addopts=--tb=short' -q` |
| `deid_option_iod` | Synthetic SR/US/PDF shells | `uv run pytest -m deid_option_iod tests/controller/script -o 'addopts=--tb=short' -q` |
| `mcp_e2e` | Live HTTP MCP server | see [mcp/README.md](mcp/README.md) |
| `view_dev` | Local GUI / MRI_TEST fixtures | `uv run pytest tests/view -m view_dev -q` |
| `tseg_integration` / `rsna_local_data` | Prototyping + local RSNA data | `uv run pytest src/prototyping -m tseg_integration` |
| `midi_b_integration` | TCIA volume + official validator | see [MIDI-B](#midi-b) below |

GUI without `view_dev`: `uv run pytest tests/view -m 'not view_dev' -q` (still outside default `testpaths`).

## MIDI-B

Opt-in adversarial suite under `tests/prototyping/midi_b/` (`midi_b_integration`). It characterizes residual PHI vs over-scrub using the official CBIIT scorer. **Not in CI** and not a substitute for the default unit suite.

CLI harness, volume layout, and scoring notes: [src/prototyping/midi_b/README.md](../src/prototyping/midi_b/README.md).

### Required

1. **External volume** at `/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B` — Synthetic Validation tree plus answer-key DB (paths in `src/prototyping/midi_b/paths.py`). Tests skip when missing.
2. **Official validator** clone at `src/prototyping/midi_b/vendor/MIDI_validation_script/` (gitignored).
3. **Deps** — always install and run with the `midi-b` group (official scorer needs nltk):

```bash
uv sync --group midi-b --group dev
```

### Environment variables

Truthy values for the boolean flags: `1`, `true`, or `yes`.

| Variable | Meaning |
|----------|---------|
| `MIDI_B_WRITE_BASELINE` | After a successful smoke5 validate+score, rewrite checked-in floors / taxonomy baselines (`smoke_floors.json`, `taxonomy_baseline.json`) from the observed run |
| `MIDI_B_FULL` | Enable the overnight full Validation gate (`-k full`); that test is skipped unless set |
| `MIDI_B_RUN_DIR` | Path to an already-scored harness run directory; reuse it (skip re-de-id) for taxonomy / baseline updates |

### Commands

```bash
# Smoke + taxonomy + live NER harvest checks
uv run --group midi-b pytest tests/prototyping/midi_b -m midi_b_integration -o 'addopts=--tb=short' -q

# Freeze score floors / taxonomy baselines from a successful smoke5
MIDI_B_WRITE_BASELINE=1 uv run --group midi-b pytest tests/prototyping/midi_b \
  -m midi_b_integration -o 'addopts=--tb=short' -q

# Reuse an existing scored run (skip re-de-id) while updating baselines
MIDI_B_RUN_DIR=/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/harness-runs/validation_<UTC>_pytest_smoke5 \
  MIDI_B_WRITE_BASELINE=1 uv run --group midi-b pytest tests/prototyping/midi_b \
  -m midi_b_integration -o 'addopts=--tb=short' -q

# Full Validation gate (overnight)
MIDI_B_FULL=1 uv run --group midi-b pytest tests/prototyping/midi_b \
  -m midi_b_integration -k full -o 'addopts=--tb=short'
```

## Shared fixtures

Binary fixtures live under `tests/controller/assets/`. Import paths from `tests.controller.paths`:

```python
from tests.controller.paths import CONTROLLER_ASSETS, CONTROLLER_TEST_DCM_FILES_DIR
```

Synthetic CT builders: `tests/controller/tseg/support/synthetic_ct.py`.
