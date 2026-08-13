# Face blur visualization POC

Compare visualization modes and verify **no HU change outside** the face mask.

## Prerequisites

```bash
uv sync --extra tseg --group dev --group prototyping-viz
uv run totalseg_set_license -l aca_XXXXXXXXXXXXXX   # if not already done
```

Either run face segmentation first (faster when iterating on viz only):

```bash
uv run python src/prototyping/ts_seg_face.py /path/to/ct_head_series
```

Or let the blur POC run segmentation automatically when the cached mask is missing.

## Run

```bash
uv run python -m prototyping.ffr.face /path/to/ct_head_series
# or
uv run python src/prototyping/ffr/face_viz_poc.py /path/to/ct_head_series
```

## Output

`<series>/face_blurred/` — axial DICOM series with in-mask face blur, same geometry as input.

`<series>/ts_seg/viz_poc/`:

| File | Mode |
|------|------|
| `report.html` | Gallery + QA PASS/FAIL |
| `report.pdf` | PDF version of the HTML report for distribution |
| `qa_summary.json` | Numeric QA metrics |
| `J_front_side.png` | **Coronal + sagittal slabs (3 positions each) before/after** |
| `J_front_side_diff.png` | \|diff\| on coronal/sagittal slabs |
| `A_triptych.png` | Before \| after \| diff (one axial slice) |
| `B_violation.png` | Red = change outside mask |
| `C_contour.png` | Face contour on slice |
| `D_multi_slice.png` | Several z positions |
| `G_histogram.png` | Inside/outside HU histograms |
| `I_diff_mip.png` | Max \|diff\| projection |

## Blur parameters

In-mask blur is a 2D Gaussian applied independently on each axial slice inside the TotalSegmentator face mask. Voxels outside the mask are unchanged.

| Parameter | Default | User control | Effect |
|-----------|---------|--------------|--------|
| `sigma_mm` | `8.0` | **Primary knob** — expose in UI/settings | Approximate standard deviation of the blur in millimetres (in-plane). Larger → more smoothing, less recognizable facial structure. Typical head CT: 6–15 mm. |
| `pixel_spacing_mm` | from DICOM | Usually automatic | `(row, col)` spacing used to convert `sigma_mm` to pixel sigmas. Finer spacing → more pixels per mm → stronger blur for the same `sigma_mm`. |
| `min_sigma_px` | `0.5` | Advanced / rarely exposed | Floor on pixel sigma so tiny `sigma_mm` or very fine voxels still blur visibly. |

Conversion (see `blur.py`):

```
sigma_x = max(sigma_mm / col_spacing_mm, min_sigma_px)
sigma_y = max(sigma_mm / row_spacing_mm, min_sigma_px)
```

OpenCV uses `ksize=(0, 0)` so kernel size is derived from sigma. Approximate FWHM ≈ `2.355 × sigma_mm` per axis.

Constants live in `config.py` (`DEFAULT_FACE_BLUR_SIGMA_MM`, `MIN_FACE_BLUR_SIGMA_PX`).

## Layout

Core blur/export/QA logic lives in ``anonymizer.controller.ai.blur_face`` (production API).
This package adds visualization/reporting only.

```
face/
  __main__.py      CLI entry (viz POC)
  pipeline.py      viz orchestration (calls controller via shims)
  mask_source.py   shim → controller.blur_face
  blur.py          shim → controller.blur_face
  ...
  viz/modes.py     PNG renderers (prototyping only)
```

Production entry point:

```python
from anonymizer.controller.ai.blur_face import blur_face_series

result = blur_face_series(series_directory)
if result.error:
    ...
```
