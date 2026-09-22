"""Tests for project series analytics ledger."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from anonymizer.controller.analytics import (
    _collect_tseg_anatomy,
    _series_anatomy_contribution,
    rebuild_anatomy_ledger,
    upsert_series_ledger_from_cache,
)
from anonymizer.controller.analytics_ledger import (
    SeriesLedgerRow,
    ledger_exists,
    ledger_path_for_images_dir,
    read_ledger_rows,
    upsert_series_row,
    utc_now_iso,
)
from anonymizer.controller.ai.tseg.config import TSEG_CACHE_DIRNAME
from anonymizer.controller.ai.tseg.seg_retention import (
    finalize_seg_cache,
    write_primary_segment_voxels,
    write_structure_voxels,
)


def _project_series(tmp_path: Path, *, patient: str = "P1", study: str = "S1", series: str = "UID1") -> Path:
    images = tmp_path / "public"
    series_path = images / patient / study / series
    series_path.mkdir(parents=True)
    return series_path


def _write_brain_mask(seg_dir: Path, voxels: int = 2000) -> None:
    seg_dir.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((8, 32, 32), dtype=np.uint8)
    flat = arr.reshape(-1)
    flat[:voxels] = 1
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((1.0, 1.0, 1.0))
    sitk.WriteImage(img, str(seg_dir / "brain.nii.gz"))


def test_ledger_upsert_idempotent(tmp_path: Path) -> None:
    images = tmp_path / "public"
    images.mkdir()
    row = SeriesLedgerRow(
        anon_series_uid="UID1",
        anon_patient_id="P1",
        modality="CT",
        head_limited=True,
        regions=("Head",),
        organs_ml={"brain": 12.5},
        updated_at=utc_now_iso(),
    )
    upsert_series_row(images, row)
    upsert_series_row(images, row)
    rows = read_ledger_rows(images)
    assert list(rows) == ["UID1"]
    assert rows["UID1"].organs_ml["brain"] == pytest.approx(12.5)

    updated = SeriesLedgerRow(
        anon_series_uid="UID1",
        anon_patient_id="P1",
        modality="CT",
        head_limited=True,
        regions=("Head",),
        organs_ml={"brain": 99.0},
        updated_at=utc_now_iso(),
    )
    upsert_series_row(images, updated)
    rows = read_ledger_rows(images)
    assert rows["UID1"].organs_ml["brain"] == pytest.approx(99.0)


def test_collect_prefers_ledger_without_series_walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    images = tmp_path / "public"
    images.mkdir()
    upsert_series_row(
        images,
        SeriesLedgerRow(
            anon_series_uid="UID1",
            anon_patient_id="P1",
            modality="CT",
            head_limited=True,
            regions=("Head",),
            organs_ml={"brain": 42.0},
            updated_at=utc_now_iso(),
        ),
    )
    assert ledger_exists(images)

    def _boom(_images_dir: Path) -> list[Path]:
        raise AssertionError("must not walk images when ledger exists")

    monkeypatch.setattr(
        "anonymizer.controller.analytics._iter_series_dirs",
        _boom,
    )
    region_hits, organ_samples, segmented = _collect_tseg_anatomy(
        images,
        {"UID1": "CT"},
    )
    assert segmented == ("CT",)
    assert any(h.region == "Head" for h in region_hits)
    assert organ_samples[0].ml == pytest.approx(42.0)
    assert organ_samples[0].organ == "brain"


def test_rebuild_writes_ledger_from_images(tmp_path: Path) -> None:
    series_path = _project_series(tmp_path)
    cache = series_path / TSEG_CACHE_DIRNAME
    seg = cache / "seg"
    _write_brain_mask(seg, 2000)
    write_structure_voxels(cache, {"brain": 2000})
    write_primary_segment_voxels(cache, {"brain": 2000})

    images = tmp_path / "public"
    assert not ledger_exists(images)

    region_hits, organ_samples, segmented = rebuild_anatomy_ledger(
        images,
        {series_path.name: "CT"},
    )
    assert segmented == ("CT",)
    assert ledger_exists(images)
    rows = read_ledger_rows(images)
    assert series_path.name in rows
    assert "brain" in rows[series_path.name].organs_ml
    assert organ_samples
    assert region_hits or organ_samples


def test_second_collect_uses_ledger_after_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    series_path = _project_series(tmp_path)
    cache = series_path / TSEG_CACHE_DIRNAME
    _write_brain_mask(cache / "seg", 2000)
    write_structure_voxels(cache, {"brain": 2000})
    write_primary_segment_voxels(cache, {"brain": 2000})
    images = tmp_path / "public"

    first = _collect_tseg_anatomy(images, {series_path.name: "CT"})
    assert ledger_exists(images)
    assert first[2] == ("CT",)

    calls = {"n": 0}
    from anonymizer.controller import analytics as analytics_mod

    real_iter = analytics_mod._iter_series_dirs

    def _counting(images_dir: Path) -> list[Path]:
        calls["n"] += 1
        return real_iter(images_dir)

    monkeypatch.setattr(analytics_mod, "_iter_series_dirs", _counting)
    second = _collect_tseg_anatomy(images, {series_path.name: "CT"})
    assert calls["n"] == 0
    assert second[2] == first[2]
    assert len(second[1]) == len(first[1])


def test_finalize_upserts_ledger_for_project_series(tmp_path: Path) -> None:
    series_path = _project_series(tmp_path, series="UID9")
    cache = series_path / TSEG_CACHE_DIRNAME
    seg = cache / "seg"
    _write_brain_mask(seg, 2000)
    finalize_seg_cache(cache, seg, {"brain": 2000})

    images = tmp_path / "public"
    assert ledger_exists(images)
    rows = read_ledger_rows(images)
    assert "UID9" in rows
    assert rows["UID9"].organs_ml.get("brain", 0) > 0


def test_upsert_from_cache_skips_flat_test_layout(tmp_path: Path) -> None:
    cache = tmp_path / TSEG_CACHE_DIRNAME
    seg = cache / "seg"
    _write_brain_mask(seg, 2000)
    write_structure_voxels(cache, {"brain": 2000})
    write_primary_segment_voxels(cache, {"brain": 2000})
    assert upsert_series_ledger_from_cache(cache) is None
    assert not ledger_path_for_images_dir(tmp_path).is_file()


def test_series_anatomy_contribution_builds_row(tmp_path: Path) -> None:
    series_path = _project_series(tmp_path)
    cache = series_path / TSEG_CACHE_DIRNAME
    _write_brain_mask(cache / "seg", 2000)
    write_structure_voxels(cache, {"brain": 2000})
    write_primary_segment_voxels(cache, {"brain": 2000})
    contrib = _series_anatomy_contribution(series_path, "CT")
    assert contrib is not None
    _hits, samples, row = contrib
    assert row.anon_series_uid == series_path.name
    assert row.modality == "CT"
    assert samples
    assert "brain" in row.organs_ml
