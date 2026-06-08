"""
Evaluate FALCON classification accuracy from a directory of labeled CT series.

Ground truth is encoded in **first-level subdirectory names** under --data-dir.
Each label folder contains one or more CT series directories (any nesting depth).

Example layout::

    /data/falcon_eval/
      CT_HEAD_WITH_CONTRAST/
        <study_uid>/<series_uid>/*.dcm
      CT_CHEST_WITHOUT_CONTRAST/
        <study_uid>/<series_uid_A>/*.dcm
        <study_uid>/<series_uid_B>/*.dcm

Run::

  poetry run python -m anonymizer.controller.falcon.eval_accuracy \\
    --data-dir /data/falcon_eval

Writes ``<data-dir>/falcon_eval_results.csv`` by default (override with ``--output``, skip with ``--no-results-file``).
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image, ImageDraw, ImageFont

from anonymizer.controller.falcon.eval_utils import (
    render_body_part_model_input_thumbnail,
    save_body_part_model_input_png,
    save_contrast_model_input_png,
)
from anonymizer.controller.falcon.predict import (
    FALCON_BODY_PARTS,
    FalconPrediction,
    contrast_prediction_confidence,
    format_confidence_percent,
    predict_falcon_series,
)
from anonymizer.controller.falcon.preprocessing.preprocess_series import preprocess_series

logger = logging.getLogger(__name__)

FALCON_EVAL_RESULTS_FILENAME = "falcon_eval_results.csv"
FALCON_EVAL_ARTIFACTS_DIRNAME = "falcon_eval_artifacts"
FALCON_EVAL_ERRORS_BODY_PART_DIR = Path("errors") / "body_part"
FALCON_EVAL_ERRORS_CONTRAST_DIR = Path("errors") / "contrast"
FALCON_EVAL_BODY_PART_ERROR_SUMMARY_DIR = Path("body_part") / "error"
FALCON_EVAL_BODY_PART_SUCCESS_SUMMARY_DIR = Path("body_part") / "success"
FALCON_EVAL_SUCCESS_CONTRAST_DIR = Path("success") / "contrast"
SUMMARY_MAX_GRID_DIMENSION = 6
SUMMARY_MAX_ARTIFACTS = SUMMARY_MAX_GRID_DIMENSION * SUMMARY_MAX_GRID_DIMENSION
SUMMARY_CELL_SIZE = 128
SUMMARY_MATRIX_GAP = 6

CONTRAST_ERROR_SUMMARY_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        "contrast_without_pred_with",
        "FALCON contrast errors: GT WITHOUT->WITH",
        "error_summary_contrast_without_pred_with.png",
    ),
    (
        "contrast_with_pred_without",
        "FALCON contrast errors: GT WITH->WITHOUT",
        "error_summary_contrast_with_pred_without.png",
    ),
)

CONTRAST_SUCCESS_SUMMARY_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        "contrast_without_pred_without",
        "FALCON contrast successes: GT WITHOUT->WITHOUT",
        "success_summary_contrast_without_pred_without.png",
    ),
    (
        "contrast_with_pred_with",
        "FALCON contrast successes: GT WITH->WITH",
        "success_summary_contrast_with_pred_with.png",
    ),
)

BODY_PART_LABELS = list(FALCON_BODY_PARTS)
CONTRAST_LABELS = ("without", "with")


@dataclass(frozen=True)
class GroundTruth:
    body_part: str
    iv_contrast: bool
    label_dir: str


@dataclass(frozen=True)
class EvalRow:
    series_path: Path
    body_part: str
    iv_contrast: bool
    label_dir: str


ERROR_CONFIDENCE_HIGH_THRESHOLD = 0.9


@dataclass(frozen=True)
class SavedEvalArtifact:
    row: EvalRow
    prediction: FalconPrediction
    image_path: Path
    task_kind: str


@dataclass(frozen=True)
class ErrorSummaryEntry:
    series_path: str
    classification_error: str
    series_description: str
    bolus_tags: str
    bp_conf: str
    contrast_conf: str


@dataclass(frozen=True)
class ClassifierMetrics:
    n: int
    accuracy: float
    macro_f1: float
    per_class: dict[str, dict[str, float]]
    confusion: np.ndarray
    label_names: tuple[str, ...]


@dataclass(frozen=True)
class EvalReport:
    total: int
    n_success: int
    n_error: int
    eligibility_rate: float
    body_part: ClassifierMetrics | None
    contrast_overall: ClassifierMetrics | None
    contrast_by_body_part: dict[str, ClassifierMetrics]
    label_counts: dict[str, int]


def parse_label_dirname(dirname: str) -> GroundTruth:
    """
    Parse ground truth from a first-level label directory name.

    Expected naming includes body region and contrast, e.g. CT_HEAD_WITH_CONTRAST,
    CT_CHEST_WITHOUT_CONTRAST, CT_HEADNECK_WO, CT_ABDOMEN_W.
    """
    joined = dirname.upper().replace("-", "_")
    tokens = [token for token in joined.split("_") if token]

    if "WITHOUT" in joined or "WO" in tokens or "NONCONTRAST" in joined or "NC" in tokens:
        iv_contrast = False
    elif "WITH" in joined or "W" in tokens or "CONTRAST" in joined:
        iv_contrast = True
    else:
        raise ValueError(
            f"Cannot parse contrast from directory name {dirname!r}. "
            "Include WITH/W or WITHOUT/WO (e.g. CT_HEAD_WITH_CONTRAST)."
        )

    if (
        "HEADNECK" in joined
        or ("HEAD" in tokens and "NECK" in tokens)
        or "HEAD" in tokens
        or "HEAT" in tokens
        or "HN" in tokens
        or "NECK" in tokens
    ):
        body_part = "HeadNeck"
    elif "CHEST" in joined or "CH" in tokens:
        body_part = "Chest"
    elif "ABDOMEN" in joined or "ABD" in tokens or "PELVIS" in joined or "AP" in tokens:
        body_part = "Abdomen"
    else:
        raise ValueError(
            f"Cannot parse body part from directory name {dirname!r}. "
            "Include HEAD/HEADNECK, CHEST, or ABDOMEN (e.g. CT_CHEST_WITHOUT_CONTRAST)."
        )

    return GroundTruth(body_part=body_part, iv_contrast=iv_contrast, label_dir=dirname)


def _directory_has_dicom_files(directory: Path) -> bool:
    return any(path.is_file() and not path.name.startswith(".") for path in directory.glob("*.dcm"))


def discover_series_directories(label_root: Path) -> list[Path]:
    """
    Find series directories under a label folder.

    Expected layout (no patient level)::

        <label_dir>/<study_uid>/<series_uid>/*.dcm

    A study may contain multiple series subdirectories. Each series_uid folder
    that contains ``.dcm`` files is one input to ``predict_falcon_series``.
    """
    series_dirs: list[Path] = []

    for study_dir in sorted(label_root.iterdir()):
        if not study_dir.is_dir() or study_dir.name.startswith("."):
            continue

        for series_dir in sorted(study_dir.iterdir()):
            if not series_dir.is_dir() or series_dir.name.startswith("."):
                continue
            if _directory_has_dicom_files(series_dir):
                series_dirs.append(series_dir.resolve())

    return sorted(series_dirs)


def load_eval_rows(data_dir: Path) -> list[EvalRow]:
    root = data_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"Data directory not found: {root}")

    rows: list[EvalRow] = []
    label_counts: dict[str, int] = {}

    for label_path in sorted(root.iterdir()):
        if not label_path.is_dir() or label_path.name.startswith("."):
            continue

        try:
            ground_truth = parse_label_dirname(label_path.name)
        except ValueError as exc:
            logger.warning("Skipping %s: %s", label_path.name, exc)
            continue

        series_dirs = discover_series_directories(label_path)
        if not series_dirs:
            logger.warning("No DICOM series found under %s", label_path)
            continue

        label_counts[ground_truth.label_dir] = len(series_dirs)
        for series_path in series_dirs:
            rows.append(
                EvalRow(
                    series_path=series_path,
                    body_part=ground_truth.body_part,
                    iv_contrast=ground_truth.iv_contrast,
                    label_dir=ground_truth.label_dir,
                )
            )

    if not rows:
        raise ValueError(
            f"No labeled series found under {root}. "
            "Expected first-level folders like CT_HEAD_WITH_CONTRAST/ containing DICOM series."
        )

    logger.info("Loaded %d series from %d label folders", len(rows), len(label_counts))
    for label_dir, count in sorted(label_counts.items()):
        logger.info("  %s: %d series", label_dir, count)

    return rows


def _confusion_matrix(
    y_true: list[str],
    y_pred: list[str],
    labels: tuple[str, ...],
) -> np.ndarray:
    index = {label: idx for idx, label in enumerate(labels)}
    matrix = np.zeros((len(labels), len(labels)), dtype=int)
    for truth, pred in zip(y_true, y_pred, strict=True):
        matrix[index[truth], index[pred]] += 1
    return matrix


def _metrics_from_confusion(matrix: np.ndarray, labels: tuple[str, ...]) -> ClassifierMetrics:
    total = int(matrix.sum())
    if total == 0:
        raise ValueError("Cannot compute metrics on empty confusion matrix")

    per_class: dict[str, dict[str, float]] = {}
    f1_scores: list[float] = []

    for idx, label in enumerate(labels):
        tp = int(matrix[idx, idx])
        fp = int(matrix[:, idx].sum() - tp)
        fn = int(matrix[idx, :].sum() - tp)
        support = int(matrix[idx, :].sum())

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0

        per_class[label] = {
            "support": float(support),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        if support > 0:
            f1_scores.append(f1)

    accuracy = float(np.trace(matrix) / total)
    macro_f1 = float(np.mean(f1_scores)) if f1_scores else 0.0

    return ClassifierMetrics(
        n=total,
        accuracy=accuracy,
        macro_f1=macro_f1,
        per_class=per_class,
        confusion=matrix,
        label_names=labels,
    )


def _contrast_label(has_contrast: bool) -> str:
    return "with" if has_contrast else "without"


def _build_classifier_metrics(
    truths: list[bool],
    preds: list[bool],
) -> ClassifierMetrics:
    y_true = [_contrast_label(value) for value in truths]
    y_pred = [_contrast_label(value) for value in preds]
    matrix = _confusion_matrix(y_true, y_pred, CONTRAST_LABELS)
    return _metrics_from_confusion(matrix, CONTRAST_LABELS)


def _parse_results_csv_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


def falcon_prediction_from_results_csv_row(csv_row: dict[str, str]) -> FalconPrediction | None:
    """Rebuild a ``FalconPrediction`` from a prior results CSV row, if possible."""
    series_path = Path(csv_row["series_path"]).resolve()
    error = (csv_row.get("error") or "").strip()
    if error == "no prediction returned":
        return None
    if error:
        return FalconPrediction(
            series_directory=series_path,
            body_part="",
            body_part_confidence=0.0,
            iv_contrast=False,
            iv_contrast_confidence=0.0,
            radlex_series_description="",
            error=error,
        )

    body_part_pred = (csv_row.get("body_part_pred") or "").strip()
    if not body_part_pred:
        return None

    body_part_confidence = float(csv_row.get("body_part_confidence") or 0.0)
    radlex_series_description = csv_row.get("radlex_series_description") or ""
    contrast_evaluated = _parse_results_csv_bool(csv_row.get("contrast_evaluated") or "false")

    iv_contrast_pred_raw = (csv_row.get("iv_contrast_pred") or "").strip()
    iv_contrast = _parse_results_csv_bool(iv_contrast_pred_raw) if iv_contrast_pred_raw else False
    iv_contrast_confidence = float(csv_row.get("iv_contrast_confidence") or 0.0)
    if not contrast_evaluated and not iv_contrast_pred_raw:
        iv_contrast = False
        iv_contrast_confidence = 0.0

    return FalconPrediction(
        series_directory=series_path,
        body_part=body_part_pred,
        body_part_confidence=body_part_confidence,
        iv_contrast=iv_contrast,
        iv_contrast_confidence=iv_contrast_confidence,
        radlex_series_description=radlex_series_description,
    )


def load_existing_predictions_from_csv(path: Path) -> dict[Path, FalconPrediction]:
    """Load cached per-series predictions keyed by resolved ``series_path``."""
    if not path.is_file():
        return {}

    predictions_by_path: dict[Path, FalconPrediction] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for csv_row in csv.DictReader(handle):
            prediction = falcon_prediction_from_results_csv_row(csv_row)
            if prediction is None:
                continue
            predictions_by_path[prediction.series_directory.resolve()] = prediction
    return predictions_by_path


def _collect_predictions_for_rows(
    rows: list[EvalRow],
    prediction_by_path: dict[Path, FalconPrediction],
) -> list[FalconPrediction]:
    predictions: list[FalconPrediction] = []
    for row in rows:
        prediction = prediction_by_path.get(row.series_path.resolve())
        if prediction is not None:
            predictions.append(prediction)
    return predictions


def evaluate_rows(
    rows: list[EvalRow],
    *,
    existing_predictions: dict[Path, FalconPrediction] | None = None,
) -> tuple[EvalReport, list[FalconPrediction]]:
    cached_predictions = existing_predictions or {}
    pending_rows = [
        row for row in rows if row.series_path.resolve() not in cached_predictions
    ]
    new_predictions = (
        predict_falcon_series([row.series_path for row in pending_rows])
        if pending_rows
        else []
    )

    if cached_predictions:
        logger.info(
            "Skipping %d series with existing results; running FALCON on %d series",
            len(rows) - len(pending_rows),
            len(pending_rows),
        )

    prediction_by_path = dict(cached_predictions)
    for prediction in new_predictions:
        prediction_by_path[prediction.series_directory.resolve()] = prediction

    successes: list[tuple[EvalRow, FalconPrediction]] = []
    errors: list[tuple[EvalRow, FalconPrediction | None]] = []

    for row in rows:
        pred = prediction_by_path.get(row.series_path.resolve())
        if pred is None or pred.error is not None:
            errors.append((row, pred))
        else:
            successes.append((row, pred))

    total = len(rows)
    n_success = len(successes)
    n_error = len(errors)

    body_metrics: ClassifierMetrics | None = None
    contrast_overall: ClassifierMetrics | None = None
    contrast_by_body: dict[str, ClassifierMetrics] = {}

    if successes:
        body_metrics = _metrics_from_confusion(
            _confusion_matrix(
                [row.body_part for row, _ in successes],
                [pred.body_part for _, pred in successes],
                tuple(BODY_PART_LABELS),
            ),
            tuple(BODY_PART_LABELS),
        )

        contrast_successes = [
            (row, pred) for row, pred in successes if pred.body_part == row.body_part
        ]
        if contrast_successes:
            contrast_overall = _build_classifier_metrics(
                [row.iv_contrast for row, _ in contrast_successes],
                [pred.iv_contrast for _, pred in contrast_successes],
            )

            for body_part in BODY_PART_LABELS:
                subset = [
                    (row, pred)
                    for row, pred in contrast_successes
                    if row.body_part == body_part
                ]
                if not subset:
                    continue
                contrast_by_body[body_part] = _build_classifier_metrics(
                    [row.iv_contrast for row, _ in subset],
                    [pred.iv_contrast for _, pred in subset],
                )

    label_counts: dict[str, int] = {}
    for row in rows:
        label_counts[row.label_dir] = label_counts.get(row.label_dir, 0) + 1

    report = EvalReport(
        total=total,
        n_success=n_success,
        n_error=n_error,
        eligibility_rate=n_success / total if total else 0.0,
        body_part=body_metrics,
        contrast_overall=contrast_overall,
        contrast_by_body_part=contrast_by_body,
        label_counts=label_counts,
    )
    return report, _collect_predictions_for_rows(rows, prediction_by_path)


def _format_confusion(matrix: np.ndarray, labels: tuple[str, ...]) -> str:
    col_width = max(len(label) for label in labels) + 2
    header = " " * col_width + "".join(f"{label:>{col_width}}" for label in labels)
    lines = [header]
    for idx, label in enumerate(labels):
        counts = "".join(f"{int(matrix[idx, j]):>{col_width}}" for j in range(len(labels)))
        lines.append(f"{label:>{col_width}}{counts}")
    return "\n".join(lines)


def _format_classifier_section(title: str, metrics: ClassifierMetrics) -> str:
    lines = [
        title,
        f"  n={metrics.n}  accuracy={metrics.accuracy:.4f}  macro_f1={metrics.macro_f1:.4f}",
        "  per-class:",
    ]
    for label in metrics.label_names:
        stats = metrics.per_class[label]
        lines.append(
            f"    {label:>10}  support={int(stats['support']):4d}  "
            f"P={stats['precision']:.4f}  R={stats['recall']:.4f}  F1={stats['f1']:.4f}"
        )
    lines.append("  confusion (rows=true, cols=pred):")
    for confusion_line in _format_confusion(metrics.confusion, metrics.label_names).splitlines():
        lines.append(f"    {confusion_line}")
    return "\n".join(lines)


def _dicom_metadata_display(value: object | None) -> str:
    if value is None or value == "":
        return "—"
    return str(value).strip().replace("\n", " ")


def _iv_contrast_label(iv_contrast: bool) -> str:
    return "with" if iv_contrast else "without"


def read_series_dicom_metadata(series_path: Path) -> tuple[str, str]:
    """Read SeriesDescription and contrast bolus tags from the first DICOM in a series folder."""
    dcm_files = sorted(series_path.glob("*.dcm"))
    if not dcm_files:
        return "—", "—"

    try:
        dataset = pydicom.dcmread(dcm_files[0], stop_before_pixels=True, force=True)
    except Exception as ex:
        logger.warning("Could not read DICOM metadata for %s: %s", series_path, ex)
        return "—", "—"

    series_description = _dicom_metadata_display(dataset.get("SeriesDescription"))
    agent = _dicom_metadata_display(dataset.get("ContrastBolusAgent"))
    route = _dicom_metadata_display(dataset.get("ContrastBolusRoute"))
    bolus_parts: list[str] = []
    if agent != "—":
        bolus_parts.append(f"Agent={agent}")
    if route != "—":
        bolus_parts.append(f"Route={route}")
    bolus_tags = "; ".join(bolus_parts) if bolus_parts else "—"
    return series_description, bolus_tags


def _body_part_classification_failed(row: EvalRow, prediction: FalconPrediction) -> bool:
    return prediction.error is None and prediction.body_part != row.body_part


def _contrast_evaluated(row: EvalRow, prediction: FalconPrediction) -> bool:
    """Contrast metrics and errors apply only when body-part prediction matches ground truth."""
    return prediction.error is None and prediction.body_part == row.body_part


def _contrast_classification_failed(row: EvalRow, prediction: FalconPrediction) -> bool:
    return _contrast_evaluated(row, prediction) and prediction.iv_contrast != row.iv_contrast


def _error_bp_confidence_display(row: EvalRow, prediction: FalconPrediction | None) -> str:
    if prediction is None or prediction.error or not _body_part_classification_failed(row, prediction):
        return "—"
    return format_confidence_percent(prediction.body_part_confidence)


def _error_contrast_confidence_display(row: EvalRow, prediction: FalconPrediction | None) -> str:
    if prediction is None or prediction.error or not _contrast_classification_failed(row, prediction):
        return "—"
    return format_confidence_percent(contrast_prediction_confidence(prediction))


def _failed_task_sort_key(row: EvalRow, prediction: FalconPrediction | None) -> float:
    """Sort ascending: lowest predicted-class confidence on the failed task first."""
    if prediction is None or prediction.error:
        return 2.0

    confidences: list[float] = []
    if _body_part_classification_failed(row, prediction):
        confidences.append(prediction.body_part_confidence)
    if _contrast_classification_failed(row, prediction):
        confidences.append(contrast_prediction_confidence(prediction))
    return min(confidences) if confidences else 2.0


def format_classification_error(row: EvalRow, prediction: FalconPrediction | None) -> str:
    """Describe body-part and/or contrast mistakes, or pipeline failure."""
    if prediction is None:
        return "no prediction returned"
    if prediction.error:
        return prediction.error

    if prediction.body_part != row.body_part:
        return f"body_part: gt {row.body_part} -> pred {prediction.body_part}"

    if prediction.iv_contrast != row.iv_contrast:
        return "iv_contrast: gt {} -> pred {}".format(
            _iv_contrast_label(row.iv_contrast),
            _iv_contrast_label(prediction.iv_contrast),
        )
    return ""


def collect_error_summary_entries(
    rows: list[EvalRow],
    predictions: list[FalconPrediction],
) -> list[ErrorSummaryEntry]:
    prediction_by_path = {pred.series_directory.resolve(): pred for pred in predictions}
    entries_with_sort: list[tuple[float, ErrorSummaryEntry]] = []

    for row in rows:
        prediction = prediction_by_path.get(row.series_path.resolve())
        classification_error = format_classification_error(row, prediction)
        if not classification_error:
            continue

        series_description, bolus_tags = read_series_dicom_metadata(row.series_path)
        entries_with_sort.append(
            (
                _failed_task_sort_key(row, prediction),
                ErrorSummaryEntry(
                    series_path=str(row.series_path),
                    classification_error=classification_error,
                    series_description=series_description,
                    bolus_tags=bolus_tags,
                    bp_conf=_error_bp_confidence_display(row, prediction),
                    contrast_conf=_error_contrast_confidence_display(row, prediction),
                ),
            )
        )

    entries_with_sort.sort(key=lambda item: item[0])
    return [entry for _, entry in entries_with_sort]


def _confidence_error_aggregate(confidences: list[float]) -> tuple[int, float | None, int]:
    if not confidences:
        return 0, None, 0
    values = np.asarray(confidences, dtype=float)
    return (
        int(values.size),
        float(np.median(values)),
        int(np.sum(values >= ERROR_CONFIDENCE_HIGH_THRESHOLD)),
    )


def format_error_confidence_aggregate(rows: list[EvalRow], predictions: list[FalconPrediction]) -> str:
    """Summarize predicted-class confidence on failed body-part and contrast tasks."""
    prediction_by_path = {pred.series_directory.resolve(): pred for pred in predictions}
    body_part_confidences: list[float] = []
    contrast_confidences: list[float] = []

    for row in rows:
        prediction = prediction_by_path.get(row.series_path.resolve())
        if prediction is None or prediction.error:
            continue
        if _body_part_classification_failed(row, prediction):
            body_part_confidences.append(prediction.body_part_confidence)
        if _contrast_classification_failed(row, prediction):
            contrast_confidences.append(contrast_prediction_confidence(prediction))

    threshold_pct = f"{ERROR_CONFIDENCE_HIGH_THRESHOLD * 100:.0f}%"
    lines = ["  Error confidence (predicted class, failed task only):"]

    for label, confidences in (
        ("body_part", body_part_confidences),
        ("contrast", contrast_confidences),
    ):
        count, median, high_conf = _confidence_error_aggregate(confidences)
        if count == 0:
            lines.append(f"    {label} errors: none")
            continue
        lines.append(
            f"    {label} errors: n={count}  median={format_confidence_percent(median)}  "
            f"high-conf (≥{threshold_pct}): {high_conf}"
        )

    return "\n".join(lines)


def format_error_summary_table(entries: list[ErrorSummaryEntry]) -> str:
    """Render misclassified or failed series as a fixed-column text table."""
    lines = ["", "Classification error summary"]
    if not entries:
        lines.append("  (none)")
        return "\n".join(lines)

    columns = (
        "series_path",
        "classification_error",
        "bp_conf",
        "contrast_conf",
        "series_description",
        "bolus_tags",
    )
    widths = [
        max(len(columns[idx]), max(len(getattr(entry, columns[idx])) for entry in entries))
        for idx in range(len(columns))
    ]
    col_gap = "  "
    header = col_gap.join(columns[idx].ljust(widths[idx]) for idx in range(len(columns)))
    lines.append(header)
    lines.append(col_gap.join("-" * widths[idx] for idx in range(len(columns))))

    for entry in entries:
        values = (
            entry.series_path,
            entry.classification_error,
            entry.bp_conf,
            entry.contrast_conf,
            entry.series_description,
            entry.bolus_tags,
        )
        lines.append(col_gap.join(values[idx].ljust(widths[idx]) for idx in range(len(values))))

    lines.append(f"  {len(entries)} series with classification or pipeline errors")
    return "\n".join(lines)


def format_error_summary_section(rows: list[EvalRow], predictions: list[FalconPrediction]) -> str:
    entries = collect_error_summary_entries(rows, predictions)
    lines = [format_error_summary_table(entries)]
    if entries:
        lines.append(format_error_confidence_aggregate(rows, predictions))
    return "\n".join(lines)


def format_report(report: EvalReport) -> str:
    lines = [
        "FALCON evaluation summary",
        f"  total={report.total}  success={report.n_success}  error={report.n_error}  "
        f"eligibility_rate={report.eligibility_rate:.4f}",
        "  label folders:",
    ]
    for label_dir, count in sorted(report.label_counts.items()):
        lines.append(f"    {label_dir}: {count} series")

    if report.n_error:
        lines.append("  (metrics below exclude series with prediction/preprocess errors)")

    if report.body_part is not None:
        lines.append("")
        lines.append(_format_classifier_section("Body part", report.body_part))

    if report.contrast_overall is not None:
        lines.append("")
        lines.append(
            _format_classifier_section(
                "IV contrast (body-part correct; contrast not scored when body part is wrong)",
                report.contrast_overall,
            )
        )

    for body_part in BODY_PART_LABELS:
        metrics = report.contrast_by_body_part.get(body_part)
        if metrics is None:
            continue
        lines.append("")
        lines.append(_format_classifier_section(f"IV contrast (ground-truth body part = {body_part})", metrics))

    return "\n".join(lines)


def default_results_csv_path(data_dir: Path) -> Path:
    return data_dir.resolve() / FALCON_EVAL_RESULTS_FILENAME


def resolve_results_csv_path(
    data_dir: Path,
    output: Path | None,
    *,
    no_results_file: bool,
) -> Path | None:
    if no_results_file:
        return None
    return output.resolve() if output is not None else default_results_csv_path(data_dir)


def _results_csv_row(row: EvalRow, prediction: FalconPrediction | None) -> dict[str, object]:
    series_description, bolus_tags = read_series_dicom_metadata(row.series_path)
    base: dict[str, object] = {
        "label_dir": row.label_dir,
        "series_path": str(row.series_path),
        "body_part_gt": row.body_part,
        "iv_contrast_gt": row.iv_contrast,
        "series_description": series_description,
        "bolus_tags": bolus_tags,
    }
    if prediction is None:
        return {
            **base,
            "classification_error": "no prediction returned",
            "error": "no prediction returned",
        }

    body_ok = prediction.error is None and prediction.body_part == row.body_part
    contrast_evaluated = _contrast_evaluated(row, prediction)
    row_data: dict[str, object] = {
        **base,
        "body_part_pred": prediction.body_part,
        "body_part_confidence": prediction.body_part_confidence,
        "radlex_series_description": prediction.radlex_series_description,
        "body_part_correct": body_ok,
        "contrast_evaluated": contrast_evaluated,
        "classification_error": format_classification_error(row, prediction),
        "error": prediction.error or "",
    }
    if contrast_evaluated:
        row_data.update(
            {
                "iv_contrast_pred": prediction.iv_contrast,
                "iv_contrast_confidence": prediction.iv_contrast_confidence,
                "iv_contrast_class_confidence": contrast_prediction_confidence(prediction),
                "iv_contrast_correct": prediction.iv_contrast == row.iv_contrast,
            }
        )
    return row_data


def _safe_artifact_component(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in value)


def _artifact_series_filename(row: EvalRow) -> str:
    return f"{_safe_artifact_component(row.series_path.name)}.png"


_BODY_PART_ARTIFACT_LABELS: dict[str, str] = {
    "HeadNeck": "HEADNECK",
    "Chest": "CHEST",
    "Abdomen": "ABDOMEN",
}


def _artifact_body_part_label(body_part: str) -> str:
    return _BODY_PART_ARTIFACT_LABELS.get(body_part, body_part.upper())


def _body_part_summary_slug(body_part: str) -> str:
    return _artifact_body_part_label(body_part).lower()


def body_part_error_summary_path(artifact_root: Path, body_part: str) -> Path:
    return (
        artifact_root
        / FALCON_EVAL_BODY_PART_ERROR_SUMMARY_DIR
        / f"{_body_part_summary_slug(body_part)}_errors.png"
    )


def body_part_success_summary_path(artifact_root: Path, body_part: str) -> Path:
    return (
        artifact_root
        / FALCON_EVAL_BODY_PART_SUCCESS_SUMMARY_DIR
        / f"{_body_part_summary_slug(body_part)}_success.png"
    )


def body_part_error_matrix_title(body_part: str) -> str:
    return f"FALCON body part errors: {_artifact_body_part_label(body_part)}"


def body_part_success_matrix_title(body_part: str) -> str:
    return f"FALCON body part successes: {_artifact_body_part_label(body_part)}"


def _artifact_contrast_label(iv_contrast: bool) -> str:
    return "WITH" if iv_contrast else "WITHOUT"


def _artifact_confidence_label(confidence: float) -> str:
    return f"{confidence * 100.0:.0f}%"


def body_part_artifact_title(row: EvalRow, prediction: FalconPrediction) -> str:
    return "GT: {}->{}\n{}".format(
        _artifact_body_part_label(row.body_part),
        _artifact_body_part_label(prediction.body_part),
        _artifact_confidence_label(prediction.body_part_confidence),
    )


def body_part_success_artifact_title(row: EvalRow, prediction: FalconPrediction) -> str:
    return "GT: {}\n{}".format(
        _artifact_body_part_label(row.body_part),
        _artifact_confidence_label(prediction.body_part_confidence),
    )


def contrast_success_artifact_title(row: EvalRow, prediction: FalconPrediction) -> str:
    return "GT: {}\n{}".format(
        _artifact_contrast_label(row.iv_contrast),
        _artifact_confidence_label(contrast_prediction_confidence(prediction)),
    )


def contrast_artifact_title(row: EvalRow, prediction: FalconPrediction) -> str:
    return "GT: {}->{}\n{}".format(
        _artifact_contrast_label(row.iv_contrast),
        _artifact_contrast_label(prediction.iv_contrast),
        _artifact_confidence_label(contrast_prediction_confidence(prediction)),
    )


def body_part_error_artifact_path(artifact_root: Path, row: EvalRow) -> Path:
    return (
        artifact_root
        / FALCON_EVAL_ERRORS_BODY_PART_DIR
        / _safe_artifact_component(row.label_dir)
        / _artifact_series_filename(row)
    )


def contrast_error_artifact_path(artifact_root: Path, row: EvalRow) -> Path:
    return (
        artifact_root
        / FALCON_EVAL_ERRORS_CONTRAST_DIR
        / _safe_artifact_component(row.label_dir)
        / _artifact_series_filename(row)
    )


def contrast_success_artifact_path(artifact_root: Path, row: EvalRow) -> Path:
    return (
        artifact_root
        / FALCON_EVAL_SUCCESS_CONTRAST_DIR
        / _safe_artifact_component(row.label_dir)
        / _artifact_series_filename(row)
    )


def summary_grid_dimension(case_count: int) -> int:
    """
    Choose a square grid up to 6×6 that fits ``case_count`` thumbnails.

    Uses 6×6 only when more than 25 cases; otherwise the smallest square that fits
    (e.g. 12 cases -> 4×4, 20 cases -> 5×5).
    """
    if case_count <= 0:
        return 0
    if case_count > 25:
        return SUMMARY_MAX_GRID_DIMENSION
    return min(5, max(1, math.ceil(math.sqrt(case_count))))


def _body_part_classification_succeeded(row: EvalRow, prediction: FalconPrediction) -> bool:
    return prediction.error is None and prediction.body_part == row.body_part


def _contrast_classification_succeeded(row: EvalRow, prediction: FalconPrediction) -> bool:
    return _contrast_evaluated(row, prediction) and prediction.iv_contrast == row.iv_contrast


def _artifact_confidence_sort_key(artifact: SavedEvalArtifact) -> float:
    if artifact.task_kind == "body_part":
        return artifact.prediction.body_part_confidence
    return contrast_prediction_confidence(artifact.prediction)


def filter_error_artifacts_for_category(
    saved_artifacts: list[SavedEvalArtifact],
    category_key: str,
) -> list[SavedEvalArtifact]:
    if category_key == "body_part":
        return [artifact for artifact in saved_artifacts if artifact.task_kind == "body_part"]
    if category_key == "contrast_without_pred_with":
        return [
            artifact
            for artifact in saved_artifacts
            if artifact.task_kind == "contrast"
            and not artifact.row.iv_contrast
            and artifact.prediction.iv_contrast
        ]
    if category_key == "contrast_with_pred_without":
        return [
            artifact
            for artifact in saved_artifacts
            if artifact.task_kind == "contrast"
            and artifact.row.iv_contrast
            and not artifact.prediction.iv_contrast
        ]
    raise ValueError(f"Unknown error summary category: {category_key}")


def filter_contrast_success_artifacts_for_category(
    saved_artifacts: list[SavedEvalArtifact],
    category_key: str,
) -> list[SavedEvalArtifact]:
    if category_key == "contrast_without_pred_without":
        return [
            artifact
            for artifact in saved_artifacts
            if artifact.task_kind == "contrast"
            and not artifact.row.iv_contrast
            and not artifact.prediction.iv_contrast
        ]
    if category_key == "contrast_with_pred_with":
        return [
            artifact
            for artifact in saved_artifacts
            if artifact.task_kind == "contrast"
            and artifact.row.iv_contrast
            and artifact.prediction.iv_contrast
        ]
    raise ValueError(f"Unknown contrast success summary category: {category_key}")


def save_summary_matrix(
    output_path: Path,
    cell_images: list[Image.Image],
    *,
    title: str,
    count_label: str,
) -> Path | None:
    """Render one summary gallery (up to 6×6, shrinking when fewer cases)."""
    display_images = cell_images[:SUMMARY_MAX_ARTIFACTS]
    case_count = len(display_images)
    if case_count == 0:
        return None

    grid_dimension = summary_grid_dimension(case_count)
    cell_size = SUMMARY_CELL_SIZE
    gap = SUMMARY_MATRIX_GAP
    header_height = 40
    font = ImageFont.load_default()

    canvas_width = (grid_dimension * cell_size) + ((grid_dimension + 1) * gap)
    canvas_height = header_height + (grid_dimension * cell_size) + ((grid_dimension + 1) * gap)
    canvas = Image.new("RGB", (canvas_width, canvas_height), (32, 32, 32))
    draw = ImageDraw.Draw(canvas)
    draw.text((gap, gap), title, fill=(255, 255, 255), font=font)
    subtitle = f"{case_count} {count_label}  |  {grid_dimension}×{grid_dimension} grid"
    draw.text((gap, gap + 14), subtitle, fill=(180, 180, 180), font=font)

    grid_top = header_height + gap
    for cell_index, thumbnail in enumerate(display_images):
        row_index = cell_index // grid_dimension
        column_index = cell_index % grid_dimension
        cell_x = gap + column_index * (cell_size + gap)
        cell_y = grid_top + row_index * (cell_size + gap)
        canvas.paste(thumbnail, (cell_x, cell_y))

    for cell_index in range(case_count, grid_dimension * grid_dimension):
        row_index = cell_index // grid_dimension
        column_index = cell_index % grid_dimension
        cell_x = gap + column_index * (cell_size + gap)
        cell_y = grid_top + row_index * (cell_size + gap)
        draw.rectangle(
            (cell_x, cell_y, cell_x + cell_size, cell_y + cell_size),
            fill=(56, 56, 56),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path


def _artifact_thumbnail_images(
    artifacts: list[SavedEvalArtifact],
    *,
    sort_descending: bool,
) -> list[Image.Image]:
    sort_key = _artifact_confidence_sort_key
    display_artifacts = (
        sorted(artifacts, key=sort_key, reverse=True)
        if sort_descending
        else sorted(artifacts, key=sort_key)
    )[:SUMMARY_MAX_ARTIFACTS]
    thumbnails: list[Image.Image] = []
    for artifact in display_artifacts:
        with Image.open(artifact.image_path) as thumbnail_source:
            thumbnails.append(
                thumbnail_source.resize((SUMMARY_CELL_SIZE, SUMMARY_CELL_SIZE)).copy()
            )
    return thumbnails


def save_category_summary_matrix_from_artifacts(
    output_path: Path,
    artifacts: list[SavedEvalArtifact],
    *,
    title: str,
    count_label: str,
    sort_descending: bool = False,
) -> Path | None:
    """Build a summary matrix from saved per-series PNG artifacts."""
    return save_summary_matrix(
        output_path,
        _artifact_thumbnail_images(artifacts, sort_descending=sort_descending),
        title=title,
        count_label=count_label,
    )


def filter_body_part_error_artifacts_for_gt(
    saved_artifacts: list[SavedEvalArtifact],
    body_part_gt: str,
) -> list[SavedEvalArtifact]:
    return [
        artifact
        for artifact in saved_artifacts
        if artifact.task_kind == "body_part" and artifact.row.body_part == body_part_gt
    ]


def save_body_part_error_summary_matrices(
    artifact_root: Path,
    saved_artifacts: list[SavedEvalArtifact],
) -> list[Path]:
    """Write one body-part error mosaic per ground-truth class under ``body_part/error/``."""
    output_paths: list[Path] = []
    for body_part in BODY_PART_LABELS:
        category_artifacts = filter_body_part_error_artifacts_for_gt(saved_artifacts, body_part)
        output_path = save_category_summary_matrix_from_artifacts(
            body_part_error_summary_path(artifact_root, body_part),
            category_artifacts,
            title=body_part_error_matrix_title(body_part),
            count_label="error(s)",
            sort_descending=False,
        )
        if output_path is not None:
            output_paths.append(output_path)
    return output_paths


def save_error_summary_matrices(
    artifact_root: Path,
    saved_artifacts: list[SavedEvalArtifact],
) -> list[Path]:
    """Write per-body-part error mosaics and contrast error summary grids."""
    output_paths = save_body_part_error_summary_matrices(artifact_root, saved_artifacts)
    for category_key, title, filename in CONTRAST_ERROR_SUMMARY_CATEGORIES:
        category_artifacts = filter_error_artifacts_for_category(saved_artifacts, category_key)
        output_path = save_category_summary_matrix_from_artifacts(
            artifact_root / filename,
            category_artifacts,
            title=title,
            count_label="error(s)",
            sort_descending=False,
        )
        if output_path is not None:
            output_paths.append(output_path)
    return output_paths


def _body_part_success_candidates_by_gt(
    rows: list[EvalRow],
    predictions: list[FalconPrediction],
) -> dict[str, list[tuple[EvalRow, FalconPrediction]]]:
    prediction_by_path = {pred.series_directory.resolve(): pred for pred in predictions}
    candidates: dict[str, list[tuple[EvalRow, FalconPrediction]]] = {
        body_part: [] for body_part in BODY_PART_LABELS
    }

    for row in rows:
        prediction = prediction_by_path.get(row.series_path.resolve())
        if prediction is None or prediction.error:
            continue
        if not _body_part_classification_succeeded(row, prediction):
            continue
        candidates[row.body_part].append((row, prediction))

    return candidates


def _select_top_body_part_successes(
    candidates: list[tuple[EvalRow, FalconPrediction]],
) -> list[tuple[EvalRow, FalconPrediction]]:
    return sorted(
        candidates,
        key=lambda item: item[1].body_part_confidence,
        reverse=True,
    )[:SUMMARY_MAX_ARTIFACTS]


def _preprocess_series_for_matrix(rows: list[EvalRow]) -> dict[Path, np.ndarray]:
    preprocessed: dict[Path, np.ndarray] = {}
    for row in rows:
        series_path = row.series_path.resolve()
        if series_path in preprocessed:
            continue
        try:
            preprocessed[series_path] = preprocess_series(row.series_path)
        except Exception as exc:
            logger.warning(
                "Could not preprocess series for summary matrix %s: %s",
                row.series_path,
                exc,
            )
    return preprocessed


def _body_part_success_thumbnails(
    items: list[tuple[EvalRow, FalconPrediction]],
    preprocessed_by_series: dict[Path, np.ndarray],
) -> list[Image.Image]:
    thumbnails: list[Image.Image] = []
    for row, prediction in items:
        image_np = preprocessed_by_series.get(row.series_path.resolve())
        if image_np is None:
            continue
        thumbnails.append(
            render_body_part_model_input_thumbnail(
                image_np,
                title=body_part_success_artifact_title(row, prediction),
                size=SUMMARY_CELL_SIZE,
            )
        )
    return thumbnails


def save_body_part_success_summary_matrices(
    rows: list[EvalRow],
    predictions: list[FalconPrediction],
    artifact_root: Path,
) -> list[Path]:
    """Build one body-part success mosaic per GT class on the fly under ``body_part/success/``."""
    candidates_by_gt = _body_part_success_candidates_by_gt(rows, predictions)
    selected_by_gt = {
        body_part: _select_top_body_part_successes(candidates_by_gt[body_part])
        for body_part in BODY_PART_LABELS
    }
    unique_rows = {
        row for items in selected_by_gt.values() for row, _prediction in items
    }
    preprocessed_by_series = _preprocess_series_for_matrix(list(unique_rows))

    output_paths: list[Path] = []
    for body_part in BODY_PART_LABELS:
        thumbnails = _body_part_success_thumbnails(
            selected_by_gt[body_part],
            preprocessed_by_series,
        )
        output_path = save_summary_matrix(
            body_part_success_summary_path(artifact_root, body_part),
            thumbnails,
            title=body_part_success_matrix_title(body_part),
            count_label="success(es)",
        )
        if output_path is not None:
            output_paths.append(output_path)
    return output_paths


def save_contrast_success_summary_matrices(
    artifact_root: Path,
    saved_artifacts: list[SavedEvalArtifact],
) -> list[Path]:
    """Write contrast success summary grids from saved per-series PNGs."""
    output_paths: list[Path] = []
    for category_key, title, filename in CONTRAST_SUCCESS_SUMMARY_CATEGORIES:
        category_artifacts = filter_contrast_success_artifacts_for_category(
            saved_artifacts,
            category_key,
        )
        output_path = save_category_summary_matrix_from_artifacts(
            artifact_root / filename,
            category_artifacts,
            title=title,
            count_label="success(es)",
            sort_descending=True,
        )
        if output_path is not None:
            output_paths.append(output_path)
    return output_paths


def save_success_summary_matrices(
    rows: list[EvalRow],
    predictions: list[FalconPrediction],
    artifact_root: Path,
    saved_contrast_artifacts: list[SavedEvalArtifact],
) -> list[Path]:
    """Write body-part success mosaics on the fly and contrast success grids from PNGs."""
    output_paths = save_body_part_success_summary_matrices(rows, predictions, artifact_root)
    output_paths.extend(
        save_contrast_success_summary_matrices(artifact_root, saved_contrast_artifacts)
    )
    return output_paths


def _contrast_success_candidates_by_category(
    rows: list[EvalRow],
    predictions: list[FalconPrediction],
) -> dict[str, list[tuple[EvalRow, FalconPrediction]]]:
    prediction_by_path = {pred.series_directory.resolve(): pred for pred in predictions}
    candidates: dict[str, list[tuple[EvalRow, FalconPrediction]]] = {
        category_key: [] for category_key, _, _ in CONTRAST_SUCCESS_SUMMARY_CATEGORIES
    }

    for row in rows:
        prediction = prediction_by_path.get(row.series_path.resolve())
        if prediction is None or prediction.error:
            continue
        if not _contrast_classification_succeeded(row, prediction):
            continue
        if row.iv_contrast:
            candidates["contrast_with_pred_with"].append((row, prediction))
        else:
            candidates["contrast_without_pred_without"].append((row, prediction))

    return candidates


def _select_top_contrast_successes(
    candidates: list[tuple[EvalRow, FalconPrediction]],
) -> list[tuple[EvalRow, FalconPrediction]]:
    return sorted(
        candidates,
        key=lambda item: contrast_prediction_confidence(item[1]),
        reverse=True,
    )[:SUMMARY_MAX_ARTIFACTS]


def save_classification_error_artifacts(
    rows: list[EvalRow],
    predictions: list[FalconPrediction],
    artifact_root: Path,
) -> list[SavedEvalArtifact]:
    """
    Save model-input PNGs for classification errors under ``errors/body_part/`` and
    ``errors/contrast/``. Contrast artifacts are omitted when body-part prediction fails.
    """
    prediction_by_path = {pred.series_directory.resolve(): pred for pred in predictions}
    saved_artifacts: list[SavedEvalArtifact] = []

    for row in rows:
        prediction = prediction_by_path.get(row.series_path.resolve())
        if prediction is None or prediction.error:
            continue

        needs_body_png = _body_part_classification_failed(row, prediction)
        needs_contrast_png = _contrast_classification_failed(row, prediction)
        if not needs_body_png and not needs_contrast_png:
            continue

        body_output_png = body_part_error_artifact_path(artifact_root, row) if needs_body_png else None
        contrast_output_png = (
            contrast_error_artifact_path(artifact_root, row) if needs_contrast_png else None
        )
        body_png_exists = body_output_png is not None and body_output_png.is_file()
        contrast_png_exists = contrast_output_png is not None and contrast_output_png.is_file()

        if body_png_exists and body_output_png is not None:
            saved_artifacts.append(
                SavedEvalArtifact(
                    row=row,
                    prediction=prediction,
                    image_path=body_output_png,
                    task_kind="body_part",
                )
            )
        if contrast_png_exists and contrast_output_png is not None:
            saved_artifacts.append(
                SavedEvalArtifact(
                    row=row,
                    prediction=prediction,
                    image_path=contrast_output_png,
                    task_kind="contrast",
                )
            )

        needs_body_write = needs_body_png and not body_png_exists
        needs_contrast_write = needs_contrast_png and not contrast_png_exists
        if not needs_body_write and not needs_contrast_write:
            continue

        try:
            image_np = preprocess_series(row.series_path)
        except Exception as exc:
            logger.warning(
                "Could not preprocess series for error artifacts %s: %s",
                row.series_path,
                exc,
            )
            continue

        if needs_body_write and body_output_png is not None:
            try:
                save_body_part_model_input_png(
                    image_np,
                    body_output_png,
                    title=body_part_artifact_title(row, prediction),
                )
                saved_artifacts.append(
                    SavedEvalArtifact(
                        row=row,
                        prediction=prediction,
                        image_path=body_output_png,
                        task_kind="body_part",
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Could not save body-part model input PNG for %s: %s",
                    row.series_path,
                    exc,
                )

        if needs_contrast_write and contrast_output_png is not None:
            try:
                save_contrast_model_input_png(
                    image_np,
                    prediction.body_part,
                    contrast_output_png,
                    title=contrast_artifact_title(row, prediction),
                )
                saved_artifacts.append(
                    SavedEvalArtifact(
                        row=row,
                        prediction=prediction,
                        image_path=contrast_output_png,
                        task_kind="contrast",
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Could not save contrast model input PNG for %s: %s",
                    row.series_path,
                    exc,
                )

    return saved_artifacts


def save_contrast_success_artifacts(
    rows: list[EvalRow],
    predictions: list[FalconPrediction],
    artifact_root: Path,
) -> list[SavedEvalArtifact]:
    """
    Save contrast success PNGs for up to 36 highest-confidence cases per contrast category.

    Body-part success mosaics are rendered on the fly in
    ``save_body_part_success_summary_matrices`` and do not write per-series files.
    """
    candidates_by_category = _contrast_success_candidates_by_category(rows, predictions)
    saved_artifacts: list[SavedEvalArtifact] = []
    saved_artifact_keys: set[Path] = set()

    def record_saved_artifact(
        row: EvalRow,
        prediction: FalconPrediction,
        output_png: Path,
    ) -> None:
        artifact_key = output_png.resolve()
        if artifact_key in saved_artifact_keys:
            return
        saved_artifact_keys.add(artifact_key)
        saved_artifacts.append(
            SavedEvalArtifact(
                row=row,
                prediction=prediction,
                image_path=output_png,
                task_kind="contrast",
            )
        )

    for category_key, _, _ in CONTRAST_SUCCESS_SUMMARY_CATEGORIES:
        for row, prediction in _select_top_contrast_successes(
            candidates_by_category[category_key]
        ):
            output_png = contrast_success_artifact_path(artifact_root, row)
            if output_png.is_file():
                record_saved_artifact(row, prediction, output_png)
                continue

            try:
                image_np = preprocess_series(row.series_path)
            except Exception as exc:
                logger.warning(
                    "Could not preprocess series for contrast success artifacts %s: %s",
                    row.series_path,
                    exc,
                )
                continue

            try:
                save_contrast_model_input_png(
                    image_np,
                    prediction.body_part,
                    output_png,
                    title=contrast_success_artifact_title(row, prediction),
                )
                record_saved_artifact(row, prediction, output_png)
            except Exception as exc:
                logger.warning(
                    "Could not save contrast success model input PNG for %s: %s",
                    row.series_path,
                    exc,
                )

    return saved_artifacts


def write_results_csv(path: Path, rows: list[EvalRow], predictions: list[FalconPrediction]) -> None:
    prediction_by_path = {pred.series_directory.resolve(): pred for pred in predictions}
    fieldnames = [
        "label_dir",
        "series_path",
        "body_part_gt",
        "iv_contrast_gt",
        "body_part_pred",
        "body_part_confidence",
        "radlex_series_description",
        "body_part_correct",
        "contrast_evaluated",
        "iv_contrast_pred",
        "iv_contrast_confidence",
        "iv_contrast_class_confidence",
        "iv_contrast_correct",
        "classification_error",
        "series_description",
        "bolus_tags",
        "error",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            prediction = prediction_by_path.get(row.series_path.resolve())
            writer.writerow(_results_csv_row(row, prediction))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate FALCON accuracy from first-level labeled subdirectories."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Root directory whose first-level subfolders encode ground-truth labels",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            f"Per-series results CSV (default: <data-dir>/{FALCON_EVAL_RESULTS_FILENAME}; "
            "use --no-results-file to skip)"
        ),
    )
    parser.add_argument(
        "--no-results-file",
        action="store_true",
        help="Do not write a per-series results CSV",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    data_dir = args.data_dir.resolve()
    try:
        rows = load_eval_rows(data_dir)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    results_path = resolve_results_csv_path(data_dir, args.output, no_results_file=args.no_results_file)
    existing_predictions = (
        load_existing_predictions_from_csv(results_path) if results_path is not None else {}
    )

    report, predictions = evaluate_rows(rows, existing_predictions=existing_predictions)
    print(format_report(report))
    print(format_error_summary_section(rows, predictions))

    if results_path is not None:
        write_results_csv(results_path, rows, predictions)
        print(f"\nWrote per-series results: {results_path}")

        artifact_root = data_dir / FALCON_EVAL_ARTIFACTS_DIRNAME
        saved_error_artifacts = save_classification_error_artifacts(rows, predictions, artifact_root)
        body_error_png_count = sum(
            1 for artifact in saved_error_artifacts if artifact.task_kind == "body_part"
        )
        contrast_error_png_count = sum(
            1 for artifact in saved_error_artifacts if artifact.task_kind == "contrast"
        )
        if body_error_png_count:
            print(
                f"Wrote {body_error_png_count} body-part error PNG(s) under: "
                f"{(artifact_root / FALCON_EVAL_ERRORS_BODY_PART_DIR).resolve()}"
            )
        if contrast_error_png_count:
            print(
                f"Wrote {contrast_error_png_count} contrast error PNG(s) under: "
                f"{(artifact_root / FALCON_EVAL_ERRORS_CONTRAST_DIR).resolve()}"
            )
        error_summary_matrix_paths = save_error_summary_matrices(artifact_root, saved_error_artifacts)
        for summary_matrix_path in error_summary_matrix_paths:
            print(f"Wrote error summary matrix: {summary_matrix_path.resolve()}")
        body_part_error_matrices = [
            path
            for path in error_summary_matrix_paths
            if FALCON_EVAL_BODY_PART_ERROR_SUMMARY_DIR in path.parents
        ]
        if body_part_error_matrices:
            print(
                "Body-part error mosaics: "
                f"{(artifact_root / FALCON_EVAL_BODY_PART_ERROR_SUMMARY_DIR).resolve()}"
            )

        saved_contrast_success_artifacts = save_contrast_success_artifacts(
            rows, predictions, artifact_root
        )
        contrast_success_png_count = len(saved_contrast_success_artifacts)
        if contrast_success_png_count:
            print(
                f"Wrote {contrast_success_png_count} contrast success PNG(s) under: "
                f"{(artifact_root / FALCON_EVAL_SUCCESS_CONTRAST_DIR).resolve()}"
            )
        success_summary_matrix_paths = save_success_summary_matrices(
            rows,
            predictions,
            artifact_root,
            saved_contrast_success_artifacts,
        )
        for summary_matrix_path in success_summary_matrix_paths:
            print(f"Wrote success summary matrix: {summary_matrix_path.resolve()}")
        body_part_success_matrices = [
            path
            for path in success_summary_matrix_paths
            if FALCON_EVAL_BODY_PART_SUCCESS_SUMMARY_DIR in path.parents
        ]
        if body_part_success_matrices:
            print(
                "Body-part success mosaics: "
                f"{(artifact_root / FALCON_EVAL_BODY_PART_SUCCESS_SUMMARY_DIR).resolve()}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
