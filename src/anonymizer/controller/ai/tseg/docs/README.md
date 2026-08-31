# TotalSegmentator CT/MR segmentation (`tseg`)

The `tseg` package is the **TotalSegmentator runtime** for CT and MR: segmentation masks, region summaries, and optional mask-based contrast phase analysis. It is not an AI Feature catalog and has no RadLex/Playbook/LOINC or FALCON coupling.

## Scope

- **Body regions:** TotalSegmentator segmentation on a ROI subset; voxel counts aggregated into Head / Chest / Abdomen (CT) or modality-profile regions (MR); multi-region labels when several regions exceed thresholds (e.g. `Chest+Abdomen`).
- **IV contrast (CT):** Organ median HU statistics from TS masks → **XGBoost ensemble** (bundled with TotalSegmentator) → phase bucket → binary with/without contrast. Optional via `ENABLE_TS_CONTRAST`.
- **Face / brain structures:** Licensed TotalSegmentator tasks used by Face Blur and Brain Structures AI Features.

Harmonize (Playbook series descriptions, LOINC study offers) lives in `controller/ai/harmonize/` and **consumes** `TS_result` / geometry from this package.

## Install implications (PyPI)

| `pip install rsna-anonymizer` | Includes TotalSegmentator, XGBoost, nibabel, and dicom2nifti. Harmonize and Face Blur are enabled per project in **Project Settings**. |

**Model storage:** OCR models under `assets/ai/ocr/model/`; TotalSegmentator config and weights under `assets/ai/tseg/` (relative to the install directory after startup).

**Native OpenMP (outside pip):** the `xgboost` wheel links to a platform OpenMP runtime that pip cannot install.

| OS | Typical requirement |
|----|---------------------|
| macOS (incl. Apple Silicon) | `libomp.dylib` — often via `brew install libomp` |
| Windows | MSVC OpenMP (`vcomp140.dll`) — usually via [Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) |
| Linux | `libgomp` — usually present with the system toolchain |

If XGBoost fails to load, the app still starts. Harmonize requires contrast phase when `ENABLE_TS_CONTRAST` is on; without it, Playbook merge cannot complete for CT series that need IV contrast codes.

### Development

```bash
uv sync --group dev
```

`dicom2nifti` is pinned to `<2.6` for compatibility with this project’s `pydicom` 2.4.x.

TotalSegmentator model weights download on first use (or via AI Features download).

## Performance (reference hardware)

On a Mac mini M-class with 16 GB RAM, expect roughly:

- ~60 s per typical chest CT series (first run includes model init)
- ~5 GB peak RAM during segmentation

Each ML stage uses `sequential_ml_context` to force `OMP/MKL=1`, `torch.set_num_threads(1)`, and `nnUNet_n_proc_DA=0`.

**macOS contrast crashes (exit 139):** contrast statistics default to CPU after MPS segmentation to avoid a second MPS pass SIGSEGV. If the process still dies at XGBoost, install OpenMP: `brew install libomp`.

## Public API

- `analyze_series(series_directories) -> list[TS_result]` in `segment.py`
- `analyze_tseg_regions` / `analyze_tseg_contrast` / `analyze_tseg_face` in `segment.py`
- `resolve_series_geometry(series_directory) -> SeriesGeometryResult` in `dicom_geometry.py`

### Module layout

| Module | Role |
|--------|------|
| `dicom_geometry.py` | DICOM header analysis: plane, dimensionality, provenance; slice sorting; geometry cache |
| `segment.py` | DICOM→NIfTI, TotalSegmentator ROI / face / brain segmentation, region summary |
| `contrast.py` | Organ HU statistics + XGBoost contrast phase (CT) |
| `modality_profile.py` | CT vs MR task / ROI / trainer profiles |
| `model_cache.py` / `readiness.py` | Weight download and readiness probes |
| `ml_env.py` | Sequential ML thread/env helpers |
| `cache.py` / `config.py` | Per-series cache paths and constants |

Per-series cache under ``<series>/A_TS_SEG/``:

- `geometry.json` — geometry/provenance
- `volume.nii.gz` — converted NIfTI
- `seg/*.nii.gz` — ROI masks and licensed task masks
- `contrast_stats.json` / `contrast_phase.json` — organ HU stats and phase (CT)

### Face segmentation (licensed task)

TotalSegmentator’s ``face`` / ``face_mr`` tasks are **separate** from anatomy ROI tasks: different weights and an **academic license** requirement.

```bash
uv run totalseg_set_license -l aca_XXXXXXXXXXXXXX
```

See [TotalSegmentator academic licensing](https://backend.totalsegmentator.com/license-academic/).

Geometry gating matches anatomy regions (`ts_regions_eligible`); head-series eligibility is handled by Face Blur. Set `ENABLE_TSEG_FACE = False` in `config.py` to disable the API.

Controller unit tests under `tests/controller/tseg/` mock TotalSegmentator (no weight download). Optional local TS inference smoke: `pytest src/prototyping -m tseg_integration` (slow; not in CI).

## Downstream AI Features

- **Harmonize** (`controller/ai/harmonize/`) — Playbook+ series description and LOINC study offers from `TS_result` + geometry
- **Face Blur** / **Brain Structures** — consume face / brain_structures segmentation APIs
