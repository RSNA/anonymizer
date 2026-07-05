#!/usr/bin/env python3
"""
End-to-end CLI eval for TotalSegmentator body region + IV contrast via ``analyze_series``.

Ground truth is parsed from first-level label directory names under ``--data-dir``
(same rules as ght-qcxr ``ct_volume.labels.parse_body_part_label``), e.g.::

    A_DATA/HEAD_WITH/<study>/<series>/*.dcm
    A_DATA/CHEST_WITHOUT/<study>/<series>/*.dcm

Requires: ``uv sync --extra tseg`` (TotalSegmentator, XGBoost). No FALCON.

Run::

    uv run python src/prototyping/ct_eval.py \\
        --data-dir /path/to/A_DATA \\
        --output-dir artifacts/ct_eval \\
        --per-class 10

Flags
-----
``--data-dir PATH``   Labeled CT root (default: ~/Downloads/A_DATA).
``--output-dir PATH`` Write ``ct_eval_results.csv`` and ``ct_eval_summary.json`` here.
``--per-class N``     Max series per label folder (``HEAD_WITH``, ``CHEST_WITHOUT``, …).
``-v`` / ``--verbose``  DEBUG logging.

Outputs
-------
**``ct_eval_results.csv``** — one row per series. Prediction columns plus DICOM geometry
(from ``.tseg_cache/geometry.json``, resolved before TS when missing):

+-------------------------------+------------------------------------------+
| Column                        | Meaning                                  |
+===============================+==========================================+
| geometry_plane                | axial / coronal / sagittal / oblique     |
| geometry_plane_confidence     | 0–1 confidence in plane classification   |
| geometry_dimensionality       | volume_3d, localizer_2d, single_slice_2d |
| geometry_provenance           | original / derived_3d_render / …         |
| geometry_n_slices             | slice count in stack                     |
| geometry_ts_suitable          | True if TS segmentation should run       |
| geometry_metadata_suspect     | True if headers look inconsistent        |
| geometry_method               | dicom_headers (etc.)                     |
+-------------------------------+------------------------------------------+

**``ct_eval_summary.json``** — aggregate metrics plus geometry breakdowns:

- ``by_geometry_plane``, ``by_geometry_dimensionality``, ``by_geometry_provenance``
- ``geometry_routing`` — TS eligible vs ineligible vs unknown (fail rates, accuracy)
- ``geometry_impact_by_plane``, ``geometry_impact_by_dimensionality`` — per-group
  ``n``, ``n_ok``, ``n_failed``, ``fail_rate``, ``n_ts_suitable``, ``n_ts_not_suitable``

Console output includes a **Geometry routing impact** section (fail = TS skip or pipeline
error) and a per-series table with an acquisition **plane** column.

Email-friendly HTML copy of this reference: ``src/prototyping/ct/ct_eval_cli.html``.
"""

from __future__ import annotations

# Running as ``python src/prototyping/ct/ct_eval.py`` puts ``ct/`` on sys.path; avoid
# prepending ``prototyping/`` on sys.path before stdlib imports (see ct_eval shim).
import os
import sys
from pathlib import Path as _Path

# Before any subprocess/torch import: clear macOS malloc debug env inherited from shell/Xcode.
for _malloc_var in (
    "MallocStackLogging",
    "MallocStackLoggingNoCompact",
    "MallocScribble",
    "MallocGuardEdges",
):
    os.environ.pop(_malloc_var, None)

_SCRIPT_DIR = str(_Path(__file__).resolve().parent)
if sys.path[0] == _SCRIPT_DIR:
    sys.path.pop(0)
_SRC_ROOT = str(_Path(__file__).resolve().parents[2])
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

import argparse
import csv
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from anonymizer.controller.tseg.dicom_geometry import (
    SeriesGeometryResult,
    resolve_series_geometry,
)
from anonymizer.controller.tseg.runtime import configure_macos_subprocess_env
from anonymizer.controller.tseg.segment import TS_result, analyze_series

configure_macos_subprocess_env()

logger = logging.getLogger(__name__)

BODY_PARTS: tuple[str, ...] = ("Head", "Chest", "Abdomen")
CONTRAST_LABELS: tuple[str, ...] = ("WITHOUT", "WITH")
BODY_PART_NONE = "(none)"
DEFAULT_DATA_DIR = Path("/Users/michaelevans/Downloads/A_DATA")

GEOMETRY_COLUMNS: tuple[str, ...] = (
    "geometry_plane",
    "geometry_plane_confidence",
    "geometry_dimensionality",
    "geometry_provenance",
    "geometry_n_slices",
    "geometry_ts_suitable",
    "geometry_metadata_suspect",
    "geometry_method",
)

RESULT_COLUMNS: tuple[str, ...] = (
    "series_index",
    "series_uid",
    "series_path",
    "label_dir",
    "body_part_gt",
    "iv_contrast_gt",
    "body_part_pred",
    "body_parts_present",
    "multi_region",
    "region_fraction",
    "body_part_correct",
    "body_part_dominant_match",
    "iv_contrast_pred",
    "contrast_phase",
    "phase_probability",
    "iv_contrast_correct",
    *GEOMETRY_COLUMNS,
    "error",
    "elapsed_sec",
    "status",
)


@dataclass(frozen=True)
class VolumeGroundTruth:
    body_part: str
    iv_contrast: bool
    label_dir: str


@dataclass(frozen=True)
class SeriesRecord:
    series_path: Path
    label_dir: str
    body_part_gt: str
    iv_contrast_gt: bool


def parse_body_part_label(dirname: str) -> VolumeGroundTruth:
    """Parse Head / Chest / Abdomen and contrast from a label folder name."""
    joined = dirname.upper().replace("-", "_")
    tokens = [token for token in joined.split("_") if token]

    if "WITHOUT" in joined or "WO" in tokens or "NONCONTRAST" in joined or "NC" in tokens:
        iv_contrast = False
    elif "WITH" in joined or "W" in tokens or "CONTRAST" in joined:
        iv_contrast = True
    else:
        raise ValueError(
            f"Cannot parse contrast from directory name {dirname!r}. Include WITH/W or WITHOUT/WO."
        )

    if "ABDOMEN" in joined or "ABD" in tokens or "PELVIS" in joined:
        body_part = "Abdomen"
    elif "CHEST" in joined or "CH" in tokens or "THORAX" in joined:
        body_part = "Chest"
    elif (
        "HEADNECK" in joined
        or ("HEAD" in tokens and "NECK" in tokens)
        or "HEAD" in tokens
        or "NECK" in tokens
        or "HN" in tokens
    ):
        body_part = "Head"
    else:
        raise ValueError(
            f"Cannot parse body part from directory name {dirname!r}. "
            "Expected HEAD_*, CHEST_*, or ABDOMEN_*."
        )

    return VolumeGroundTruth(body_part=body_part, iv_contrast=iv_contrast, label_dir=dirname)


def _series_dir_has_dicoms(series_dir: Path) -> bool:
    for entry in series_dir.iterdir():
        if not entry.is_file() or entry.name.startswith("."):
            continue
        name = entry.name.lower()
        if name.endswith(".dcm") or name.endswith(".dicom") or "." not in entry.name:
            return True
    return False


def iter_series_directories(label_root: Path):
    """Yield ``label_root/<study>/<series>/`` directories that contain DICOM files."""
    if not label_root.is_dir():
        return
    for study_dir in sorted(label_root.iterdir()):
        if not study_dir.is_dir() or study_dir.name.startswith("."):
            continue
        for series_dir in sorted(study_dir.iterdir()):
            if not series_dir.is_dir() or series_dir.name.startswith("."):
                continue
            if _series_dir_has_dicoms(series_dir):
                yield series_dir.resolve()


def discover_series(
    data_dir: Path,
    *,
    per_class: int | None = None,
) -> list[SeriesRecord]:
    """
    Discover labeled series under ``data_dir``.

    When ``per_class`` is set, include at most that many series per **label
    subdirectory** (e.g. ``HEAD_WITHOUT``, ``CHEST_WITH``), in sorted path order.
    """
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        raise ValueError(f"Data directory not found: {data_dir}")

    label_counts: dict[str, int] = defaultdict(int)
    records: list[SeriesRecord] = []

    for label_path in sorted(data_dir.iterdir()):
        if not label_path.is_dir() or label_path.name.startswith("."):
            continue
        try:
            ground_truth = parse_body_part_label(label_path.name)
        except ValueError as exc:
            logger.warning("Skipping label dir %s: %s", label_path.name, exc)
            continue

        label_name = ground_truth.label_dir
        for series_path in iter_series_directories(label_path):
            if per_class is not None and label_counts[label_name] >= per_class:
                break
            records.append(
                SeriesRecord(
                    series_path=series_path,
                    label_dir=label_name,
                    body_part_gt=ground_truth.body_part,
                    iv_contrast_gt=ground_truth.iv_contrast,
                )
            )
            label_counts[label_name] += 1

    return sorted(records, key=lambda record: (record.label_dir, str(record.series_path)))


def _tseg_body_part_pred(tseg) -> str:
    if tseg is None:
        return ""
    return (tseg.dominant_region or "").strip()


def _tseg_contrast_pred(tseg) -> bool | None:
    if tseg is None or tseg.error:
        return None
    if not tseg.contrast_phase:
        return None
    return bool(tseg.iv_contrast)


def _gt_in_body_parts_present(body_part_gt: str, body_parts_present: str) -> bool:
    """True when GT region appears in segmented regions (incl. multi-region e.g. Chest+Head)."""
    if not body_parts_present.strip():
        return False
    present = {part.strip() for part in body_parts_present.split("+") if part.strip()}
    return body_part_gt in present


def geometry_fields(geometry: SeriesGeometryResult) -> dict[str, object]:
    """Flatten ``SeriesGeometryResult`` for CSV/JSON eval rows."""
    return {
        "geometry_plane": geometry.plane,
        "geometry_plane_confidence": round(geometry.plane_confidence, 4),
        "geometry_dimensionality": geometry.dimensionality,
        "geometry_provenance": geometry.provenance,
        "geometry_n_slices": geometry.n_slices,
        "geometry_ts_suitable": geometry.ts_suitable,
        "geometry_metadata_suspect": geometry.metadata_suspect,
        "geometry_method": geometry.method,
    }


def empty_geometry_fields() -> dict[str, object]:
    return {column: "" for column in GEOMETRY_COLUMNS}


def geometry_fields_for_series(series_path: Path) -> dict[str, object]:
    try:
        return geometry_fields(resolve_series_geometry(series_path))
    except Exception as exc:
        logger.warning("Geometry analysis failed for %s: %s", series_path, exc)
        return empty_geometry_fields()


def evaluate_record(
    record: SeriesRecord,
    tseg: TS_result,
    *,
    series_index: int,
    elapsed_sec: float,
    geometry: SeriesGeometryResult | None = None,
) -> dict:
    geo_row = geometry_fields(geometry) if geometry is not None else geometry_fields_for_series(record.series_path)
    body_part_pred = _tseg_body_part_pred(tseg)
    body_parts_present = (tseg.body_parts_present or "") if tseg else ""
    iv_pred = _tseg_contrast_pred(tseg)

    body_dominant_match = body_part_pred == record.body_part_gt if body_part_pred else False
    # Success when GT anatomy is among segmented regions (multi-region FOV counts as correct).
    body_correct = _gt_in_body_parts_present(record.body_part_gt, body_parts_present)

    if iv_pred is None:
        contrast_correct = ""
    else:
        contrast_correct = iv_pred == record.iv_contrast_gt

    error = tseg.error or ""
    status = "ok" if not error and body_parts_present.strip() else "fail"

    return {
        "series_index": series_index,
        "series_uid": record.series_path.name,
        "series_path": str(record.series_path),
        "label_dir": record.label_dir,
        "body_part_gt": record.body_part_gt,
        "iv_contrast_gt": record.iv_contrast_gt,
        "body_part_pred": body_part_pred,
        "body_parts_present": body_parts_present,
        "multi_region": tseg.multi_region,
        "region_fraction": round(tseg.region_fraction, 4),
        "body_part_correct": body_correct,
        "body_part_dominant_match": body_dominant_match,
        "iv_contrast_pred": iv_pred if iv_pred is not None else "",
        "contrast_phase": tseg.contrast_phase,
        "phase_probability": round(tseg.phase_probability, 4) if tseg.contrast_phase else "",
        "iv_contrast_correct": contrast_correct,
        **geo_row,
        "error": error,
        "elapsed_sec": round(elapsed_sec, 1),
        "status": status,
    }


def _accuracy(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _fmt_acc(values: list[bool]) -> str:
    if not values:
        return "n/a"
    correct = sum(values)
    pct = 100.0 * correct / len(values)
    return f"{pct:.1f}% ({correct}/{len(values)})"


def _fmt_rate(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    pct = 100.0 * numerator / denominator
    return f"{pct:.1f}% ({numerator}/{denominator})"


def _coerce_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _row_ts_suitable(row: dict) -> bool | None:
    return _coerce_bool(row.get("geometry_ts_suitable"))


def geometry_group_stats(rows: list[dict], group_field: str) -> dict[str, dict]:
    """Per-group counts, fail rates, and accuracy for all eval rows."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = row.get(group_field)
        if key not in (None, ""):
            grouped[str(key)].append(row)

    stats: dict[str, dict] = {}
    for key, subset in sorted(grouped.items()):
        ok = [row for row in subset if row["status"] == "ok"]
        failed = [row for row in subset if row["status"] != "ok"]
        ts_suitable = [row for row in subset if _row_ts_suitable(row) is True]
        ts_not_suitable = [row for row in subset if _row_ts_suitable(row) is False]
        contrast_ok = [row for row in ok if row["iv_contrast_correct"] != ""]
        stats[key] = {
            "n": len(subset),
            "n_ok": len(ok),
            "n_failed": len(failed),
            "fail_rate": len(failed) / len(subset) if subset else None,
            "n_ts_suitable": len(ts_suitable),
            "n_ts_not_suitable": len(ts_not_suitable),
            "body_part_accuracy": _accuracy([bool(row["body_part_correct"]) for row in ok]),
            "body_part_dominant_accuracy": _accuracy(
                [bool(row["body_part_dominant_match"]) for row in ok]
            ),
            "iv_contrast_accuracy": _accuracy([bool(row["iv_contrast_correct"]) for row in contrast_ok])
            if contrast_ok
            else None,
        }
    return stats


def build_geometry_routing_summary(rows: list[dict]) -> dict[str, dict]:
    """Compare pipeline outcomes for TS-eligible vs ineligible series."""
    suitable = [row for row in rows if _row_ts_suitable(row) is True]
    not_suitable = [row for row in rows if _row_ts_suitable(row) is False]
    unknown = [row for row in rows if _row_ts_suitable(row) is None]

    def _bucket(subset: list[dict]) -> dict:
        ok = [row for row in subset if row["status"] == "ok"]
        failed = [row for row in subset if row["status"] != "ok"]
        contrast_ok = [row for row in ok if row["iv_contrast_correct"] != ""]
        return {
            "n": len(subset),
            "n_ok": len(ok),
            "n_failed": len(failed),
            "fail_rate": len(failed) / len(subset) if subset else None,
            "body_part_accuracy": _accuracy([bool(row["body_part_correct"]) for row in ok]),
            "body_part_dominant_accuracy": _accuracy(
                [bool(row["body_part_dominant_match"]) for row in ok]
            ),
            "iv_contrast_accuracy": _accuracy([bool(row["iv_contrast_correct"]) for row in contrast_ok])
            if contrast_ok
            else None,
        }

    return {
        "ts_suitable": _bucket(suitable),
        "ts_not_suitable": _bucket(not_suitable),
        "ts_unknown": _bucket(unknown),
    }


def print_geometry_impact_report(rows: list[dict]) -> None:
    """Print fail rates and accuracy split by plane, dimensionality, and TS eligibility."""
    routing = build_geometry_routing_summary(rows)
    print("\n=== Geometry routing impact ===")
    for label, key in (
        ("TS eligible", "ts_suitable"),
        ("TS ineligible (expected skip)", "ts_not_suitable"),
        ("TS eligibility unknown", "ts_unknown"),
    ):
        bucket = routing[key]
        if bucket["n"] == 0:
            continue
        present = (
            f"{100.0 * bucket['body_part_accuracy']:.1f}%"
            if bucket["body_part_accuracy"] is not None
            else "n/a"
        )
        print(
            f"  {label:<32} n={bucket['n']:>3}  ok={bucket['n_ok']:>3}  "
            f"failed={bucket['n_failed']:>3}  fail={_fmt_rate(bucket['n_failed'], bucket['n'])}  "
            f"present={present}"
        )

    for field, title in (
        ("geometry_plane", "By acquisition plane"),
        ("geometry_dimensionality", "By dimensionality"),
    ):
        stats = geometry_group_stats(rows, field)
        if not stats:
            continue
        print(f"\n{title} (all series; fail = TS skip or pipeline error):")
        for key, bucket in stats.items():
            present = (
                f"{100.0 * bucket['body_part_accuracy']:.1f}%"
                if bucket["body_part_accuracy"] is not None
                else "n/a"
            )
            fail = (
                f"{100.0 * bucket['fail_rate']:.1f}%"
                if bucket["fail_rate"] is not None
                else "n/a"
            )
            print(
                f"  {key:<20} n={bucket['n']:>3}  ok={bucket['n_ok']:>3}  "
                f"failed={bucket['n_failed']:>3} ({fail})  "
                f"ts_ok={bucket['n_ts_suitable']:>3} ts_skip={bucket['n_ts_not_suitable']:>3}  "
                f"present={present}"
            )


def _contrast_label(value) -> str:
    if value is True:
        return "WITH"
    if value is False:
        return "WITHOUT"
    return "?"


def _pass_fail(ok: bool) -> str:
    return "ok" if ok else "FAIL"


def _short_uid(uid: str, *, max_len: int = 28) -> str:
    if len(uid) <= max_len:
        return uid
    return f"...{uid[-(max_len - 3) :]}"


def _body_part_label(value: str) -> str:
    label = (value or "").strip()
    return label if label in BODY_PARTS else BODY_PART_NONE


def build_confusion_matrix(
    y_true: list[str],
    y_pred: list[str],
    labels: tuple[str, ...],
    *,
    unknown_pred: str | None = None,
) -> list[list[int]]:
    index = {label: idx for idx, label in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for truth, pred in zip(y_true, y_pred, strict=True):
        if truth not in index:
            continue
        pred_label = pred if pred in index else unknown_pred
        if pred_label is None or pred_label not in index:
            continue
        matrix[index[truth]][index[pred_label]] += 1
    return matrix


def format_confusion_matrix(matrix: list[list[int]], labels: tuple[str, ...]) -> str:
    col_width = max(len(label) for label in labels) + 2
    header = " " * col_width + "".join(f"{label:>{col_width}}" for label in labels)
    lines = [header]
    for idx, label in enumerate(labels):
        counts = "".join(f"{matrix[idx][col]:>{col_width}}" for col in range(len(labels)))
        lines.append(f"{label:>{col_width}}{counts}")
    return "\n".join(lines)


def confusion_matrix_dict(matrix: list[list[int]], labels: tuple[str, ...]) -> dict:
    return {
        "labels": list(labels),
        "matrix": matrix,
        "rows_are_true": True,
        "cols_are_pred": True,
    }


def body_part_confusion_rows(rows: list[dict]) -> tuple[list[str], list[str]]:
    """Ground truth vs dominant_region for successful series."""
    ok = [row for row in rows if row["status"] == "ok"]
    y_true = [row["body_part_gt"] for row in ok]
    y_pred = [_body_part_label(row["body_part_pred"]) for row in ok]
    return y_true, y_pred


def contrast_confusion_rows(rows: list[dict]) -> tuple[list[str], list[str]]:
    ok = [
        row
        for row in rows
        if row["status"] == "ok" and row["iv_contrast_correct"] != "" and row["iv_contrast_pred"] != ""
    ]
    y_true = [_contrast_label(row["iv_contrast_gt"]) for row in ok]
    y_pred = [_contrast_label(row["iv_contrast_pred"]) for row in ok]
    return y_true, y_pred


def print_confusion_matrices(rows: list[dict]) -> None:
    body_labels = BODY_PARTS + (BODY_PART_NONE,)
    y_true_body, y_pred_body = body_part_confusion_rows(rows)
    if y_true_body:
        body_matrix = build_confusion_matrix(
            y_true_body, y_pred_body, body_labels, unknown_pred=BODY_PART_NONE
        )
        print("\nBody part confusion (rows=true, cols=pred; pred = dominant_region):")
        for line in format_confusion_matrix(body_matrix, body_labels).splitlines():
            print(f"  {line}")

    y_true_iv, y_pred_iv = contrast_confusion_rows(rows)
    if y_true_iv:
        contrast_matrix = build_confusion_matrix(y_true_iv, y_pred_iv, CONTRAST_LABELS)
        print("\nIV contrast confusion (rows=true, cols=pred):")
        for line in format_confusion_matrix(contrast_matrix, CONTRAST_LABELS).splitlines():
            print(f"  {line}")


def print_series_table(rows: list[dict]) -> None:
    """Print one line per series with ground truth, predictions, and pass/fail."""
    print("\n--- Per-series results ---")
    header = (
        f"{'#':>3}  {'label_dir':<14} {'plane':<8} {'series_uid':<28} "
        f"{'GT body':<8} {'GT IV':<7} {'segmented':<16} {'dominant':<8} "
        f"{'IV pred':<7} {'phase':<12} {'body':<5} {'dom':<5} {'IV':<5}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        if row["status"] != "ok":
            print(
                f"{row['series_index']:>3}  {row['label_dir']:<14} "
                f"{row.get('geometry_plane', ''):<8} "
                f"{_short_uid(row['series_uid'], max_len=28):<28} ERROR: {row['error']}"
            )
            continue
        iv_ok = row["iv_contrast_correct"] if row["iv_contrast_correct"] != "" else True
        phase = row["contrast_phase"] or "-"
        if len(phase) > 12:
            phase = phase[:11] + "…"
        plane = str(row.get("geometry_plane") or "-")
        print(
            f"{row['series_index']:>3}  {row['label_dir']:<14} "
            f"{plane:<8} "
            f"{_short_uid(row['series_uid'], max_len=28):<28} "
            f"{row['body_part_gt']:<8} {_contrast_label(row['iv_contrast_gt']):<7} "
            f"{row['body_parts_present']:<16} {row['body_part_pred']:<8} "
            f"{_contrast_label(row['iv_contrast_pred']):<7} {phase:<12} "
            f"{_pass_fail(bool(row['body_part_correct'])):<5} "
            f"{_pass_fail(bool(row['body_part_dominant_match'])):<5} "
            f"{_pass_fail(bool(iv_ok)):<5}"
        )
    print(
        "\nColumns: body = GT found in body_parts_present; "
        "dom = dominant_region equals GT body part; IV = iv_contrast match."
    )


def print_summary(rows: list[dict]) -> None:
    ok = [row for row in rows if row["status"] == "ok"]
    failed = [row for row in rows if row["status"] != "ok"]
    body_correct = [bool(row["body_part_correct"]) for row in ok]
    body_dominant = [bool(row["body_part_dominant_match"]) for row in ok]
    contrast_rows = [row for row in ok if row["iv_contrast_correct"] != ""]
    contrast_correct = [bool(row["iv_contrast_correct"]) for row in contrast_rows]

    print("\n=== tseg eval summary ===")
    print(f"Series run: {len(rows)}  ok: {len(ok)}  failed: {len(failed)}")

    print("\nBody part metrics:")
    print(
        "  present   — GT anatomy appears in body_parts_present "
        "(multi-region FOV counts, e.g. Chest+Head for a chest series)"
    )
    if body_correct:
        print(f"            {_fmt_acc(body_correct)}")
    print(
        "  dominant  — dominant_region (largest voxel mass) equals GT body part exactly"
    )
    if body_dominant:
        print(f"            {_fmt_acc(body_dominant)}")

    print("\nIV contrast:")
    if contrast_correct:
        print(f"            {_fmt_acc(contrast_correct)}")

    print("\nBy label directory:")
    for label_dir in sorted({row["label_dir"] for row in ok}):
        subset = [row for row in ok if row["label_dir"] == label_dir]
        present = _fmt_acc([bool(row["body_part_correct"]) for row in subset])
        dominant = _fmt_acc([bool(row["body_part_dominant_match"]) for row in subset])
        c_sub = [row for row in subset if row["iv_contrast_correct"] != ""]
        contrast = _fmt_acc([bool(row["iv_contrast_correct"]) for row in c_sub]) if c_sub else "n/a"
        print(
            f"  {label_dir:<16} n={len(subset):>2}  "
            f"present={present}  dominant={dominant}  IV={contrast}"
        )

    print("\nBy body part (aggregated):")
    for body_part in BODY_PARTS:
        subset = [row for row in ok if row["body_part_gt"] == body_part]
        if not subset:
            continue
        present = _fmt_acc([bool(row["body_part_correct"]) for row in subset])
        c_sub = [row for row in subset if row["iv_contrast_correct"] != ""]
        contrast = _fmt_acc([bool(row["iv_contrast_correct"]) for row in c_sub]) if c_sub else "n/a"
        print(f"  {body_part:<8} n={len(subset):>2}  present={present}  IV={contrast}")

    print_geometry_impact_report(rows)

    print_confusion_matrices(rows)
    print_series_table(rows)


def write_results_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(RESULT_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def write_summary_json(path: Path, rows: list[dict]) -> None:
    ok = [row for row in rows if row["status"] == "ok"]
    contrast_ok = [row for row in ok if row["iv_contrast_correct"] != ""]
    body_labels = BODY_PARTS + (BODY_PART_NONE,)
    y_true_body, y_pred_body = body_part_confusion_rows(rows)
    y_true_iv, y_pred_iv = contrast_confusion_rows(rows)
    summary = {
        "n_total": len(rows),
        "n_ok": len(ok),
        "body_part_accuracy": _accuracy([bool(r["body_part_correct"]) for r in ok]),
        "body_part_dominant_accuracy": _accuracy([bool(r["body_part_dominant_match"]) for r in ok]),
        "iv_contrast_accuracy": _accuracy([bool(r["iv_contrast_correct"]) for r in contrast_ok]),
        "confusion_matrices": {},
        "by_body_part": {},
        "by_label_dir": {},
        "by_geometry_plane": {},
        "by_geometry_dimensionality": {},
        "by_geometry_provenance": {},
        "geometry_routing": build_geometry_routing_summary(rows),
        "geometry_impact_by_plane": geometry_group_stats(rows, "geometry_plane"),
        "geometry_impact_by_dimensionality": geometry_group_stats(rows, "geometry_dimensionality"),
    }
    if y_true_body:
        body_matrix = build_confusion_matrix(
            y_true_body, y_pred_body, body_labels, unknown_pred=BODY_PART_NONE
        )
        summary["confusion_matrices"]["body_part_dominant"] = confusion_matrix_dict(body_matrix, body_labels)
    if y_true_iv:
        contrast_matrix = build_confusion_matrix(y_true_iv, y_pred_iv, CONTRAST_LABELS)
        summary["confusion_matrices"]["iv_contrast"] = confusion_matrix_dict(
            contrast_matrix, CONTRAST_LABELS
        )
    for body_part in BODY_PARTS:
        subset = [r for r in ok if r["body_part_gt"] == body_part]
        if subset:
            c_sub = [r for r in subset if r["iv_contrast_correct"] != ""]
            summary["by_body_part"][body_part] = {
                "n": len(subset),
                "body_part_accuracy": _accuracy([bool(r["body_part_correct"]) for r in subset]),
                "iv_contrast_accuracy": _accuracy([bool(r["iv_contrast_correct"]) for r in c_sub]),
            }
    by_label: dict[str, list] = defaultdict(list)
    for row in ok:
        by_label[row["label_dir"]].append(row)
    for label_dir, subset in sorted(by_label.items()):
        c_sub = [r for r in subset if r["iv_contrast_correct"] != ""]
        summary["by_label_dir"][label_dir] = {
            "n": len(subset),
            "body_part_accuracy": _accuracy([bool(r["body_part_correct"]) for r in subset]),
            "iv_contrast_accuracy": _accuracy([bool(r["iv_contrast_correct"]) for r in c_sub]),
        }
    for field, summary_key in (
        ("geometry_plane", "by_geometry_plane"),
        ("geometry_dimensionality", "by_geometry_dimensionality"),
        ("geometry_provenance", "by_geometry_provenance"),
    ):
        grouped: dict[str, list] = defaultdict(list)
        for row in ok:
            value = row.get(field)
            if value:
                grouped[str(value)].append(row)
        for value, subset in sorted(grouped.items()):
            c_sub = [r for r in subset if r["iv_contrast_correct"] != ""]
            summary[summary_key][value] = {
                "n": len(subset),
                "body_part_accuracy": _accuracy([bool(r["body_part_correct"]) for r in subset]),
                "body_part_dominant_accuracy": _accuracy(
                    [bool(r["body_part_dominant_match"]) for r in subset]
                ),
                "iv_contrast_accuracy": _accuracy([bool(r["iv_contrast_correct"]) for r in c_sub]),
            }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def run_eval(
    data_dir: Path,
    output_dir: Path,
    *,
    per_class: int | None = None,
) -> Path:
    records = discover_series(data_dir, per_class=per_class)
    if not records:
        raise ValueError(f"No labeled series found under {data_dir}")

    logger.info(
        "Discovered %d series under %s (per_class=%s)",
        len(records),
        data_dir,
        per_class if per_class is not None else "all",
    )

    rows: list[dict] = []
    run_started = time.perf_counter()

    for index, record in enumerate(records, start=1):
        logger.info(
            "[%d/%d] %s / %s (gt=%s %s)",
            index,
            len(records),
            record.label_dir,
            record.series_path.name,
            record.body_part_gt,
            _contrast_label(record.iv_contrast_gt),
        )
        series_started = time.perf_counter()
        try:
            geometry = resolve_series_geometry(record.series_path)
        except Exception as exc:
            logger.warning("Geometry analysis failed for %s: %s", record.series_path, exc)
            geometry = None
        geo_row = geometry_fields(geometry) if geometry is not None else empty_geometry_fields()
        try:
            tseg_results = analyze_series([record.series_path])
            tseg = tseg_results[0] if tseg_results else None
            if tseg is None:
                raise RuntimeError("analyze_series returned no result")
            row = evaluate_record(
                record,
                tseg,
                series_index=index,
                elapsed_sec=time.perf_counter() - series_started,
                geometry=geometry,
            )
        except Exception as exc:
            logger.exception("Failed on %s: %s", record.series_path, exc)
            row = {
                "series_index": index,
                "series_uid": record.series_path.name,
                "series_path": str(record.series_path),
                "label_dir": record.label_dir,
                "body_part_gt": record.body_part_gt,
                "iv_contrast_gt": record.iv_contrast_gt,
                "body_part_pred": "",
                "body_parts_present": "",
                "multi_region": False,
                "region_fraction": "",
                "body_part_correct": False,
                "body_part_dominant_match": False,
                "iv_contrast_pred": "",
                "contrast_phase": "",
                "phase_probability": "",
                "iv_contrast_correct": "",
                **geo_row,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_sec": round(time.perf_counter() - series_started, 1),
                "status": "fail",
            }
        rows.append(row)
        logger.info(
            "  [%d/%d] label=%s segmented=%r dominant=%r present_ok=%s dominant_ok=%s IV_ok=%s (%.1fs)",
            index,
            len(records),
            record.label_dir,
            row["body_parts_present"],
            row["body_part_pred"],
            row["body_part_correct"],
            row["body_part_dominant_match"],
            row["iv_contrast_correct"],
            row["elapsed_sec"],
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "ct_eval_results.csv"
    write_results_csv(csv_path, rows)
    write_summary_json(output_dir / "ct_eval_summary.json", rows)

    print_summary(rows)
    print(f"\nWrote {csv_path}")
    print(f"Total elapsed: {time.perf_counter() - run_started:.1f}s")
    return csv_path


def build_parser() -> argparse.ArgumentParser:
    epilog = """
Geometry CSV columns (also in --help via module docstring):
  geometry_plane, geometry_plane_confidence, geometry_dimensionality,
  geometry_provenance, geometry_n_slices, geometry_ts_suitable,
  geometry_metadata_suspect, geometry_method

JSON summary adds geometry_routing, geometry_impact_by_plane,
geometry_impact_by_dimensionality, and by_geometry_* breakdowns.

See src/prototyping/ct/ct_eval_cli.html for full HTML reference.
"""
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate tseg body part + IV contrast via analyze_series on labeled CT data. "
            "Resolves DICOM geometry per series and reports TS routing impact."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Labeled CT root (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/ct_eval"),
        help="Directory for CSV and JSON summary (default: artifacts/ct_eval)",
    )
    parser.add_argument(
        "--per-class",
        type=int,
        default=None,
        metavar="N",
        help="Max series per label subdirectory (HEAD_WITH, CHEST_WITHOUT, …); default all",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        run_eval(args.data_dir, args.output_dir, per_class=args.per_class)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
