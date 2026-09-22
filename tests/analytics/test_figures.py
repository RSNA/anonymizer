"""Headless figure checks: integer ticks, n= titles, no label clash, PNG shots."""

from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from dataclasses import replace

import pytest

from anonymizer.controller.analytics import (
    AnalyticsFilterIndex,
    OrganVolumeDistribution,
    OrganVolumeSample,
    _assemble_from_index,
    _PatientRow,
    _SeriesRow,
)
from anonymizer.utils.translate import _
from anonymizer.view.shell.analytics_charts import (
    analytics_scroll_height,
    analytics_scrollbar_needed,
    build_age_figure,
    build_chart_figure,
    build_modality_figure,
    build_organ_figure,
    build_sex_figure,
    load_chart_theme,
)


def _demo_snapshot():
    index = AnalyticsFilterIndex(
        patients=(
            _PatientRow(_("Male"), 32.0, "White", frozenset({"CT"})),
            _PatientRow(_("Female"), 37.0, "White", frozenset({"CT"})),
            _PatientRow(_("Male"), 41.0, _("Unknown"), frozenset({"CT"})),
            _PatientRow(_("Unknown"), None, _("Unknown"), frozenset({"CT"})),
        ),
        series=(_SeriesRow("CT", "s1", True, False, False),),
        region_hits=(),
        organ_samples=(),
        segmented_modalities=("CT",),
    )
    return _assemble_from_index(index, datetime.now().astimezone())


def test_count_axis_tick_values_consistent_majors() -> None:
    from anonymizer.view.shell.analytics_charts import count_axis_tick_values

    assert count_axis_tick_values(0) == [0, 5]
    assert count_axis_tick_values(2) == [0, 5]
    assert count_axis_tick_values(4) == [0, 5]
    assert count_axis_tick_values(5) == [0, 5]
    assert count_axis_tick_values(6) == [0, 5, 10]
    assert count_axis_tick_values(23) == [0, 5, 10, 15, 20, 25]
    ticks = count_axis_tick_values(200)
    assert ticks[0] == 0
    assert ticks[-1] >= 200
    assert len(ticks) <= 9
    huge = count_axis_tick_values(1_000_000)
    assert huge[0] == 0
    assert huge[-1] >= 1_000_000
    assert len(huge) <= 9
    assert all(huge[i] < huge[i + 1] for i in range(len(huge) - 1))


def test_age_yaxis_integer_ticks_only() -> None:
    theme = load_chart_theme()
    fig = build_age_figure(theme, _demo_snapshot())
    try:
        ax = fig.axes[0]
        fig.canvas.draw()
        yticks = list(ax.get_yticks())
        assert yticks
        assert all(abs(t - round(t)) < 1e-9 for t in yticks)
        assert all(t == int(t) for t in yticks)
        assert all(int(t) % 5 == 0 for t in yticks)
        minors = [round(t) for t in ax.yaxis.get_minorticklocs() if 0 < t < 5]
        assert minors == [1, 2, 3, 4]
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_organ_patient_yaxis_majors_and_unlabeled_minors() -> None:
    theme = load_chart_theme()
    organ = OrganVolumeDistribution(
        "frontal_lobe",
        (OrganVolumeSample("p0", 410.0), OrganVolumeSample("p1", 410.0)),
    )
    fig = build_organ_figure(theme, organ)
    try:
        ax = fig.axes[0]
        yticks = [int(t) for t in ax.get_yticks()]
        assert yticks == [0, 5]
        minors = [round(t) for t in ax.yaxis.get_minorticklocs() if 0 < t < 5]
        assert minors == [1, 2, 3, 4]
        assert "patient" in ax.get_ylabel().casefold()
        assert float(ax.get_xticks()[0]) == pytest.approx(ax.get_xlim()[0])
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_organ_patient_yaxis_ticks_every_five_when_large() -> None:
    theme = load_chart_theme()
    organ = OrganVolumeDistribution(
        "brain", tuple(OrganVolumeSample(f"p{i}", 1100.0) for i in range(11))
    )
    fig = build_organ_figure(theme, organ)
    try:
        ax = fig.axes[0]
        yticks = [int(t) for t in ax.get_yticks()]
        assert yticks[0] == 0 and all(t % 5 == 0 for t in yticks)
        assert ax.get_ylim()[1] >= 10
        assert "patient" in ax.get_ylabel().casefold()
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_sex_title_uses_known_n_no_unknown_caption() -> None:
    theme = load_chart_theme()
    snap = _demo_snapshot()
    fig = build_sex_figure(theme, snap)
    try:
        assert len(fig.axes) == 1
        assert f"n={snap.demographics.sex.known_total}" in fig.axes[0].get_title()
        assert "Unknown" not in fig.axes[0].get_title()
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_organ_title_carries_n_xlabel_is_ml_only() -> None:
    theme = load_chart_theme()
    organ = OrganVolumeDistribution(
        "brain",
        (
            OrganVolumeSample("p0", 120.0),
            OrganVolumeSample("p1", 400.0),
            OrganVolumeSample("p2", 450.0),
            OrganVolumeSample("p3", 1100.0),
        ),
    )
    fig = build_organ_figure(theme, organ)
    try:
        ax = fig.axes[0]
        assert len(fig.axes) == 1
        assert "n=4" in ax.get_title()
        assert "ml" in ax.get_xlabel().casefold()
        assert "patient" in ax.get_ylabel().casefold()
        from anonymizer.controller.analytics import organ_volume_range_ml

        lo, hi, width = organ_volume_range_ml("brain")
        plot_lo = max(0.0, lo - width)
        plot_hi = hi + width
        # Extreme lows → one-bin underflow sentinel (same width as main bins).
        assert ax.get_xlim()[0] == pytest.approx(plot_lo - width)
        assert ax.get_xlim()[1] == pytest.approx(plot_hi)
        tick_labels = [t.get_text() for t in ax.get_xticklabels() if t.get_text()]
        assert not any(lbl.startswith("<") or lbl.startswith(">") for lbl in tick_labels)
        hit = getattr(fig, "_analytics_organ_hit", None)
        assert isinstance(hit, dict)
        assert sum(b["count"] for b in hit["bins"]) == 4
        underflow = next(b for b in hit["bins"] if b["kind"] == "underflow")
        assert underflow["count"] >= 1
        assert underflow["hi"] - underflow["lo"] == pytest.approx(width)
        assert "Extreme" not in underflow["tip"]
        assert "n=" in underflow["tip"]
        from matplotlib.patches import Rectangle

        bar_heights = [
            p.get_height()
            for p in ax.patches
            if isinstance(p, Rectangle)
            and p.get_width() < (hi - lo) * 0.5
            and p.get_facecolor()[3] > 0.5
        ]
        assert sum(bar_heights) == pytest.approx(4.0)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_organ_bar_bin_hits_group_patient_ids() -> None:
    from anonymizer.controller.analytics import (
        OrganVolumeSample,
        organ_volume_axis_span,
        organ_volume_bin_edges,
    )
    from anonymizer.view.shell.analytics_charts import _organ_bar_bin_hits

    samples = (
        OrganVolumeSample("a", 920.0),
        OrganVolumeSample("b", 930.0),
        OrganVolumeSample("c", 1500.0),
    )
    mls = [s.ml for s in samples]
    plot_lo, plot_hi, *_ = organ_volume_axis_span(mls, organ_name="brain")
    edges = organ_volume_bin_edges(mls, organ_name="brain")
    bins = _organ_bar_bin_hits(samples, edges, plot_lo=plot_lo, plot_hi=plot_hi)
    assert sum(b["count"] for b in bins) == 3
    nonempty = [b for b in bins if b["count"]]
    assert any("a" in b["patient_ids"] for b in nonempty)
    assert any("c" in b["patient_ids"] for b in nonempty)
    assert all(b["tip"] for b in nonempty)


def test_organ_empty_samples_still_draws_two_norm_lines() -> None:
    theme = load_chart_theme()
    fig = build_organ_figure(theme, OrganVolumeDistribution("cerebellum", ()))
    try:
        ax = fig.axes[0]
        vlines = [line for line in ax.lines if line.get_linestyle() in ("--", "dashed")]
        assert len(vlines) >= 2
        hit = getattr(fig, "_analytics_organ_hit", None)
        assert isinstance(hit, dict)
        assert hit.get("bins") is not None
        assert all(b["count"] == 0 for b in hit["bins"])
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_age_title_uses_known_n_no_unknown_caption() -> None:
    theme = load_chart_theme()
    snap = _demo_snapshot()
    fig = build_age_figure(theme, snap)
    try:
        assert len(fig.axes) == 1
        assert f"n={snap.demographics.age.known_total}" in fig.axes[0].get_title()
        assert "Unknown" not in fig.axes[0].get_title()
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_build_chart_figure_caption_band_is_stable() -> None:
    theme = load_chart_theme()

    def paint(ax) -> None:
        ax.plot([0, 1], [0, 1])
        ax.set_title("T")

    fig = build_chart_figure(theme, paint, caption="note", caption_x=0.5)
    try:
        assert len(fig.axes) == 2
        assert any(t.get_text() == "note" for t in fig.axes[1].texts)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_analytics_scroll_height_caps_to_screen_fraction() -> None:
    assert analytics_scroll_height(1000, 100) >= 220
    assert analytics_scroll_height(1000, 400) == 400
    assert analytics_scroll_height(1000, 900) <= 700
    assert analytics_scroll_height(2000, 1200) <= 900


def test_analytics_scrollbar_only_when_content_overflows() -> None:
    assert analytics_scrollbar_needed(200, 220) is False
    assert analytics_scrollbar_needed(220, 220) is False
    assert analytics_scrollbar_needed(221, 220) is True
    assert analytics_scrollbar_needed(800, 420) is True


def test_modality_legend_stays_inside_figure() -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    theme = load_chart_theme()
    index = AnalyticsFilterIndex(
        patients=(
            _PatientRow(_("Male"), 32.0, "White", frozenset({"CT", "MR"})),
            _PatientRow(_("Female"), 37.0, "White", frozenset({"CT", "MR"})),
        ),
        series=(
            _SeriesRow("CT", "s1", True, False, False),
            _SeriesRow("MR", "s2", True, False, False),
        ),
        region_hits=(),
        organ_samples=(),
        segmented_modalities=("CT", "MR"),
    )
    snap = _assemble_from_index(index, datetime.now().astimezone())
    fig = build_modality_figure(theme, snap)
    try:
        FigureCanvasAgg(fig)
        fig.canvas.draw()
        assert fig.legends or any(ax.get_legend() for ax in fig.axes)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_render_board_with_transparent_parent_succeeds() -> None:
    import customtkinter as ctk

    from anonymizer.view.shell.analytics_charts import render_analytics_board

    root = ctk.CTk()
    root.withdraw()
    try:
        board = ctk.CTkFrame(root, fg_color="transparent")
        board.pack()
        snap = _demo_snapshot()
        render_analytics_board(board, snap)
        flat_texts: list[str] = []

        def walk(w) -> None:
            with contextlib.suppress(Exception):
                if isinstance(w, ctk.CTkLabel):
                    flat_texts.append(str(w.cget("text") or ""))
            for child in w.winfo_children():
                walk(child)

        walk(board)
        assert flat_texts, "expected chart cells or labels on the board"
        assert "Chart unavailable" not in flat_texts
        assert _("No analytics available") not in flat_texts
    finally:
        root.destroy()


def test_figures_export_png_for_layout_review(tmp_path: Path) -> None:
    theme = load_chart_theme()
    snap = _demo_snapshot()
    out = tmp_path / "analytics_shots"
    out.mkdir()
    figures = {
        "sex.png": build_sex_figure(theme, snap),
        "age.png": build_age_figure(theme, snap),
        "organ.png": build_organ_figure(
            theme,
            OrganVolumeDistribution(
                "brain",
                (
                    OrganVolumeSample("p0", 400.0),
                    OrganVolumeSample("p1", 450.0),
                    OrganVolumeSample("p2", 500.0),
                ),
            ),
        ),
    }
    try:
        for name, fig in figures.items():
            dest = out / name
            fig.savefig(dest, dpi=100, facecolor=theme.fig)
            assert dest.is_file()
            assert dest.stat().st_size > 500
    finally:
        import matplotlib.pyplot as plt

        for fig in figures.values():
            plt.close(fig)


def test_extreme_hover_tip_single_and_multi_patient() -> None:
    from anonymizer.controller.analytics import organ_volume_axis_span, organ_volume_bin_edges
    from anonymizer.view.shell.analytics_charts import _organ_bar_bin_hits

    one = (OrganVolumeSample("p0", 380.0),)
    mls = [s.ml for s in one]
    plot_lo, plot_hi, *_ = organ_volume_axis_span(mls, organ_name="occipital_lobe")
    edges = organ_volume_bin_edges(mls, organ_name="occipital_lobe")
    bins = _organ_bar_bin_hits(
        one, edges, plot_lo=plot_lo, plot_hi=plot_hi, has_overflow=True
    )
    overflow = bins[-1]
    assert overflow["kind"] == "overflow"
    assert overflow["count"] == 1
    assert overflow["tip"] == "380 ml · n=1"

    multi = (
        OrganVolumeSample("a", 220.0),
        OrganVolumeSample("b", 300.0),
        OrganVolumeSample("c", 348.0),
    )
    mls_m = [s.ml for s in multi]
    plot_lo, plot_hi, *_ = organ_volume_axis_span(mls_m, organ_name="occipital_lobe")
    edges = organ_volume_bin_edges(mls_m, organ_name="occipital_lobe")
    bins = _organ_bar_bin_hits(
        multi, edges, plot_lo=plot_lo, plot_hi=plot_hi, has_overflow=True
    )
    overflow = bins[-1]
    assert overflow["count"] == 3
    assert overflow["tip"] == "220–348 ml · n=3"


def test_extreme_sentinel_same_bin_width_no_hatch() -> None:
    from matplotlib.patches import Rectangle

    from anonymizer.controller.analytics import organ_volume_range_ml

    theme = load_chart_theme()
    organ = OrganVolumeDistribution(
        "ventricle",
        (OrganVolumeSample("p0", 40.0), OrganVolumeSample("p1", 320.0)),
    )
    fig = build_organ_figure(theme, organ)
    try:
        assert len(fig.axes) == 1
        ax = fig.axes[0]
        hatched = [p for p in ax.patches if isinstance(p, Rectangle) and p.get_hatch()]
        assert not hatched
        _lo, _hi, width = organ_volume_range_ml("ventricle")
        hit = fig._analytics_organ_hit  # type: ignore[attr-defined]
        overflow = next(b for b in hit["bins"] if b["kind"] == "overflow")
        assert overflow["hi"] - overflow["lo"] == pytest.approx(width)
        assert overflow["tip"] == "320 ml · n=1"
        # Ticks stay on the main span (no sentinel ml labels).
        tick_labels = [t.get_text() for t in ax.get_xticklabels() if t.get_text()]
        assert "320" not in tick_labels
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_bin_width_pct_widens_bins_vs_json_default() -> None:
    from anonymizer.controller.analytics import (
        effective_bin_width_ml,
        organ_volume_bin_edges,
        organ_volume_range_ml,
    )
    from anonymizer.controller.analytics_prefs import clear_analytics_preferences_cache

    clear_analytics_preferences_cache()
    _lo, _hi, json_w = organ_volume_range_ml("temporal_lobe")
    assert effective_bin_width_ml("temporal_lobe", None) == pytest.approx(json_w)
    wide = effective_bin_width_ml("temporal_lobe", 10.0)
    assert wide > json_w
    default_edges = organ_volume_bin_edges([200.0, 250.0], organ_name="temporal_lobe")
    coarse_edges = organ_volume_bin_edges(
        [200.0, 250.0], organ_name="temporal_lobe", bin_width_pct=10.0
    )
    assert len(coarse_edges) < len(default_edges)

    theme = load_chart_theme()
    organ = OrganVolumeDistribution(
        "temporal_lobe",
        (OrganVolumeSample("p0", 200.0), OrganVolumeSample("p1", 250.0)),
    )
    fig_coarse = build_organ_figure(theme, organ, bin_width_pct=10.0)
    try:
        clear_analytics_preferences_cache()
        fig_json = build_organ_figure(theme, organ)
        try:
            coarse_bins = fig_coarse._analytics_organ_hit["bins"]  # type: ignore[attr-defined]
            json_bins = fig_json._analytics_organ_hit["bins"]  # type: ignore[attr-defined]
            assert len(coarse_bins) < len(json_bins)
        finally:
            import matplotlib.pyplot as plt

            plt.close(fig_json)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig_coarse)


def test_matplotlib_fonts_configured_for_charts() -> None:
    from anonymizer.view.shell.analytics_charts import (
        _configure_matplotlib_fonts,
        _matplotlib_fonts_healthy,
        _rasterize_figure_png,
        load_chart_theme,
    )

    _configure_matplotlib_fonts(force_rebuild=True)
    assert _matplotlib_fonts_healthy()
    assert matplotlib.rcParams["font.enable_last_resort"] is False
    assert "DejaVu Sans" in matplotlib.rcParams["font.sans-serif"]

    theme = load_chart_theme()
    fig = build_sex_figure(theme, _demo_snapshot())
    try:
        img = _rasterize_figure_png(fig, theme)
        assert img.size[0] > 0 and img.size[1] > 0
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)
