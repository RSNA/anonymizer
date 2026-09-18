"""Unit tests for Dataset analytics bucketing and organ volumes."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from anonymizer.controller.analytics import (
    AGE_BANDS,
    AnalyticsFilterIndex,
    AnatomyAnalytics,
    CountBucket,
    Distribution,
    OrganVolumeDistribution,
    OrganVolumeSample,
    _ai_coverage_distribution,
    _assemble_from_index,
    _collect_tseg_metrics,
    _distribution_excluding_unknown,
    _distribution_from_counter,
    _ethnicity_distribution,
    _OrganSample,
    _patient_mean_samples_by_organ,
    _PatientRow,
    _select_main_organ,
    _select_top_organs,
    _SeriesRow,
    age_band_for_dob,
    age_histogram_bin_edges,
    age_years_for_dob,
    normalize_sex_label,
    organ_volume_bin_edges,
    voxels_to_ml,
)
from anonymizer.utils.translate import _
from anonymizer.view.shell.analytics_charts import select_widgets


def test_normalize_sex_label() -> None:
    assert normalize_sex_label("M") == _("Male")
    assert normalize_sex_label("F") == _("Female")
    assert normalize_sex_label(None) == _("Unknown")
    assert normalize_sex_label("") == _("Unknown")


def test_age_years_and_bands_for_dob() -> None:
    assert age_years_for_dob(date(2010, 1, 1), date(2020, 1, 1)) == pytest.approx(10.0)
    assert age_years_for_dob(date(1990, 6, 1), date(2020, 6, 1)) == pytest.approx(30.0)
    assert age_years_for_dob(None, date(2020, 1, 1)) is None
    assert age_years_for_dob(date(1990, 1, 1), None) is None
    assert age_band_for_dob(date(2010, 1, 1), date(2020, 1, 1)) == "<18"
    assert age_band_for_dob(date(1990, 6, 1), date(2020, 6, 1)) == "18–39"
    assert age_band_for_dob(date(1970, 1, 1), date(2020, 1, 1)) == "40–59"
    assert age_band_for_dob(date(1950, 1, 1), date(2020, 1, 1)) == "60–79"
    assert age_band_for_dob(date(1930, 1, 1), date(2020, 1, 1)) == "80+"
    assert age_band_for_dob(None, date(2020, 1, 1)) == "Unknown"


def test_age_histogram_bin_edges_five_years() -> None:
    edges = age_histogram_bin_edges([12.0, 17.0, 33.0, 41.0])
    widths = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]
    assert all(w == pytest.approx(5.0) for w in widths)
    assert edges[0] == pytest.approx(0.0)
    assert edges[-1] == pytest.approx(100.0)
    # Single sample still gets the full static axis.
    assert age_histogram_bin_edges([37.0]) == edges
    assert age_histogram_bin_edges([]) == edges
    assert age_histogram_bin_edges(None) == edges


def test_ethnicity_distribution_excludes_unknown_from_items() -> None:
    counter = Counter(
        {
            "Hispanic": 10,
            "Asian": 8,
            "White": 6,
            "Black": 4,
            "Pacific": 3,
            "OtherRare": 2,
            "Unknown": 5,
        }
    )
    dist = _ethnicity_distribution(counter, top_n=3)
    labels = [b.label for b in dist.items]
    assert labels[:3] == ["Hispanic", "Asian", "White"]
    assert _("Other") in labels
    assert _("Unknown") not in labels
    assert dist.unknown_count == 5
    assert dist.total == sum(counter.values())
    assert dist.unknown_pct() == pytest.approx(100.0 * 5 / 38)


def test_sex_exclude_unknown_with_caption_counts() -> None:
    sex = _distribution_excluding_unknown(
        Counter({_("Male"): 2, _("Female"): 1, _("Unknown"): 7}),
        total=10,
        unknown_label=_("Unknown"),
    )
    assert [b.label for b in sex.items] == [_("Male"), _("Female")]
    assert sex.unknown_count == 7
    assert sex.known_total == 3
    assert sex.unknown_pct() == pytest.approx(70.0)


def test_ai_coverage_omits_zero_percent() -> None:
    dist = _ai_coverage_distribution(
        series_total=100,
        series_harmonized=40,
        series_face_blur=0,
        series_pixel_phi=5,
    )
    labels = [b.label for b in dist.items]
    assert labels == [_("Harmonize"), _("Pixel PHI")]
    assert _("Face blur") not in labels
    assert dist.total == 100
    assert dist.pct(40) == pytest.approx(40.0)

    empty = _ai_coverage_distribution(
        series_total=50,
        series_harmonized=0,
        series_face_blur=0,
        series_pixel_phi=0,
    )
    assert empty.items == ()
    assert empty.empty


def test_voxels_to_ml() -> None:
    assert voxels_to_ml(1000, (1.0, 1.0, 1.0)) == pytest.approx(1.0)
    assert voxels_to_ml(1000, (2.0, 1.0, 1.0)) == pytest.approx(2.0)
    assert voxels_to_ml(0, (1.0, 1.0, 1.0)) is None
    assert voxels_to_ml(100, None) is None


def test_select_top_organs_two_major() -> None:
    top = _select_top_organs(
        {
            "liver": [OrganVolumeSample("a", 100.0), OrganVolumeSample("b", 120.0)],
            "brain": [
                OrganVolumeSample("a", 500.0),
                OrganVolumeSample("b", 510.0),
                OrganVolumeSample("c", 520.0),
            ],
            "heart": [OrganVolumeSample("a", 80.0)],
        },
        top_n=2,
    )
    assert [o.organ_name for o in top] == ["brain", "liver"]
    assert top[0].patient_count == 3


def test_select_main_organ_by_patient_count_then_median() -> None:
    main = _select_main_organ(
        {
            "liver": [OrganVolumeSample("a", 100.0), OrganVolumeSample("b", 120.0)],
            "brain": [
                OrganVolumeSample("a", 500.0),
                OrganVolumeSample("b", 510.0),
                OrganVolumeSample("c", 520.0),
            ],
            "heart": [OrganVolumeSample("a", 80.0)],
        }
    )
    assert main is not None
    assert main.organ_name == "brain"
    assert main.patient_count == 3
    assert main.samples_ml == (500.0, 510.0, 520.0)


def test_collect_tseg_metrics_top_organ_histograms(tmp_path: Path) -> None:
    series = tmp_path / "pt" / "study" / "series"
    cache = series / "0_TS_SEG"
    cache.mkdir(parents=True)
    (cache / "primary_segment_voxels.json").write_text(
        json.dumps(
            {
                "liver": 500_000,
                "lungs": 400_000,
                "brain": 300_000,
                "kidneys": 200_000,
                "spleen": 100_000,
                "heart": 50_000,
                "spine": 900_000,
                "cerebellum": 80_000,
                "ventricle": 40_000,
                "brainstem": 30_000,
            }
        ),
        encoding="utf-8",
    )
    (cache / "structure_voxels.json").write_text(
        json.dumps({"liver": 500_000, "lung_upper_lobe_left": 200_000}),
        encoding="utf-8",
    )
    (cache / "mask_geometry.json").write_text(
        json.dumps(
            {
                "size": [10, 10, 10],
                "spacing": [1.0, 1.0, 1.0],
                "origin": [0, 0, 0],
                "direction": [1, 0, 0, 0, 1, 0, 0, 0, 1],
            }
        ),
        encoding="utf-8",
    )

    anatomy = _collect_tseg_metrics(tmp_path)
    assert anatomy.available
    assert anatomy.applicable
    # All VOLUME_SEGMENT_GROUPS organs with samples (incl. brain substructures
    # and skeletal latch groups when present in primary_segment_voxels).
    names = [o.organ_name for o in anatomy.organ_volumes]
    assert set(names) == {
        "liver",
        "lungs",
        "brain",
        "kidneys",
        "spleen",
        "heart",
        "spine",
        "cerebellum",
        "ventricle",
        "brainstem",
    }
    # Ranked by patient count then median ml — single patient → descending volume.
    assert names[0] == "spine"
    assert names[1] == "liver"
    liver = next(o for o in anatomy.organ_volumes if o.organ_name == "liver")
    assert liver.samples_ml == (500.0,)
    assert liver.patient_count == 1
    assert anatomy.segmented_series == 1


def test_patient_mean_samples_averages_multi_series_same_patient() -> None:
    samples = (
        _OrganSample("liver", "CT", 100.0, "ptA"),
        _OrganSample("liver", "CT", 200.0, "ptA"),
        _OrganSample("liver", "CT", 300.0, "ptB"),
    )
    by_organ = _patient_mean_samples_by_organ(samples, modality=None)
    assert sorted(s.ml for s in by_organ["liver"]) == pytest.approx([150.0, 300.0])
    assert {s.anon_patient_id for s in by_organ["liver"]} == {"ptA", "ptB"}


def test_patient_mean_samples_modality_filter_before_average() -> None:
    samples = (
        _OrganSample("brain", "CT", 400.0, "ptA"),
        _OrganSample("brain", "MR", 600.0, "ptA"),
        _OrganSample("brain", "CT", 500.0, "ptB"),
    )
    ct_only = _patient_mean_samples_by_organ(samples, modality="CT")
    assert sorted(s.ml for s in ct_only["brain"]) == pytest.approx([400.0, 500.0])
    assert {s.anon_patient_id for s in ct_only["brain"]} == {"ptA", "ptB"}


def test_assemble_anatomy_histograms_patient_means(tmp_path: Path) -> None:
    """Two series same patient → one hist sample = mean ml."""

    def _seed(series: Path, *, liver_voxels: int) -> None:
        cache = series / "0_TS_SEG"
        cache.mkdir(parents=True)
        (cache / "primary_segment_voxels.json").write_text(
            json.dumps({"liver": liver_voxels}),
            encoding="utf-8",
        )
        (cache / "structure_voxels.json").write_text(
            json.dumps({"liver": liver_voxels}),
            encoding="utf-8",
        )
        (cache / "mask_geometry.json").write_text(
            json.dumps(
                {
                    "size": [10, 10, 10],
                    "spacing": [1.0, 1.0, 1.0],
                    "origin": [0, 0, 0],
                    "direction": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                }
            ),
            encoding="utf-8",
        )

    _seed(tmp_path / "ptA" / "st1" / "ser1", liver_voxels=100_000)
    _seed(tmp_path / "ptA" / "st1" / "ser2", liver_voxels=200_000)
    _seed(tmp_path / "ptB" / "st1" / "ser3", liver_voxels=300_000)

    anatomy = _collect_tseg_metrics(tmp_path)
    liver = next(o for o in anatomy.organ_volumes if o.organ_name == "liver")
    assert liver.patient_count == 2
    assert sorted(liver.samples_ml) == pytest.approx([150.0, 300.0])


def test_organ_display_name_humanizes_underscores() -> None:
    from anonymizer.controller.analytics import organ_display_name

    assert organ_display_name("brain") == "Brain"
    assert organ_display_name("frontal_lobe") == "Frontal lobe"
    assert organ_display_name("caudate_nucleus") == "Caudate nucleus"


def test_distribution_order_and_pct() -> None:
    counter = Counter({"18–39": 2, "Unknown": 1, "<18": 3})
    dist = _distribution_from_counter(counter, total=6, order=AGE_BANDS)
    assert [b.label for b in dist.items[:3]] == ["<18", "18–39", "40–59"]
    assert dist.items[0].count == 3
    assert dist.pct(dist.items[0].count) == pytest.approx(50.0)
    assert dist.total == 6


def test_modality_filter_subsets_and_planar_anatomy() -> None:
    index = AnalyticsFilterIndex(
        patients=(
            _PatientRow(
                sex=_("Male"),
                age_years=30.0,
                ethnicity="White",
                modalities=frozenset({"CT", "CR"}),
            ),
            _PatientRow(
                sex=_("Female"),
                age_years=None,
                ethnicity=_("Unknown"),
                modalities=frozenset({"CR"}),
            ),
            _PatientRow(
                sex=_("Unknown"),
                age_years=50.0,
                ethnicity="Asian",
                modalities=frozenset({"MR"}),
            ),
        ),
        series=(
            _SeriesRow("CT", "s1", True, False, False),
            _SeriesRow("CT", "s2", False, False, False),
            _SeriesRow("CR", "s3", True, False, False),
            _SeriesRow("CR", "s4", False, False, False),
            _SeriesRow("MR", "s5", False, True, False),
        ),
        region_hits=(),
        organ_samples=(),
        segmented_modalities=("CT",),
    )
    full = _assemble_from_index(index, datetime.now().astimezone())
    assert full.demographics.sex.total == 3
    assert full.demographics.age.samples_years == (30.0, 50.0)
    assert full.demographics.age.unknown_count == 1
    assert full.imaging.modality.total == 5
    assert full.is_all_modalities
    assert full.anatomy.applicable
    assert full.anatomy.segmented_series == 1
    assert full.anatomy.ct_mr_series == 3

    cr_view = full.for_modality("CR")
    assert cr_view.demographics.sex.total == 2
    assert not cr_view.is_all_modalities
    assert cr_view.imaging.modality.total == 5
    assert cr_view.imaging.ai_coverage.total == 2
    assert cr_view.imaging.ai_coverage.items[0].label == _("Harmonize")
    assert not cr_view.anatomy.applicable
    assert cr_view.anatomy.organ_volumes == ()

    ct_view = full.for_modality("CT")
    assert ct_view.demographics.sex.total == 1
    assert ct_view.anatomy.applicable
    assert ct_view.anatomy.segmented_series == 1
    assert ct_view.anatomy.ct_mr_series == 2


def test_organ_volume_bin_edges_cover_normative_when_samples_inside() -> None:
    from anonymizer.controller.analytics import organ_volume_range_ml

    lo, hi, width = organ_volume_range_ml("brain")
    # In-range samples keep a one-bin pad so normative bounds stay inset.
    edges = organ_volume_bin_edges([lo + 10.0, hi - 10.0], organ_name="brain")
    assert edges[0] == pytest.approx(max(0.0, lo - width))
    assert edges[-1] == pytest.approx(hi + width)


def test_organ_volume_axis_pads_so_norm_lo_is_inset() -> None:
    """High-only outliers must not glue the left dotted bound to the spine."""
    from anonymizer.controller.analytics import organ_volume_axis_span, organ_volume_range_ml

    lo, hi, width = organ_volume_range_ml("frontal_lobe")
    axis_lo, axis_hi, norm_lo, norm_hi, _w = organ_volume_axis_span(
        [hi + 90.0], organ_name="frontal_lobe"
    )
    assert norm_lo == pytest.approx(lo)
    assert norm_hi == pytest.approx(hi)
    assert axis_lo == pytest.approx(max(0.0, lo - width))
    assert axis_lo < norm_lo  # left dotted line is interior, not at x=spine
    assert axis_hi >= hi + 90.0


def test_organ_volume_bin_edges_extend_for_outliers() -> None:
    from anonymizer.controller.analytics import organ_volume_axis_span, organ_volume_range_ml

    lo, hi, _width = organ_volume_range_ml("brain")
    below = lo - 200.0
    above = hi + 150.0
    axis_lo, axis_hi, norm_lo, norm_hi, _w = organ_volume_axis_span(
        [below, above], organ_name="brain"
    )
    assert norm_lo == pytest.approx(lo)
    assert norm_hi == pytest.approx(hi)
    assert axis_lo <= below
    assert axis_hi >= above
    edges = organ_volume_bin_edges([below, above], organ_name="brain")
    assert edges[0] == pytest.approx(axis_lo)
    assert edges[-1] == pytest.approx(axis_hi)


def test_organ_volume_ml_tick_values_are_sparse_and_skip_forced_bounds() -> None:
    from anonymizer.controller.analytics import organ_volume_ml_tick_values, organ_volume_range_ml

    lo, hi, width = organ_volume_range_ml("brain")
    ticks = organ_volume_ml_tick_values(lo - 100, hi + 100, width, max_ticks=6)
    assert 2 <= len(ticks) <= 6
    # Origin labeled; steps monotonic; no forced normative endpoints.
    assert ticks[0] == pytest.approx(lo - 100)
    assert all(ticks[i] < ticks[i + 1] for i in range(len(ticks) - 1))


def test_organ_volume_ml_tick_values_origin_omits_next_label() -> None:
    from anonymizer.controller.analytics import organ_volume_ml_tick_values

    # Frontal-lobe-like span: origin kept, next sparse label dropped (no overwrite).
    ticks = organ_volume_ml_tick_values(100.0, 420.0, 20.0, max_ticks=6)
    assert ticks[0] == pytest.approx(100.0)
    assert 200.0 not in ticks  # next-up from min omitted
    assert 2 <= len(ticks) <= 6
    assert all(ticks[i] < ticks[i + 1] for i in range(len(ticks) - 1))


def test_organ_volume_bin_edges_differ_by_organ() -> None:
    brain = organ_volume_bin_edges(organ_name="brain")
    liver = organ_volume_bin_edges(organ_name="liver")
    assert (brain[0], brain[-1]) != (liver[0], liver[-1])


def test_organ_volume_range_unknown_raises() -> None:
    from anonymizer.controller.analytics import organ_volume_range_ml

    with pytest.raises(KeyError, match="No normative volume range"):
        organ_volume_range_ml("not_a_real_organ")


def test_organ_volume_ranges_cover_primary_segment_groups() -> None:
    from anonymizer.controller.ai.tseg.config import PRIMARY_SEGMENT_GROUPS
    from anonymizer.controller.analytics import VOLUME_SEGMENT_GROUPS, load_organ_volume_ranges

    ranges = load_organ_volume_ranges()
    assert frozenset(PRIMARY_SEGMENT_GROUPS) == VOLUME_SEGMENT_GROUPS
    assert frozenset(PRIMARY_SEGMENT_GROUPS) <= ranges.keys()
    # Healthy-adult floors: no zero-min placeholders for soft organs / sulcus.
    for name in ("heart", "lungs", "stomach", "pancreas", "central_sulcus"):
        lo, _hi, _w = ranges[name]
        assert lo > 0.0
    for name in ("skull", "spine", "clavicles", "ribs"):
        assert name in ranges


def test_patient_mean_logs_warning_when_outside_normative(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from anonymizer.controller.analytics import organ_volume_range_ml

    lo, hi, _ = organ_volume_range_ml("lungs")
    above = hi + 500.0
    samples = (
        _OrganSample("lungs", "CT", above, "ptOut"),
        _OrganSample("lungs", "CT", (lo + hi) / 2.0, "ptOk"),
    )
    with caplog.at_level(logging.WARNING, logger="anonymizer.controller.analytics"):
        by_organ = _patient_mean_samples_by_organ(samples, modality=None)

    assert sorted(s.ml for s in by_organ["lungs"]) == pytest.approx(sorted([above, (lo + hi) / 2.0]))
    warnings = [r for r in caplog.records if "outside normative range" in r.getMessage()]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "organ=lungs" in msg
    assert "patient=ptOut" in msg
    assert "mean_vs_range=above" in msg
    assert f"normative=[{lo:.1f}, {hi:.1f}]" in msg
    assert "series_outside=" in msg
    assert "organ_volume_ranges_ml.json" in msg


def test_patient_mean_logs_when_series_oor_but_mean_inside(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from anonymizer.controller.analytics import organ_volume_range_ml

    lo, hi, _ = organ_volume_range_ml("heart")
    # One series far above, one far below → mean can land inside range.
    low = lo - 50.0
    high = hi + 50.0
    samples = (
        _OrganSample("heart", "CT", low, "ptMix"),
        _OrganSample("heart", "CT", high, "ptMix"),
    )
    mean = (low + high) / 2.0
    assert lo <= mean <= hi

    with caplog.at_level(logging.WARNING, logger="anonymizer.controller.analytics"):
        by_organ = _patient_mean_samples_by_organ(samples, modality=None)

    assert [s.ml for s in by_organ["heart"]] == pytest.approx([mean])
    assert by_organ["heart"][0].anon_patient_id == "ptMix"
    warnings = [r for r in caplog.records if "outside normative range" in r.getMessage()]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "patient=ptMix" in msg
    assert "mean_vs_range=inside" in msg
    assert "series_outside=" in msg


def test_select_widgets_omits_null_stats() -> None:
    index = AnalyticsFilterIndex(
        patients=(
            _PatientRow(_("Male"), 25.0, _("Unknown"), frozenset({"CR"})),
            _PatientRow(_("Unknown"), None, _("Unknown"), frozenset({"CR"})),
        ),
        series=(
            _SeriesRow("CR", "s1", False, False, False),
            _SeriesRow("CR", "s2", False, False, False),
        ),
        region_hits=(),
        organ_samples=(),
        segmented_modalities=(),
    )
    snap = _assemble_from_index(index, datetime.now().astimezone())
    keys = {w.key for w in select_widgets(snap)}
    assert "sex" in keys
    assert "age" in keys
    assert "ethnicity" not in keys
    assert "modality" not in keys  # single modality
    assert "ai" not in keys
    assert not any(k.startswith("organ:") for k in keys)


def test_select_widgets_includes_ai_and_organs_when_present() -> None:
    index = AnalyticsFilterIndex(
        patients=(_PatientRow(_("Female"), 45.0, "White", frozenset({"CT"})),),
        series=(_SeriesRow("CT", "s1", True, False, False),),
        region_hits=(),
        organ_samples=(),
        segmented_modalities=("CT",),
    )
    snap = _assemble_from_index(index, datetime.now().astimezone())
    snap = replace(
        snap,
        anatomy=AnatomyAnalytics(
            available=True,
            applicable=True,
            regions=Distribution(items=(CountBucket("Head", 1),), total=1),
            organ_volumes=(
                OrganVolumeDistribution(
                    "brain",
                    (
                        OrganVolumeSample("p0", 400.0),
                        OrganVolumeSample("p1", 450.0),
                        OrganVolumeSample("p2", 500.0),
                    ),
                ),
                OrganVolumeDistribution(
                    "liver",
                    (OrganVolumeSample("p0", 900.0), OrganVolumeSample("p1", 950.0)),
                ),
            ),
            segmented_series=1,
            ct_mr_series=1,
        ),
    )
    keys = {w.key for w in select_widgets(snap)}
    assert "ai" in keys
    assert "organ:brain" in keys
    assert "organ:liver" in keys
    assert "anatomy" not in keys
    assert "ethnicity" in keys
    assert "modality" not in keys  # only CT
