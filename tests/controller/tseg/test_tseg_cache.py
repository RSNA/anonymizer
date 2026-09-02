"""Tests for per-series TotalSegmentator cache directory helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from anonymizer.controller.ai.tseg.cache import (
    clear_series_tseg_cache,
    clear_tseg_series_cache,
    resolve_series_cache_dir,
    tseg_cache_summary,
)
from anonymizer.controller.ai.tseg.config import TSEG_CACHE_DIRNAME


def test_resolve_series_cache_dir_uses_standard_name(tmp_path: Path) -> None:
    cache = tmp_path / TSEG_CACHE_DIRNAME
    cache.mkdir()
    (cache / "geometry.json").write_text("{}", encoding="utf-8")

    assert resolve_series_cache_dir(tmp_path) == cache


def test_tseg_cache_summary_empty_series(tmp_path: Path) -> None:
    summary = tseg_cache_summary(tmp_path)

    assert summary.exists is False
    assert summary.file_count == 0
    assert summary.size_bytes == 0
    assert summary.path == tmp_path / TSEG_CACHE_DIRNAME


def test_clear_tseg_series_cache_removes_cache(tmp_path: Path) -> None:
    cache = tmp_path / TSEG_CACHE_DIRNAME
    cache.mkdir()
    (cache / "volume.nii.gz").write_bytes(b"x" * 128)

    dicom = tmp_path / "slice.dcm"
    dicom.write_bytes(b"DICOM")

    assert clear_tseg_series_cache(tmp_path) is True
    assert not cache.exists()
    assert dicom.is_file()
    assert tseg_cache_summary(tmp_path).exists is False


def test_clear_series_tseg_cache_updates_model_metadata(tmp_path: Path) -> None:
    cache = tmp_path / TSEG_CACHE_DIRNAME
    cache.mkdir()
    (cache / "geometry.json").write_text("{}", encoding="utf-8")

    anon_model = MagicMock()

    assert clear_series_tseg_cache(tmp_path, anon_model=anon_model, anon_series_uid="anon-series-1") is True
    anon_model.clear_series_tseg_metadata.assert_called_once_with("anon-series-1")
    assert not cache.exists()
