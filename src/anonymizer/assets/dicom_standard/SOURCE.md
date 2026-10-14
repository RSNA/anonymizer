# DICOM standard IOD excerpts (dicom-validator)

Bundled JSON used by [`metadata/iod_allowlist.py`](../../controller/ai/embedded_phi/metadata/iod_allowlist.py) to mark public free-text / date tags outside the SOP Class IOD.

## Layout

```
assets/dicom_standard/
  SOURCE.md                 ← this file
  2025e/json/               ← EditionReader cache layout
    dict_info.json
    iod_info.json
    module_info.json
    uid_info.json
    version
```

`EditionReader` path root is this directory (`assets/dicom_standard`); edition id is the first path segment (`2025e`).

## Bundled edition

| | |
| --- | --- |
| **Edition** | `2025e` (DICOM NEMA 2025e) |
| **Source** | [dicom-validator](https://github.com/pydicom/dicom-validator) `EditionReader` JSON excerpts from PS3.3 / PS3.4 / PS3.6 docbook |
| **Total JSON** | **~2.4 MiB** (2 524 769 bytes for the four `*_info.json` files) |

### Per-file sizes

| File | Size |
| --- | --- |
| `dict_info.json` | 584 KiB (597 729 bytes) |
| `iod_info.json` | 448 KiB (455 321 bytes) |
| `module_info.json` | 1.4 MiB (1 436 235 bytes) |
| `uid_info.json` | 36 KiB (35 484 bytes) |
| `version` | dicom-validator build marker |

IOD allow-list loading uses `dict_info.json`, `iod_info.json`, and `module_info.json` only.

## Refresh

To replace the bundle with a newer edition (example `2026d`):

```bash
uv run python -c "
from pathlib import Path
from dicom_validator.spec_reader.edition_reader import EditionReader
EditionReader().dicom_info_for_edition('2026d')  # downloads under ~/dicom-validator
"
# then copy ~/dicom-validator/<edition>/json/ into assets/dicom_standard/<edition>/json/
# and update BUNDLED_DICOM_EDITION in iod_allowlist.py
```

Prefer a fully downloaded edition; truncated docbook downloads fail JSON generation.
