# TotalSegmentator anatomy analysis (tseg)

The `tseg` module derives CT series anatomy and IV contrast from **physical HU values** and segmented organ volumes. It is an anatomic analytic pipeline, not a predictive classifier.

## Scope

- **Body regions:** TotalSegmentator 3 mm segmentation on a ROI subset; voxel counts aggregated into Head / Chest / Abdomen; multi-region labels when several regions exceed thresholds (e.g. `Chest+Abdomen`).
- **IV contrast:** Organ median HU statistics (TotalSegmentator) → **XGBoost ensemble** (models bundled inside `totalsegmentator`) → phase bucket → binary with/without contrast.

## Install implications (PyPI)

| Command | What you get |
|---------|----------------|
| `pip install rsna-anonymizer` | Core app only. Harmonize runs **FALCON** for regions and contrast. No TotalSegmentator or XGBoost. |
| `pip install "rsna-anonymizer[tseg]"` | Adds `totalsegmentator`, `xgboost`, `nibabel`, and pinned `dicom2nifti`. Harmonize uses TS for regions and contrast when runtime loads successfully. |

**Why XGBoost is in our extra, not TotalSegmentator’s:** upstream TS ships the contrast classifier `.pkl` files but documents `pip install xgboost` as a manual step and does **not** declare `xgboost` in its package metadata. The `tseg` extra makes that explicit for rsna-anonymizer.

**Native OpenMP (outside pip):** the `xgboost` wheel links to a platform OpenMP runtime that pip cannot install.

| OS | Typical requirement |
|----|---------------------|
| macOS (incl. Apple Silicon) | `libomp.dylib` — often via `brew install libomp` |
| Windows | MSVC OpenMP (`vcomp140.dll`) — usually via [Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) |
| Linux | `libgomp` — usually present with the system toolchain |

If XGBoost fails to load, the app still starts. Harmonize keeps TS regions when segmentation succeeded and **falls back to FALCON for contrast**.

### Development

```bash
uv sync --extra tseg --group dev
```

`dicom2nifti` is pinned to `<2.6` for compatibility with this project’s `pydicom` 2.4.x.

TotalSegmentator model weights (~400 MB) download automatically on first use.

## Performance (reference hardware)

On a Mac mini M-class with 16 GB RAM, expect roughly:

- ~60 s per typical chest CT series (first run includes model init)
- ~5 GB peak RAM during segmentation

Run anatomy analysis and FALCON **sequentially** during Harmonize to limit peak memory.

Harmonize order (single worker thread, per series):

0. **Geometry** — read DICOM headers; infer plane, 2D/3D dimensionality, original vs derived; cache in ``<series>/A_TS_SEG/geometry.json``
1. **FALCON** — lightweight slice-based inference; models released before TS
2. **TS segmentation** — ROI masks and regions on MPS/CUDA; **skipped** when ``geometry.ts_suitable`` is false (scouts, MIP/VR, single-slice)
3. **TS contrast** — optional (`ENABLE_TS_CONTRAST` in `config.py`). When off, FALCON supplies contrast.

The harmonize worker is the only thread that runs ML. Segmentation no longer spawns a progress ticker thread. Each stage uses `sequential_ml_context` to force `OMP/MKL=1`, `torch.set_num_threads(1)`, and `nnUNet_n_proc_DA=0`.

**macOS contrast crashes (exit 139):** contrast statistics default to CPU after MPS segmentation to avoid a second MPS pass SIGSEGV. If the process still dies at XGBoost, install OpenMP: `brew install libomp`.

## Public API

- `analyze_series(series_directories) -> list[TS_result]` in `segment.py`
- `analyze_tseg_face(series_directory, ...) -> FaceSegResult` in `segment.py`
- `resolve_series_geometry(series_directory) -> SeriesGeometryResult` in `dicom_geometry.py`
- RadLex Playbook+ descriptions via `format_radlex_ct_series_description()` in `radlex.py`

### Module layout (tseg + Harmonize)

| Module | Role |
|--------|------|
| `dicom_geometry.py` | DICOM header analysis: plane, dimensionality, provenance; slice sorting; ``geometry.json`` cache |
| `segment.py` | DICOM→NIfTI, TotalSegmentator ROI segmentation, region summary (`analyze_tseg_regions`) |
| `contrast.py` | Organ HU statistics + XGBoost contrast phase |
| `harmonize.py` | Orchestrates geometry → FALCON → TS → merge into `HarmonizedResult` |

Per-series cache under ``<series>/A_TS_SEG/``:

- `geometry.json` — geometry/provenance (this PR)
- `volume.nii.gz` — converted NIfTI
- `seg/*.nii.gz` — ROI masks and `face.nii.gz` (licensed face task)
- `contrast_stats.json` — organ HU stats

### Face segmentation (licensed task)

TotalSegmentator’s ``face`` task (Dataset303) is **separate** from the ROI ``total`` task: different weights and an **academic license** requirement.

```bash
uv run totalseg_set_license -l aca_XXXXXXXXXXXXXX
```

See [TotalSegmentator academic licensing](https://backend.totalsegmentator.com/license-academic/).

Public API in `segment.py`:

- `analyze_tseg_face(series_directory, *, progress=None, force=False) -> FaceSegResult`
- `run_face_segmentation(nifti_path, output_dir, ...) -> float` — low-level inference
- `face_mask_cache_path(series_directory) -> Path` — ``<series>/A_TS_SEG/seg/face.nii.gz``

Geometry gating matches anatomy regions (`ts_regions_eligible`); head-series eligibility is handled by downstream FFR/de-id callers. Set `ENABLE_TSEG_FACE = False` in `config.py` to disable the API.

Optional integration tests: `pytest tests/controller/tseg/test_tseg_face.py -m tseg_integration` (real TS ``face`` inference; slow).

## Harmonize integration

Series View **Harmonize Description** runs `harmonize_series()`, which uses TotalSegmentator as the primary source for regions and XGBoost-based contrast, with FALCON as fallback when anatomy analysis or contrast loading fails.
