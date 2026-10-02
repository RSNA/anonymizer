"""Unit coverage for mcp.ops pure helpers (no GPU / AWS)."""

from __future__ import annotations

import pytest

from anonymizer.mcp.ops import HeadlessOpsError, _filter_series_rows, _pick_index, _reject_relative_selector


def test_reject_relative_selector() -> None:
    _reject_relative_selector("series", "1")
    with pytest.raises(HeadlessOpsError):
        _reject_relative_selector("series", "last")
    with pytest.raises(HeadlessOpsError):
        _reject_relative_selector("patient", "first")


def test_pick_index() -> None:
    assert _pick_index(["a", "b", "c"], "2", label="study") == "b"
    with pytest.raises(HeadlessOpsError):
        _pick_index([], "1", label="study")
    with pytest.raises(HeadlessOpsError):
        _pick_index(["a"], "x", label="study")
    with pytest.raises(HeadlessOpsError):
        _pick_index(["a"], "9", label="study")


def test_filter_series_rows_selectors() -> None:
    rows = [
        {"modality": "CR", "series_description": "Chest AP", "pixel_phi_scanned": False},
        {"modality": "CT", "series_description": "Chest W", "pixel_phi_scanned": True},
        {"modality": "DX", "series_description": "Abdomen", "pixel_phi_scanned": False},
    ]
    assert _filter_series_rows(rows, series_selector="") == rows
    assert len(_filter_series_rows(rows, series_selector="unscanned")) == 2
    assert all(r["modality"] in {"CR", "DX"} for r in _filter_series_rows(rows, series_selector="cxr"))
    assert len(_filter_series_rows(rows, series_selector="CT")) == 1
    assert len(_filter_series_rows(rows, series_selector="Chest")) >= 1
    with pytest.raises(HeadlessOpsError):
        _filter_series_rows(rows, series_selector="zzz_no_match_xyz")
