"""Capture fixture caches: TS copy/harvest (no OCR box cache)."""

from pathlib import Path

from docs_help.fixture_cache import (
    harvest_tseg_cache_from_tree,
    pixel_phi_lookup_labels,
    save_tseg_cache,
    seed_tseg_cache,
    tseg_anatomy_cache_ready,
)


def test_pixel_phi_lookup_labels_are_text_not_boxes() -> None:
    labels = pixel_phi_lookup_labels("davidson_cxr")
    assert "DAVIDSON" in labels
    assert "Portable" in labels
    assert pixel_phi_lookup_labels("missing_fixture") == []


def test_seed_tseg_clears_orphan_masks_without_fixture_cache(tmp_path: Path, monkeypatch) -> None:
    from docs_help import fixture_cache as fc

    monkeypatch.setattr(fc, "TSEG_CACHE_ROOT", tmp_path / "fixture_cache")
    series = tmp_path / "davidson_series"
    seg = series / "0_TS_SEG" / "seg"
    seg.mkdir(parents=True)
    (seg / "brain.nii.gz").write_bytes(b"nii")
    assert seed_tseg_cache(series, "davidson_cxr") is False
    assert not (series / "0_TS_SEG").exists()


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
