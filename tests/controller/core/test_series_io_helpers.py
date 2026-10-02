"""Additional series_io coverage: projections, view stack, LOINC apply, helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydicom import dcmread

from anonymizer.controller.series_io import (
    apply_series_description,
    apply_study_description,
    clip_and_cast_to_int,
    compute_series_projections,
    load_series_frames,
    series_buffer_monochrome_to_stored,
    stored_monochrome_to_series_buffer,
)
from tests.controller.tseg.support.synthetic_ct import build_synthetic_ct_small_series


def test_compute_projections_and_series_view_stack(tmp_path: Path) -> None:
    series_dir = build_synthetic_ct_small_series(tmp_path / "ct", num_slices=11)
    loaded = load_series_frames(series_dir)
    proj = compute_series_projections(loaded.frames)
    assert proj.minimum.shape == loaded.frames.shape[1:]
    assert proj.maximum.shape == loaded.frames.shape[1:]
    assert proj.mean.shape == loaded.frames.shape[1:]

    stack = loaded.series_view_stack()
    assert stack.shape[0] == loaded.frames.shape[0] + 3
    slices = loaded.series_view_slices_from_stack(stack)
    assert slices.shape == loaded.frames.shape

    with pytest.raises(ValueError):
        compute_series_projections(np.zeros((4, 4)))


def test_clip_and_cast_and_monochrome_buffer_helpers(tmp_path: Path) -> None:
    floats = np.array([[-5.5, 1.2], [300.0, 10.9]], dtype=np.float32)
    casted = clip_and_cast_to_int(floats, np.uint8)
    assert casted is not None
    assert casted.dtype == np.uint8
    assert int(casted[0, 0]) == 0

    series_dir = build_synthetic_ct_small_series(tmp_path / "buf", num_slices=11)
    loaded = load_series_frames(series_dir)
    ds = loaded.metadata
    frame = loaded.frames[0]
    # Round-trip through stored helpers when frames are already viewer-space is lossy;
    # just ensure helpers accept a DICOM dataset + array.
    stored = series_buffer_monochrome_to_stored(frame.astype(np.float32), ds)
    assert stored.ndim == 2
    viewer, mono1_max = stored_monochrome_to_series_buffer(stored, ds)
    assert viewer.ndim == 2
    assert mono1_max is None or isinstance(mono1_max, float)


def test_apply_study_description_with_loinc(tmp_path: Path) -> None:
    series_dir = build_synthetic_ct_small_series(tmp_path / "pt" / "st" / "ser", num_slices=11)
    study = series_dir.parent
    assert apply_study_description(study, "CT Chest W contrast IV", loinc_number="42274-1") is True
    ds = dcmread(next(series_dir.glob("*.dcm")), stop_before_pixels=True)
    assert str(ds.StudyDescription) == "CT Chest W contrast IV"
    assert str(ds.ProcedureCodeSequence[0].CodeValue) == "42274-1"

    assert apply_series_description(tmp_path / "missing", "x") is False
    assert apply_study_description(tmp_path / "missing", "x") is False
    assert apply_study_description(study, "   ") is False
