# Controller tests

Tests for `src/anonymizer/controller/` and related integration (DICOM network, storage, tseg, Harmonize).

## Layout

```
tests/controller/
├── assets/          # Shared binary fixtures (DICOM, indexes)
├── conftest.py      # Cross-cutting fixtures (project, SCP, temp dirs)
├── ocr/             # remove_pixel_phi / EasyOCR (unit + asset fixtures; ocr_integration)
├── tseg/            # TotalSegmentator, dicom_geometry, synthetic CT support
├── harmonize/       # harmonize_series merge and pipeline (incl. batch helpers)
├── blur_face/       # CT face blur (blur_face.py)
├── dicom/           # SCU/SCP integration tests + support modules
├── core/            # anonymizer.py, create_projections.py, ai_batch_process.py
└── infra/           # storage, network, logging, translate, modalities, aws, load_java_index
```

## Shared assets

All DICOM phantoms and eval fixtures live under `tests/controller/assets/`. Import paths from `tests.controller.paths`:

```python
from tests.controller.paths import CONTROLLER_ASSETS, CONTROLLER_TEST_DCM_FILES_DIR, JAVA_GENERATED_INDEX
```

Synthetic CT series builders live under `tests/controller/tseg/support/synthetic_ct.py`.

## DICOM support imports

```python
from tests.controller.dicom.support.test_files import ct_small_filename
from tests.controller.dicom.support.test_nodes import LocalStorageSCP
from tests.controller.dicom.support.helpers import send_file_to_scp
```

## Running subsets

```bash
pytest tests/controller/tseg -q
pytest tests/controller/harmonize -q
pytest tests/controller/blur_face -q
pytest tests/controller/ocr -q                       # unit + load/smoke (excludes ocr_integration by default)
pytest tests/controller/ocr -m ocr_integration -q    # EasyOCR on real fixtures (needs weights)
pytest tests/controller/dicom -q
pytest tests/controller/core -q
pytest tests/controller/infra -q
pytest tests/controller/dicom -m dicom_integration   # local Orthanc required
```

Default `addopts` excludes `ocr_integration` (`-m "not ocr_integration"`). Download EasyOCR models via AI Features or `download_ocr_models()` before running OCR asset tests.

See also [tests/README.md](../README.md) for the full test tree and marker reference.
