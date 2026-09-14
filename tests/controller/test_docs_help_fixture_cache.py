"""Capture fixture caches: TS copy/harvest and pixel-PHI detection JSON."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from docs_help.fixture_cache import (
    apply_cached_ocr_detections,
    cached_pixel_phi_labels,
    harvest_tseg_cache_from_tree,
    load_ocr_cache,
    save_tseg_cache,
    seed_tseg_cache,
    tseg_anatomy_cache_ready,
)


def test_load_ocr_cache_davidson_includes_portable() -> None:
    frames = load_ocr_cache("davidson_cxr")
    texts = [item.text for item in frames[0]]
    assert "DAVIDSON" in texts
    assert "Portable" in texts
    assert "DAVIDSON" in cached_pixel_phi_labels("davidson_cxr")


def test_load_ocr_cache_us_covers_exclude_panel() -> None:
    frames = load_ocr_cache("us_rgb_single_frame")
    texts = [item.text for item in frames[0]]
    assert "mindray" in texts
    assert any("FHS" in t for t in texts)
    assert "LIVER" in texts
    assert "Dist" in texts


def test_seed_and_save_tseg_cache(tmp_path: Path, monkeypatch) -> None:
    from docs_help import fixture_cache as fc

    monkeypatch.setattr(fc, "TSEG_CACHE_ROOT", tmp_path / "fixture_cache")
    series = tmp_path / "series"
    seg = series / "0_TS_SEG" / "seg"
    seg.mkdir(parents=True)
    (seg / "brain.nii.gz").write_bytes(b"nii")
    assert tseg_anatomy_cache_ready(series)
    assert save_tseg_cache(series, "CT_Head_With_Contrast")

    imported = tmp_path / "imported"
    imported.mkdir()
    assert seed_tseg_cache(imported, "CT_Head_With_Contrast")
    assert (imported / "0_TS_SEG" / "seg" / "brain.nii.gz").is_file()


def test_harvest_tseg_cache_from_tree(tmp_path: Path, monkeypatch) -> None:
    from docs_help import fixture_cache as fc

    monkeypatch.setattr(fc, "TSEG_CACHE_ROOT", tmp_path / "fixture_cache")
    leftover = tmp_path / "en_US" / "project" / "public" / "p" / "st" / "ser" / "0_TS_SEG" / "seg"
    leftover.mkdir(parents=True)
    (leftover / "liver.nii.gz").write_bytes(b"nii")
    assert harvest_tseg_cache_from_tree(tmp_path / "en_US")
    seeded = tmp_path / "next_series"
    seeded.mkdir()
    assert seed_tseg_cache(seeded, "CT_Head_With_Contrast")
    assert (seeded / "0_TS_SEG" / "seg" / "liver.nii.gz").is_file()


def test_save_tseg_cache_does_not_downgrade(tmp_path: Path, monkeypatch) -> None:
    from docs_help import fixture_cache as fc

    monkeypatch.setattr(fc, "TSEG_CACHE_ROOT", tmp_path / "fixture_cache")
    rich = tmp_path / "rich"
    rich_seg = rich / "0_TS_SEG" / "seg"
    rich_seg.mkdir(parents=True)
    (rich_seg / "brain.nii.gz").write_bytes(b"a")
    (rich_seg / "brainstem.nii.gz").write_bytes(b"b")
    assert save_tseg_cache(rich, "CT_Head_With_Contrast")

    poor = tmp_path / "poor"
    poor_seg = poor / "0_TS_SEG" / "seg"
    poor_seg.mkdir(parents=True)
    (poor_seg / "brain.nii.gz").write_bytes(b"a")
    assert save_tseg_cache(poor, "CT_Head_With_Contrast")
    cached = tmp_path / "fixture_cache" / "CT_Head_With_Contrast" / "0_TS_SEG" / "seg"
    assert (cached / "brainstem.nii.gz").is_file()


def test_apply_cached_ocr_detections_uses_series_view_path() -> None:
    applied: dict[int, list] = {}

    def _apply(result):
        applied.update(result)

    view = SimpleNamespace(
        _apply_ocr_detections_result=_apply,
        update_status=lambda *a, **k: None,
        _refresh_ocr_toolbar_buttons=lambda: None,
        image_viewer=SimpleNamespace(refresh_current_image=lambda: None),
    )
    count = apply_cached_ocr_detections(view, "davidson_cxr")
    assert count == 6
    assert 0 in applied
    assert any(t.text == "DAVIDSON" for t in applied[0])
