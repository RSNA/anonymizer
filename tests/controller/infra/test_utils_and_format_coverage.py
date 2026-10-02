"""Pure-ish coverage for utils + pipeline format helpers (under controller testpaths)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pydicom import Dataset

from anonymizer.controller.ai.harmonize._playbook_gettext import _register_playbook_label_msgids
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeProgress,
    format_harmonize_batch_series_label,
    format_harmonize_progress_message,
    series_description_group_choices,
)
from anonymizer.utils.memory import (
    MemoryGuard,
    MemorySnapshot,
    capture_memory_snapshot,
    collect_garbage_safe,
    estimate_batch_resources,
    format_array_memory,
    format_memory_snapshot_label,
    is_main_thread,
    log_process_memory,
    release_accelerator_caches,
)
from anonymizer.utils.windowing import apply_windowing


def test_register_playbook_label_msgids() -> None:
    _register_playbook_label_msgids()


def test_apply_windowing_branches() -> None:
    mono = np.full((32, 32), 1000.0, dtype=np.float32)
    out = apply_windowing(1000.0, 2000.0, mono)
    assert out.shape == (32, 32, 3) and out.dtype == np.uint8

    rgb = np.zeros((16, 16, 3), dtype=np.uint8)
    assert apply_windowing(127.5, 255.0, rgb).shape == (16, 16, 3)

    rgba = np.zeros((16, 16, 4), dtype=np.uint8)
    assert apply_windowing(127.5, 255.0, rgba).shape == (16, 16, 3)

    gray_u8 = np.zeros((16, 16), dtype=np.uint8)
    assert apply_windowing(127.5, 255.0, gray_u8).shape == (16, 16, 3)

    weird = np.zeros((8, 8, 5), dtype=np.uint8)
    assert apply_windowing(10.0, 20.0, weird).shape == (8, 8, 3)


def test_memory_helpers() -> None:
    assert "none" in format_array_memory(None)
    arr = np.zeros((4, 4), dtype=np.float32)
    assert "shape=" in format_array_memory(arr)

    snap = capture_memory_snapshot()
    if snap is not None:
        assert format_memory_snapshot_label(snap)
        assert snap.rss_mb >= 0

    est = estimate_batch_resources(
        includes_pixel_phi=True, includes_harmonize=True, includes_face_blur=True
    )
    assert est.min_available_mb > 1000
    est2 = estimate_batch_resources(
        includes_pixel_phi=False, includes_harmonize=False, includes_face_blur=False
    )
    assert est2.min_available_mb > 0

    guard = MemoryGuard(warn_available_mb=5000, abort_available_mb=100)
    assert guard.check(None) == "ok"
    low = MemorySnapshot(rss_mb=1, available_mb=50, total_mb=16000, percent_used=99)
    assert guard.check(low) == "abort"
    warn = MemorySnapshot(rss_mb=1, available_mb=2000, total_mb=16000, percent_used=50)
    assert guard.check(warn) == "warn"
    assert guard.should_log_warn() is True
    assert guard.should_log_warn() is False

    assert is_main_thread() is True
    collect_garbage_safe(generations=1)
    release_accelerator_caches()
    log_process_memory("pytest", array=arr, extra="cov")


def test_format_harmonize_progress_all_stages() -> None:
    stages = [
        ("done", ""),
        ("failed", ""),
        ("failed", "boom"),
        ("geometry", ""),
        ("prepare", ""),
        ("segment", "Segmenting anatomy"),
        ("segment", "Using cached anatomy segmentation"),
        ("regions", "Summarizing anatomy regions"),
        ("tseg", ""),
        ("contrast", ""),
        ("contrast_stats", ""),
        ("contrast_stats_cached", "Computing organ HU statistics"),
        ("contrast_stats_hn", ""),
        ("contrast_stats_hn_cached", ""),
        ("contrast_stats_hn_skip", ""),
        ("contrast_xgboost", ""),
        ("contrast_phase_cache", ""),
        ("merge", ""),
        ("unknown_stage", "Starting contrast phase analysis"),
        ("unknown_stage", "custom msg"),
        ("unknown_stage", ""),
    ]
    for stage, message in stages:
        text = format_harmonize_progress_message(
            HarmonizeProgress(stage=stage, message=message, fraction=0.5, elapsed_sec=1.0),
            include_pct=True,
            segmentation_mode=None,
        )
        assert isinstance(text, str) and text


def test_batch_series_label_and_group_choices() -> None:
    ds = Dataset()
    ds.SeriesDescription = "Chest AP"
    ds.SeriesNumber = 3
    assert "#" in format_harmonize_batch_series_label(Path("/x"), ds)
    ds2 = Dataset()
    ds2.SeriesNumber = 1
    assert format_harmonize_batch_series_label(Path("/x"), ds2)
    ds3 = Dataset()
    assert format_harmonize_batch_series_label(Path("/x"), ds3)

    choices = series_description_group_choices(
        modalities=["CR", "DX"],
        current_descriptions=["Chest AP", "Chest AP"],
        full_catalog=False,
    )
    assert isinstance(choices, list)
    assert series_description_group_choices(modalities=[], current_descriptions=[]) == []
    assert series_description_group_choices(
        modalities=["CR", "CT"],
        current_descriptions=["a", "b"],
    ) == []
