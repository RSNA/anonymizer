"""Tests for batch memory estimation helpers."""

from __future__ import annotations

from anonymizer.utils.memory import estimate_batch_resources


def test_estimate_batch_resources_is_per_series_not_pending_count() -> None:
    """Memory estimate must not scale with how many series are queued."""
    single = estimate_batch_resources(
        includes_pixel_phi=True,
        includes_harmonize=True,
        includes_face_blur=True,
    )
    assert single.min_available_mb == 7_000.0
    assert "pending series" not in single.notes.lower()


def test_estimate_batch_resources_algorithm_additions() -> None:
    base = estimate_batch_resources(
        includes_pixel_phi=False,
        includes_harmonize=False,
        includes_face_blur=False,
    )
    assert base.min_available_mb == 1_500.0

    ocr = estimate_batch_resources(
        includes_pixel_phi=True,
        includes_harmonize=False,
        includes_face_blur=False,
    )
    assert ocr.min_available_mb == 3_000.0

    harmonize = estimate_batch_resources(
        includes_pixel_phi=False,
        includes_harmonize=True,
        includes_face_blur=False,
    )
    assert harmonize.min_available_mb == 4_000.0

    face_blur = estimate_batch_resources(
        includes_pixel_phi=False,
        includes_harmonize=False,
        includes_face_blur=True,
    )
    assert face_blur.min_available_mb == 3_000.0
