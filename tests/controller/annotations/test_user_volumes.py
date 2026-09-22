"""Tests for user annotation → analytics organ volumes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.ai.tseg.seg_retention import (
    ORGAN_VOLUMES_ML_FILENAME,
    write_organ_volumes_ml,
)
from anonymizer.controller.analytics import (
    _organ_volumes_ml_for_cache,
    _OrganSample,
    _patient_mean_samples_by_organ,
    has_organ_volume_range,
    organ_display_name,
    organ_volume_axis_span,
)
from anonymizer.controller.annotations import (
    add_user_label,
    analytics_organ_key,
    label_name_taken,
    load_annotate_session,
    resolve_normative_organ,
    save_annotate_session,
    stamp_brush,
    user_annotation_volumes_ml,
)


def _write_geometry_volume(cache_dir: Path, shape_zyx: tuple[int, int, int] = (4, 32, 32)) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    z, y, x = shape_zyx
    arr = np.zeros((z, y, x), dtype=np.int16)
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((1.0, 1.0, 2.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    sitk.WriteImage(img, str(cache_dir / "volume.nii.gz"), True)
    import json

    from anonymizer.controller.ai.tseg.seg_retention import (
        MASK_GEOMETRY_FILENAME,
        mask_geometry_from_image,
    )

    (cache_dir / MASK_GEOMETRY_FILENAME).write_text(
        json.dumps(mask_geometry_from_image(img)) + "\n", encoding="utf-8"
    )


def test_resolve_normative_organ_matches_key_and_display() -> None:
    assert resolve_normative_organ("liver") == "liver"
    assert resolve_normative_organ("Liver") == "liver"
    assert resolve_normative_organ("frontal lobe") == "frontal_lobe"
    assert resolve_normative_organ("Frontal_lobe") == "frontal_lobe"
    assert resolve_normative_organ("my tumor") is None


def test_label_name_taken_case_insensitive(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    add_user_label(session, "Lesion A")
    assert label_name_taken(session, "lesion a")
    assert label_name_taken(session, "  LESION A  ")
    assert not label_name_taken(session, "Lesion B")
    with pytest.raises(ValueError, match="already exists"):
        add_user_label(session, "lesion a")


def test_label_entry_normative_roundtrip(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    entry = add_user_label(session, "liver", normative_organ="liver")
    assert entry.normative_organ == "liver"
    assert analytics_organ_key(entry) == "liver"
    custom = add_user_label(session, "My ROI", normative_organ=None)
    assert custom.normative_organ is None
    assert analytics_organ_key(custom) == "user:my_roi"
    save_annotate_session(session)
    reloaded = load_annotate_session(cache)
    assert reloaded is not None
    assert reloaded.label_map[entry.label_id].normative_organ == "liver"
    assert reloaded.label_map[custom.label_id].normative_organ is None


def test_user_annotation_volumes_ml_and_merge_prefers_user(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    write_organ_volumes_ml(cache, {"liver": 999.0})
    assert (cache / ORGAN_VOLUMES_ML_FILENAME).is_file()

    session = load_annotate_session(cache)
    assert session is not None
    entry = add_user_label(session, "liver", normative_organ="liver")
    for y in range(10, 20):
        for x in range(10, 20):
            session.labels[1, y, x] = entry.label_id
    save_annotate_session(session)

    user = user_annotation_volumes_ml(cache)
    assert "liver" in user
    assert user["liver"] > 0
    assert user["liver"] < 999.0

    merged = _organ_volumes_ml_for_cache(cache)
    assert merged["liver"] == pytest.approx(user["liver"])


def test_custom_organ_samples_and_axis_without_normative_band(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    entry = add_user_label(session, "Custom Blob", normative_organ=None)
    stamp_brush(session.labels, slice_index=0, cy=16, cx=16, radius=4, value=entry.label_id)
    save_annotate_session(session)

    vols = user_annotation_volumes_ml(cache)
    key = analytics_organ_key(entry)
    assert key.startswith("user:")
    assert key in vols
    assert not has_organ_volume_range(key)

    samples = [
        _OrganSample(organ=key, modality="CT", ml=vols[key], anon_patient_id="p1"),
        _OrganSample(organ=key, modality="CT", ml=vols[key] * 1.2, anon_patient_id="p2"),
    ]
    by_organ = _patient_mean_samples_by_organ(samples, modality=None)
    assert key in by_organ
    assert len(by_organ[key]) == 2

    mls = [s.ml for s in by_organ[key]]
    plot_lo, plot_hi, norm_lo, norm_hi, _w = organ_volume_axis_span(mls, organ_name=key)
    assert norm_lo == plot_lo
    assert norm_hi == plot_hi
    assert organ_display_name(key) == "Custom blob"


def test_auto_resolve_on_add_without_explicit_normative(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    _write_geometry_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    entry = add_user_label(session, "Heart")
    assert entry.normative_organ == "heart"
