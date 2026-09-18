"""Analytics board layout rules: relevance, layout manager, AI zero omission."""

from __future__ import annotations

from datetime import datetime

from anonymizer.controller.analytics import (
    AnalyticsFilterIndex,
    AnatomyAnalytics,
    Distribution,
    OrganVolumeDistribution,
    OrganVolumeSample,
    _PatientRow,
    _SeriesRow,
    _ai_coverage_distribution,
    _assemble_from_index,
    default_selected_organ_names,
)
from anonymizer.utils.translate import _
from anonymizer.view.shell.analytics_charts import (
    WidgetSpec,
    modality_distinct_count,
    plan_board_layout,
    select_board_sections,
    select_widgets,
)


def _noop_paint(cell, analytics, theme) -> None:
    return None


def _spec(key: str) -> WidgetSpec:
    return WidgetSpec(key=key, relevant=lambda _a: True, paint=_noop_paint)


def _snap_multi_modality():
    index = AnalyticsFilterIndex(
        patients=(
            _PatientRow(_("Male"), 30.0, "White", frozenset({"CT", "MR"})),
            _PatientRow(_("Female"), 40.0, _("Unknown"), frozenset({"CT"})),
        ),
        series=(
            _SeriesRow("CT", "s1", True, False, False),
            _SeriesRow("MR", "s2", False, False, False),
            _SeriesRow("CT", "s3", False, False, False),
        ),
        region_hits=(),
        organ_samples=(),
        segmented_modalities=("CT",),
    )
    return _assemble_from_index(index, datetime.now().astimezone())


def test_modality_pie_only_when_more_than_one_modality() -> None:
    multi = _snap_multi_modality()
    assert modality_distinct_count(multi.imaging.modality) == 2
    assert "modality" in {w.key for w in select_widgets(multi)}

    single_index = AnalyticsFilterIndex(
        patients=(_PatientRow(_("Male"), 30.0, "White", frozenset({"CT"})),),
        series=(_SeriesRow("CT", "s1", True, False, False),),
        region_hits=(),
        organ_samples=(),
        segmented_modalities=(),
    )
    single = _assemble_from_index(single_index, datetime.now().astimezone())
    assert modality_distinct_count(single.imaging.modality) == 1
    assert "modality" not in {w.key for w in select_widgets(single)}


def test_ai_coverage_omits_rounded_zero_percent() -> None:
    # 1/791 ≈ 0.13% → rounds to 0% and must be omitted.
    dist = _ai_coverage_distribution(
        series_total=791,
        series_harmonized=310,
        series_face_blur=1,
        series_pixel_phi=0,
    )
    labels = [b.label for b in dist.items]
    assert _("Harmonize") in labels
    assert _("Face blur") not in labels
    assert _("Pixel PHI") not in labels


def test_plan_board_layout_orphan_spans_full_row() -> None:
    """3 widgets → row0 pair, row1 lone widget spans both columns (uses L→R space)."""
    layout = plan_board_layout([_spec("a"), _spec("b"), _spec("c")])
    assert layout.cols == 2
    assert layout.rows == 2
    assert [(p.spec.key, p.row, p.col, p.colspan) for p in layout.placements] == [
        ("a", 0, 0, 1),
        ("b", 0, 1, 1),
        ("c", 1, 0, 2),
    ]
    assert layout.figsize_for(layout.placements[-1])[0] > layout.figsize_for(layout.placements[0])[0]


def test_plan_board_layout_even_count_no_orphan_span() -> None:
    layout = plan_board_layout([_spec("a"), _spec("b"), _spec("c"), _spec("d")])
    assert all(p.colspan == 1 for p in layout.placements)
    assert {(p.row, p.col) for p in layout.placements} == {(0, 0), (0, 1), (1, 0), (1, 1)}


def test_organs_expand_to_even_cells() -> None:
    snap = _snap_multi_modality()
    from dataclasses import replace

    snap = replace(
        snap,
        anatomy=AnatomyAnalytics(
            available=True,
            applicable=True,
            regions=Distribution(items=(), total=0),
            organ_volumes=(
                OrganVolumeDistribution("brain", (OrganVolumeSample("p0", 400.0), OrganVolumeSample("p1", 450.0),)),
                OrganVolumeDistribution("liver", (OrganVolumeSample("p0", 900.0), OrganVolumeSample("p1", 950.0),)),
            ),
            segmented_series=2,
            ct_mr_series=2,
        ),
    )
    keys = [w.key for w in select_widgets(snap)]
    assert "organ:brain" in keys
    assert "organ:liver" in keys
    assert "anatomy" not in keys
    layout = plan_board_layout(select_widgets(snap))
    assert layout.cols == 2
    # Layout manager may span a lone last cell; every other cell is single-width.
    for p in layout.placements:
        assert p.colspan in (1, layout.cols)


def test_graphical_widgets_before_textual() -> None:
    snap = _snap_multi_modality()
    from dataclasses import replace

    snap = replace(
        snap,
        anatomy=AnatomyAnalytics(
            available=True,
            applicable=True,
            regions=Distribution(items=(), total=0),
            organ_volumes=(OrganVolumeDistribution("brain", (OrganVolumeSample("p0", 400.0), OrganVolumeSample("p1", 450.0),)),),
            segmented_series=2,
            ct_mr_series=2,
        ),
    )
    keys = [w.key for w in select_widgets(snap)]
    assert "ai" in keys
    assert "organ:brain" in keys
    assert keys.index("organ:brain") < keys.index("ai")
    # AI follows modality/volumes before leftover charts (e.g. ethnicity).
    assert keys.index("modality") < keys.index("ai")


def test_no_volumes_places_ai_beside_modality() -> None:
    """With volumes unchecked, AI fills the second column next to modality."""
    snap = _snap_multi_modality()
    from dataclasses import replace

    snap = replace(
        snap,
        anatomy=AnatomyAnalytics(
            available=True,
            applicable=True,
            regions=Distribution(items=(), total=0),
            organ_volumes=(OrganVolumeDistribution("brain", (OrganVolumeSample("p0", 400.0), OrganVolumeSample("p1", 450.0),)),),
            segmented_series=2,
            ct_mr_series=2,
        ),
    )
    sections = select_board_sections(snap, selected_organs=())
    assert not sections.organs
    assert "modality" in {w.key for w in sections.charts}
    assert "ai" in {w.key for w in sections.texts}
    layout = plan_board_layout(sections.all)
    by_key = {p.spec.key: p for p in layout.placements}
    assert by_key["modality"].row == by_key["ai"].row
    assert by_key["modality"].col == 0
    assert by_key["ai"].col == 1
    assert by_key["modality"].colspan == 1
    assert by_key["ai"].colspan == 1

    """Fewer selected organs → fewer placements; empty selection → no organ cells."""
    snap = _snap_multi_modality()
    from dataclasses import replace

    organs = (
        OrganVolumeDistribution("brain", (OrganVolumeSample("p0", 400.0), OrganVolumeSample("p1", 450.0),)),
        OrganVolumeDistribution("liver", (OrganVolumeSample("p0", 900.0), OrganVolumeSample("p1", 950.0),)),
    )
    snap = replace(
        snap,
        anatomy=AnatomyAnalytics(
            available=True,
            applicable=True,
            regions=Distribution(items=(), total=0),
            organ_volumes=organs,
            segmented_series=2,
            ct_mr_series=2,
        ),
    )
    both = select_board_sections(snap, selected_organs=("brain", "liver"))
    one = select_board_sections(snap, selected_organs=("brain",))
    none = select_board_sections(snap, selected_organs=())
    assert len(both.organs) == 2
    assert len(one.organs) == 1
    assert len(none.organs) == 0
    assert plan_board_layout(one.organs).rows == 1
    assert plan_board_layout(none.organs).rows == 0

    snap = _snap_multi_modality()
    from dataclasses import replace

    organs = (
        OrganVolumeDistribution("brain", (OrganVolumeSample("p0", 400.0), OrganVolumeSample("p1", 450.0),)),
        OrganVolumeDistribution("liver", (OrganVolumeSample("p0", 900.0), OrganVolumeSample("p1", 950.0),)),
        OrganVolumeDistribution("heart", (OrganVolumeSample("p0", 200.0),)),
    )
    snap = replace(
        snap,
        anatomy=AnatomyAnalytics(
            available=True,
            applicable=True,
            regions=Distribution(items=(), total=0),
            organ_volumes=organs,
            segmented_series=2,
            ct_mr_series=2,
        ),
    )
    assert default_selected_organ_names(organs) == ("brain", "liver")
    default_keys = {w.key for w in select_widgets(snap)}
    assert "organ:brain" in default_keys
    assert "organ:liver" in default_keys
    assert "organ:heart" not in default_keys

    picked = {w.key for w in select_widgets(snap, selected_organs=("heart", "brain"))}
    assert picked & {"organ:brain", "organ:heart"} == {"organ:brain", "organ:heart"}
    assert "organ:liver" not in picked

    # Explicit empty selection must remove all organ widgets (not fall back to defaults).
    cleared = {w.key for w in select_widgets(snap, selected_organs=())}
    assert not any(k.startswith("organ:") for k in cleared)


def test_unknown_demo_omits_empty_ethnicity() -> None:
    index = AnalyticsFilterIndex(
        patients=(
            _PatientRow(_("Male"), 25.0, _("Unknown"), frozenset({"CR"})),
            _PatientRow(_("Unknown"), None, _("Unknown"), frozenset({"CR"})),
        ),
        series=(_SeriesRow("CR", "a", False, False, False),),
        region_hits=(),
        organ_samples=(),
        segmented_modalities=(),
    )
    snap = _assemble_from_index(index, datetime.now().astimezone())
    keys = {w.key for w in select_widgets(snap)}
    assert "sex" in keys
    assert "age" in keys
    assert "ethnicity" not in keys
    assert "modality" not in keys  # only CR
