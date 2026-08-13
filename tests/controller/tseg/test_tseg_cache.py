"""Tests for per-series TotalSegmentator cache directory helpers."""

from __future__ import annotations

from pathlib import Path

from anonymizer.controller.ai.tseg.cache import (
    LEGACY_TSEG_CACHE_DIRNAME,
    clear_series_tseg_cache,
    clear_tseg_series_cache,
    resolve_series_cache_dir,
    tseg_cache_summary,
)
from anonymizer.controller.ai.tseg.config import TSEG_CACHE_DIRNAME


def test_resolve_series_cache_dir_uses_new_name(tmp_path: Path) -> None:
    cache = tmp_path / TSEG_CACHE_DIRNAME
    cache.mkdir()
    (cache / "geometry.json").write_text("{}", encoding="utf-8")

    assert resolve_series_cache_dir(tmp_path) == cache


def test_resolve_series_cache_dir_migrates_legacy(tmp_path: Path) -> None:
    legacy = tmp_path / LEGACY_TSEG_CACHE_DIRNAME
    legacy.mkdir()
    (legacy / "geometry.json").write_text("{}", encoding="utf-8")

    resolved = resolve_series_cache_dir(tmp_path)

    assert resolved == tmp_path / TSEG_CACHE_DIRNAME
    assert resolved.is_dir()
    assert (resolved / "geometry.json").is_file()
    assert not legacy.exists()


def test_tseg_cache_summary_empty_series(tmp_path: Path) -> None:
    summary = tseg_cache_summary(tmp_path)

    assert summary.exists is False
    assert summary.file_count == 0
    assert summary.size_bytes == 0
    assert summary.path == tmp_path / TSEG_CACHE_DIRNAME


def test_clear_tseg_series_cache_removes_new_and_legacy(tmp_path: Path) -> None:
    new_cache = tmp_path / TSEG_CACHE_DIRNAME
    new_cache.mkdir()
    (new_cache / "volume.nii.gz").write_bytes(b"x" * 128)

    legacy_cache = tmp_path / LEGACY_TSEG_CACHE_DIRNAME
    legacy_cache.mkdir()
    (legacy_cache / "geometry.json").write_text("{}", encoding="utf-8")

    dicom = tmp_path / "slice.dcm"
    dicom.write_bytes(b"DICOM")

    assert clear_tseg_series_cache(tmp_path) is True
    assert not new_cache.exists()
    assert not legacy_cache.exists()
    assert dicom.is_file()
    assert tseg_cache_summary(tmp_path).exists is False


def test_clear_series_tseg_cache_updates_model_metadata(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    cache = tmp_path / TSEG_CACHE_DIRNAME
    cache.mkdir()
    (cache / "geometry.json").write_text("{}", encoding="utf-8")

    anon_model = MagicMock()

    assert clear_series_tseg_cache(tmp_path, anon_model=anon_model, anon_series_uid="anon-series-1") is True
    anon_model.clear_series_tseg_metadata.assert_called_once_with("anon-series-1")
    assert not cache.exists()
