"""Unit tests for ct_eval geometry routing and impact reports (step 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonymizer.controller.tseg.dicom_geometry import resolve_series_geometry
from prototyping.ct.ct_eval import (
    build_geometry_routing_summary,
    geometry_fields,
    geometry_group_stats,
    print_geometry_impact_report,
    write_summary_json,
)
from tests.controller.tseg.support.synthetic_ct import (
    build_synthetic_chest_ct_series,
    build_synthetic_scout_ct_series,
)


pytestmark = pytest.mark.prototyping


def _row(
    *,
    status: str = "ok",
    plane: str = "axial",
    dimensionality: str = "volume_3d",
    provenance: str = "original",
    ts_suitable: bool | str = True,
    body_part_correct: bool = True,
    body_part_dominant_match: bool = True,
    iv_contrast_correct: bool | str = True,
    body_part_gt: str = "Chest",
    body_part_pred: str = "Chest",
    label_dir: str = "CHEST_WITH",
) -> dict:
    return {
        "status": status,
        "label_dir": label_dir,
        "body_part_gt": body_part_gt,
        "body_part_pred": body_part_pred,
        "geometry_plane": plane,
        "geometry_dimensionality": dimensionality,
        "geometry_provenance": provenance,
        "geometry_ts_suitable": ts_suitable,
        "body_part_correct": body_part_correct,
        "body_part_dominant_match": body_part_dominant_match,
        "iv_contrast_correct": iv_contrast_correct,
        "iv_contrast_pred": True if iv_contrast_correct not in ("", None) else "",
        "iv_contrast_gt": True,
    }


def test_geometry_group_stats_skips_blank_group_keys() -> None:
    rows = [
        _row(plane="axial"),
        {**_row(), "geometry_plane": ""},
        {**_row(), "geometry_plane": None},
    ]
    stats = geometry_group_stats(rows, "geometry_plane")
    assert list(stats) == ["axial"]
    assert stats["axial"]["n"] == 1


def test_geometry_group_stats_empty_rows() -> None:
    assert geometry_group_stats([], "geometry_plane") == {}


def test_geometry_group_stats_accuracy_and_iv_metrics() -> None:
    rows = [
        _row(body_part_correct=True, body_part_dominant_match=True, iv_contrast_correct=True),
        _row(body_part_correct=False, body_part_dominant_match=True, iv_contrast_correct=False),
        _row(status="fail", body_part_correct=False, iv_contrast_correct=""),
    ]
    stats = geometry_group_stats(rows, "geometry_plane")["axial"]
    assert stats["n"] == 3
    assert stats["n_ok"] == 2
    assert stats["body_part_accuracy"] == 0.5
    assert stats["body_part_dominant_accuracy"] == 1.0
    assert stats["iv_contrast_accuracy"] == 0.5


def test_geometry_group_stats_by_provenance() -> None:
    rows = [
        _row(provenance="original", ts_suitable=True),
        _row(provenance="derived_reformat", ts_suitable=False, status="fail"),
        _row(provenance="derived_3d_render", ts_suitable=False, status="fail"),
    ]
    stats = geometry_group_stats(rows, "geometry_provenance")
    assert stats["original"]["n_ok"] == 1
    assert stats["derived_3d_render"]["fail_rate"] == 1.0
    assert stats["derived_3d_render"]["n_ts_not_suitable"] == 1


@pytest.mark.parametrize(
    ("ts_suitable", "expected_bucket"),
    [
        (True, "ts_suitable"),
        (False, "ts_not_suitable"),
        ("True", "ts_suitable"),
        ("false", "ts_not_suitable"),
        ("", "ts_unknown"),
    ],
)
def test_routing_summary_coerces_csv_style_ts_suitable(
    ts_suitable: bool | str,
    expected_bucket: str,
) -> None:
    routing = build_geometry_routing_summary([_row(ts_suitable=ts_suitable)])
    assert routing[expected_bucket]["n"] == 1
    for key, bucket in routing.items():
        if key != expected_bucket:
            assert bucket["n"] == 0


def test_routing_summary_unknown_eligibility_bucket() -> None:
    rows = [
        {**_row(), "geometry_ts_suitable": ""},
        {**_row(), "geometry_ts_suitable": None},
    ]
    routing = build_geometry_routing_summary(rows)
    assert routing["ts_unknown"]["n"] == 2
    assert routing["ts_suitable"]["n"] == 0
    assert routing["ts_not_suitable"]["n"] == 0


def test_routing_summary_ts_eligible_can_still_fail() -> None:
    """Eligible geometry with a TS pipeline error should count as failed, not skipped."""
    rows = [_row(status="fail", ts_suitable=True, body_part_correct=False, iv_contrast_correct="")]
    routing = build_geometry_routing_summary(rows)
    assert routing["ts_suitable"]["n"] == 1
    assert routing["ts_suitable"]["n_failed"] == 1
    assert routing["ts_suitable"]["fail_rate"] == 1.0
    assert routing["ts_not_suitable"]["n"] == 0


def test_routing_summary_empty_rows() -> None:
    routing = build_geometry_routing_summary([])
    for bucket in routing.values():
        assert bucket["n"] == 0
        assert bucket["fail_rate"] is None
        assert bucket["body_part_accuracy"] is None


def test_write_summary_json_includes_geometry_impact(tmp_path: Path) -> None:
    rows = [
        _row(plane="axial", ts_suitable=True),
        _row(plane="oblique", ts_suitable=False, status="fail"),
    ]
    summary_path = tmp_path / "ct_eval_summary.json"
    write_summary_json(summary_path, rows)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["geometry_routing"]["ts_suitable"]["n"] == 1
    assert summary["geometry_routing"]["ts_not_suitable"]["n"] == 1
    assert summary["geometry_impact_by_plane"]["oblique"]["fail_rate"] == 1.0
    assert summary["geometry_impact_by_dimensionality"]["volume_3d"]["n"] == 2


def test_print_geometry_impact_report(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [
        _row(plane="axial", dimensionality="volume_3d"),
        _row(
            plane="oblique",
            dimensionality="localizer_2d",
            ts_suitable=False,
            status="fail",
        ),
    ]
    print_geometry_impact_report(rows)
    output = capsys.readouterr().out

    assert "Geometry routing impact" in output
    assert "TS eligible" in output
    assert "TS ineligible" in output
    assert "By acquisition plane" in output
    assert "By dimensionality" in output
    assert "oblique" in output
    assert "localizer_2d" in output
    assert "100.0%" in output


def test_geometry_impact_from_synthetic_axial_and_scout(tmp_path: Path) -> None:
    """Real header geometry: scout/localizer should show 100% fail vs axial volume."""
    chest_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    scout_dir = build_synthetic_scout_ct_series(tmp_path / "scout")

    rows = []
    for series_dir, gt_ok in ((chest_dir, True), (scout_dir, False)):
        geometry = resolve_series_geometry(series_dir)
        rows.append(
            {
                "status": "ok" if geometry.ts_suitable else "fail",
                "body_part_correct": gt_ok and geometry.ts_suitable,
                "body_part_dominant_match": gt_ok and geometry.ts_suitable,
                "iv_contrast_correct": "" if not geometry.ts_suitable else True,
                **geometry_fields(geometry),
            }
        )

    by_plane = geometry_group_stats(rows, "geometry_plane")
    by_dim = geometry_group_stats(rows, "geometry_dimensionality")
    routing = build_geometry_routing_summary(rows)

    # Both phantoms are axial IOP; dimensionality separates scout from volume.
    assert by_plane["axial"]["n"] == 2
    assert by_plane["axial"]["n_ts_suitable"] == 1
    assert by_plane["axial"]["n_ts_not_suitable"] == 1
    assert by_dim["volume_3d"]["fail_rate"] == 0.0
    assert by_dim["localizer_2d"]["fail_rate"] == 1.0
    assert by_dim["localizer_2d"]["n_ts_not_suitable"] == 1
    assert routing["ts_suitable"]["n_ok"] == 1
    assert routing["ts_not_suitable"]["n_failed"] == 1


def test_mixed_planes_show_different_fail_rates() -> None:
    rows = [
        _row(plane="axial", status="ok"),
        _row(plane="axial", status="ok"),
        _row(plane="axial", status="fail", ts_suitable=True, body_part_correct=False, iv_contrast_correct=""),
        _row(plane="sagittal", status="fail", ts_suitable=False, body_part_correct=False, iv_contrast_correct=""),
        _row(plane="coronal", status="fail", ts_suitable=False, body_part_correct=False, iv_contrast_correct=""),
    ]
    stats = geometry_group_stats(rows, "geometry_plane")
    assert stats["axial"]["fail_rate"] == pytest.approx(1 / 3)
    assert stats["sagittal"]["fail_rate"] == 1.0
    assert stats["coronal"]["fail_rate"] == 1.0
