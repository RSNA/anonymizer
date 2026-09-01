#!/usr/bin/env python3
"""
Manual smoke test for Harmonize cooperative cancellation.

Not collected by pytest (lives under src/prototyping/, outside testpaths).

Run:
    uv run python src/prototyping/harmonize_cancel_smoke.py
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

from anonymizer.controller.ai.harmonize import harmonize_series
from anonymizer.controller.ai.tseg.dicom_geometry import SeriesGeometryResult
from anonymizer.controller.ai.tseg.segment import (
    HARMONIZE_CANCELLED_MESSAGE,
    TS_result,
    analyze_tseg_regions,
    harmonize_cancel_requested,
)


def _geometry() -> SeriesGeometryResult:
    return SeriesGeometryResult(
        plane="sagittal",
        plane_confidence=0.95,
        slice_normal_lps=(1.0, 0.0, 0.0),
        plane_angles_deg={"axial": 85.0, "coronal": 85.0, "sagittal": 5.0},
        dimensionality="volume_3d",
        n_slices=24,
        through_plane_extent_mm=120.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "SAGITTAL"),
        source_series_uids=(),
        ts_suitable=True,
        metadata_suspect=False,
        method="dicom_headers",
        notes="",
    )


def _region_result(series_dir: Path) -> TS_result:
    return TS_result(
        series_directory=series_dir,
        dominant_region="Head",
        body_parts_present="Head",
        multi_region=False,
        region_fraction=1.0,
        iv_contrast=False,
        contrast_phase="",
        phase_probability=0.0,
        structures_present={"brain": 50_000},
    )


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_cancel_requested_helper() -> None:
    flag = {"value": False}
    _assert(not harmonize_cancel_requested(None), "None callback is not cancelled")
    _assert(not harmonize_cancel_requested(lambda: flag["value"]), "initially not cancelled")
    flag["value"] = True
    _assert(harmonize_cancel_requested(lambda: flag["value"]), "flag reflects cancel")


def test_analyze_tseg_regions_returns_cancelled_before_start(work_dir: Path) -> None:
    series = work_dir / "series"
    series.mkdir(parents=True, exist_ok=True)
    result, nifti = analyze_tseg_regions(series, geometry=_geometry(), cancelled=lambda: True)
    _assert(result.error == HARMONIZE_CANCELLED_MESSAGE, "cancelled TS regions error")
    _assert(nifti is None, "no NIfTI on immediate cancel")


def test_harmonize_series_stops_before_contrast(work_dir: Path) -> None:
    series = work_dir / "chest"
    series.mkdir(parents=True, exist_ok=True)
    cancel = threading.Event()

    def slow_regions(*_args, **_kwargs):
        time.sleep(0.05)
        cancel.set()
        time.sleep(0.05)
        return (_region_result(series), series / "vol.nii.gz")

    with (
        patch("anonymizer.controller.ai.harmonize.pipeline.resolve_series_geometry", return_value=_geometry()),
        patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions", side_effect=slow_regions),
        patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast") as mock_contrast,
        patch("anonymizer.controller.ai.harmonize.pipeline._merge_result") as mock_merge,
        patch("anonymizer.controller.ai.tseg.seg_retention.evict_tseg_volume") as mock_evict,
    ):
        results = harmonize_series([series], cancelled=cancel.is_set)

    _assert(results == [], "cancelled harmonize returns no merged results")
    mock_contrast.assert_not_called()
    mock_merge.assert_not_called()
    mock_evict.assert_not_called()


def test_harmonize_series_cancel_before_ts(work_dir: Path) -> None:
    series = work_dir / "mr"
    series.mkdir(parents=True, exist_ok=True)

    with (
        patch("anonymizer.controller.ai.harmonize.pipeline.resolve_series_geometry", return_value=_geometry()),
        patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions") as mock_regions,
    ):
        results = harmonize_series([series], cancelled=lambda: True)

    _assert(results == [], "immediate cancel yields empty results")
    mock_regions.assert_not_called()


def test_work_state_finish_on_cancel_pattern() -> None:
    """Mirror HarmonizeResultsView worker: cancelled jobs must still mark WorkState done."""
    from anonymizer.controller.work_state import WorkState

    work_state = WorkState()
    work_state.prepare_job()
    work_state.request_cancel()
    work_state.finish(None)
    _assert(work_state.done, "cancelled worker marks WorkState done")
    _assert(work_state.result is None, "cancelled worker stores no harmonize results")


def main() -> None:
    tmp = Path("/tmp/anonymizer_harmonize_cancel_smoke")
    tmp.mkdir(parents=True, exist_ok=True)

    tests = [
        ("cancel_requested_helper", lambda: test_cancel_requested_helper()),
        ("analyze_tseg_regions_immediate_cancel", lambda: test_analyze_tseg_regions_returns_cancelled_before_start(tmp / "a")),
        ("harmonize_series_stop_before_contrast", lambda: test_harmonize_series_stops_before_contrast(tmp / "b")),
        ("harmonize_series_cancel_before_ts", lambda: test_harmonize_series_cancel_before_ts(tmp / "c")),
        ("work_state_finish_on_cancel", lambda: test_work_state_finish_on_cancel_pattern()),
    ]

    passed = 0
    for name, run in tests:
        try:
            run()
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
            raise SystemExit(1) from exc
        print(f"PASS {name}")
        passed += 1

    print(f"\nAll {passed} harmonize cancel smoke checks passed.")


if __name__ == "__main__":
    main()
