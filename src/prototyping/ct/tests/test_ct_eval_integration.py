"""Slow integration smoke tests for ct_eval (requires TotalSegmentator extra)."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from prototyping.ct.ct_eval import GEOMETRY_COLUMNS, run_eval
from tests.controller.tseg.support.synthetic_ct import build_synthetic_chest_ct_series, list_dcm_files

pytestmark = [pytest.mark.prototyping, pytest.mark.tseg_integration]

totalsegmentator = pytest.importorskip("totalsegmentator")


def _layout_labeled_series(
    data_root: Path,
    label_dir: str,
    series_dicom_dir: Path,
    *,
    study_uid: str = "1.2.840.113619.2.55.3.604688119.802.1713781234567890",
    series_uid: str = "1.2.840.113619.2.55.3.604688119.802.1713781234567891",
) -> Path:
    """Build ct_eval layout: ``data_root/<label>/<study>/<series>/*.dcm``."""
    dest = data_root / label_dir / study_uid / series_uid
    dest.mkdir(parents=True)
    for path in list_dcm_files(series_dicom_dir):
        shutil.copy(path, dest / path.name)
    return data_root


def test_run_eval_smoke_includes_geometry_columns_for_axial_chest(
    tmp_path: Path,
) -> None:
    phantom_dir = build_synthetic_chest_ct_series(tmp_path / "phantom")
    data_dir = _layout_labeled_series(tmp_path / "data", "CHEST_WITHOUT", phantom_dir)
    output_dir = tmp_path / "artifacts"

    csv_path = run_eval(data_dir, output_dir, per_class=1)
    summary_path = output_dir / "ct_eval_summary.json"

    assert csv_path.is_file()
    assert summary_path.is_file()

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    row = rows[0]
    for column in GEOMETRY_COLUMNS:
        assert column in row
        assert row[column] != ""

    assert row["geometry_plane"] == "axial"
    assert row["geometry_dimensionality"] == "volume_3d"
    assert row["geometry_provenance"] == "original"
    assert row["geometry_ts_suitable"] == "True"
    assert int(row["geometry_n_slices"]) >= 11

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["n_total"] == 1
    assert "by_geometry_plane" in summary
    assert "axial" in summary["by_geometry_plane"]
    assert summary["by_geometry_plane"]["axial"]["n"] == 1
    assert summary["geometry_routing"]["ts_suitable"]["n"] == 1
    assert summary["geometry_routing"]["ts_suitable"]["fail_rate"] == 0.0
    assert summary["geometry_impact_by_plane"]["axial"]["fail_rate"] == 0.0
