# FALCON accuracy evaluation

## Utility

`eval_accuracy.py` runs the **production** path (`predict_falcon_series`) on labeled CT series and prints:

- Eligibility rate (successful inference vs `FalconPrediction.error`)
- **Body part**: accuracy, macro-F1, per-class precision/recall/F1, confusion matrix
- **IV contrast**: same metrics overall and stratified by **ground-truth** body part

Ground truth comes from **first-level folder names** under a data root—no manifest CSV.

```bash
poetry run python -m anonymizer.controller.ai.falcon.eval_accuracy \
  --data-dir /path/to/labeled_dataset
```

By default this also writes `<data-dir>/falcon_eval_results.csv`. Override the path with `--output PATH`, or pass `--no-results-file` to skip the CSV.

Re-running against the same data directory **skips FALCON inference** for any series already present in the results CSV, skips regenerating error PNGs that already exist on disk, and skips regenerating contrast success PNGs. Body-part success mosaics are rebuilt on the fly each run. New or missing series are evaluated and merged into an updated CSV.

### Results CSV columns

Per-series predictions and ground truth, plus fields aligned with the printed error summary: `classification_error`, `series_description`, `bolus_tags`, and `iv_contrast_class_confidence` (predicted With/Without class confidence, not raw P(present)).

When a results CSV is written, classification-error PNGs are saved under:

- `<data-dir>/falcon_eval_artifacts/errors/body_part/<label_dir>/` — body-part wrong (z index 50 input)
- `<data-dir>/falcon_eval_artifacts/errors/contrast/<label_dir>/` — contrast wrong **only if body part was correct**

Contrast success PNGs for comparison are saved under:

- `<data-dir>/falcon_eval_artifacts/success/contrast/<label_dir>/` — contrast correct **only if body part was correct**

Body-part summary mosaics (one per ground-truth class) live under:

- `<data-dir>/falcon_eval_artifacts/body_part/error/` — up to 36 body-part errors per class, e.g. `headneck_errors.png`
- `<data-dir>/falcon_eval_artifacts/body_part/success/` — up to 36 body-part successes per class compiled on the fly, e.g. `headneck_success.png`

No per-series body-part success PNGs are written to disk.

Per-series error/contrast PNG filenames are `<series_uid>.png` (dots in UIDs become underscores). Each cell has a compact top-left title on two lines, e.g. `GT: HEADNECK->CHEST` and `80%` for errors (contrast: `GT: WITH->WITHOUT`); body-part success cells show `GT: HEADNECK` and `95%`.

Examples:

`errors/body_part/CT_HEAD_WITH_CONTRAST/1_2_3_series.png`

`body_part/error/chest_errors.png`

`body_part/success/headneck_success.png`

Summary grids use up to 6×6 cells (shrinking to 5×5, 4×4, … when there are fewer than 36 cases). Contrast summary grids remain at the artifact root for now:

| File | Contents |
|------|----------|
| `body_part/error/headneck_errors.png` | Body-part errors, GT HeadNeck |
| `body_part/error/chest_errors.png` | Body-part errors, GT Chest |
| `body_part/error/abdomen_errors.png` | Body-part errors, GT Abdomen |
| `body_part/success/headneck_success.png` | Body-part correct, GT HeadNeck |
| `body_part/success/chest_success.png` | Body-part correct, GT Chest |
| `body_part/success/abdomen_success.png` | Body-part correct, GT Abdomen |
| `error_summary_contrast_without_pred_with.png` | GT WITHOUT, predicted WITH |
| `error_summary_contrast_with_pred_without.png` | GT WITH, predicted WITHOUT |
| `success_summary_contrast_without_pred_without.png` | GT WITHOUT, predicted WITHOUT |
| `success_summary_contrast_with_pred_with.png` | GT WITH, predicted WITH |

Each cell is an annotated model-input thumbnail (title + confidence). Body-part error grids sort by ascending failed-task confidence; body-part success grids sort by descending confidence. Categories with no cases are omitted.

**IV contrast metrics** and contrast error reporting exclude series where body-part prediction does not match ground truth (contrast is routed by predicted body part). The results CSV includes a `contrast_evaluated` column.

## Directory layout

```text
/path/to/labeled_dataset/
  CT_HEAD_WITH_CONTRAST/
    <study_uid>/
      <series_uid_A>/*.dcm
      <series_uid_B>/*.dcm
  CT_CHEST_WITHOUT_CONTRAST/
    <study_uid>/
      <series_uid>/*.dcm
```

- There is **no patient** level: label → study → series → instances.
- Each **first-level subdirectory** name defines body part and IV contrast for every series under it.
- One row per `<series_uid>` folder that contains `.dcm` files; a study may include multiple series.
- Optional `CT_` prefix; use underscores between tokens.

### Supported naming patterns

| Token in folder name | Meaning |
|----------------------|---------|
| `HEAD`, `HEADNECK`, `HN`, `NECK` | HeadNeck |
| `CHEST`, `CH` | Chest |
| `ABDOMEN`, `ABD`, `PELVIS`, `AP` | Abdomen |
| `WITH`, `W`, `CONTRAST` (without `WITHOUT`) | IV contrast present |
| `WITHOUT`, `WO`, `NONCONTRAST`, `NC` | No IV contrast |

Examples: `CT_HEAD_WITH_CONTRAST`, `CT_CHEST_WITHOUT_CONTRAST`, `CT_ABDOMEN_WO`.

Unparseable first-level folders are skipped with a warning.

After the metrics report, a **Classification error summary** is always printed for series with a body-part mismatch, contrast mismatch, or pipeline error:

- Table columns: `series_path`, `classification_error`, `bp_conf`, `contrast_conf`, `series_description`, `bolus_tags`.
- `bp_conf` / `contrast_conf` show predicted-class confidence (same as Harmonize) only for the task that failed; contrast uses class confidence, not raw P(present).
- Rows are sorted by ascending confidence on the failed task (least confident errors first).
- A short aggregate lists median confidence and count of high-confidence (≥90%) errors per failed task type.
- `series_description` and `bolus_tags` come from the first slice (`ContrastBolusAgent` / `ContrastBolusRoute`).

## Metrics notes

- Rows with preprocess/prediction **errors** are excluded from accuracy/F1 but counted in `eligibility_rate`.
- **IV contrast** metrics include only series where **body-part prediction matches ground truth**; wrong body part excludes that series from contrast accuracy/F1 and from contrast error artifacts.
- On successful series with correct body part, contrast uses the model routed from **predicted** body part (same as Harmonize).
- Stratified contrast sections filter by **ground-truth** body part among contrast-evaluated series.

## Citation

Report numbers with the upstream FALCON paper; see [README.md](README.md).
