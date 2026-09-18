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

    # Small n: same 0…5 majors as large charts (minors carry 1–4 unlabeled).
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
    # Scales to 1e6 without exploding label count.
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
        # Consistent major step of 5; unlabeled minors fill 1–4.
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
        # ml origin labeled (left spine is not an unlabeled 0).
        assert float(ax.get_xticks()[0]) == pytest.approx(ax.get_xlim()[0])
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_organ_patient_yaxis_ticks_every_five_when_large() -> None:
    theme = load_chart_theme()
    organ = OrganVolumeDistribution("brain", tuple(OrganVolumeSample(f"p{i}", 120.0) for i in range(11)))
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
        assert len(fig.axes) == 1  # no Unknown caption band
        assert f"n={snap.demographics.sex.known_total}" in fig.axes[0].get_title()
        assert "Unknown" not in fig.axes[0].get_title()
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_organ_title_carries_n_xlabel_is_ml_only() -> None:
    theme = load_chart_theme()
    organ = OrganVolumeDistribution("brain", (OrganVolumeSample("p0", 120.0), OrganVolumeSample("p1", 400.0), OrganVolumeSample("p2", 450.0), OrganVolumeSample("p3", 1100.0)))
    fig = build_organ_figure(theme, organ)
    try:
        ax = fig.axes[0]
        assert "n=4" in ax.get_title()
        assert "ml" in ax.get_xlabel().casefold()
        assert "patient" in ax.get_ylabel().casefold()
        assert "n=" not in ax.get_xlabel()
        assert "segmented" not in ax.get_xlabel().casefold()
        from anonymizer.controller.analytics import organ_volume_range_ml

        lo, hi, width = organ_volume_range_ml("brain")
        xlim = ax.get_xlim()
        # Axis covers normative window (with one-bin pad) and the low outlier (120).
        assert xlim[0] <= 120.0 + 1e-6
        assert xlim[0] < lo  # left dotted bound is inset, not on the spine
        assert xlim[1] >= hi - 1e-6
        # Left origin is always labeled (prevents mistaking the spine for 0).
        assert float(ax.get_xticks()[0]) == pytest.approx(xlim[0])
        # Always two dotted normative bounds (not as axis tick labels).
        vlines = [line for line in ax.lines if line.get_linestyle() in ("--", "dashed")]
        assert len(vlines) >= 2
        vline_x = sorted({float(line.get_xdata()[0]) for line in vlines})
        assert vline_x[0] == pytest.approx(lo)
        assert vline_x[1] == pytest.approx(hi)
        # Sparse ml ticks — no clutter from forced norm min/max labels.
        assert len(ax.get_xticks()) <= 6
        hit = getattr(fig, "_analytics_organ_hit", None)
        assert isinstance(hit, dict)
        assert hit["norm_lo"] == pytest.approx(lo)
        assert hit["norm_hi"] == pytest.approx(hi)
        assert "Norm:" in hit["norm_tip"] and ".." in hit["norm_tip"]
        assert isinstance(hit.get("bins"), list) and hit["bins"]
        nonempty = [b for b in hit["bins"] if b["count"] > 0]
        assert nonempty
        assert all("patient_ids" in b and "tip" in b for b in nonempty)
        assert sum(b["count"] for b in hit["bins"]) == 4
        # Hist bars only (exclude normative axvspan rectangle).
        from matplotlib.patches import Rectangle

        bar_heights = [
            p.get_height()
            for p in ax.patches
            if isinstance(p, Rectangle) and p.get_width() < (hi - lo) * 0.5
        ]
        assert sum(bar_heights) == pytest.approx(4.0)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_organ_bar_bin_hits_group_patient_ids() -> None:
    from anonymizer.controller.analytics import OrganVolumeSample, organ_volume_bin_edges
    from anonymizer.view.shell.analytics_charts import _organ_bar_bin_hits

    samples = (
        OrganVolumeSample("a", 920.0),
        OrganVolumeSample("b", 930.0),
        OrganVolumeSample("c", 1500.0),
    )
    edges = organ_volume_bin_edges([s.ml for s in samples], organ_name="brain")
    bins = _organ_bar_bin_hits(samples, edges)
    assert sum(b["count"] for b in bins) == 3
    nonempty = [b for b in bins if b["count"]]
    assert any("a" in b["patient_ids"] for b in nonempty)
    assert any("c" in b["patient_ids"] for b in nonempty)
    assert all("n=" in b["tip"] for b in nonempty)


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
    # Grow with content until the screen-fraction / absolute cap.
    assert analytics_scroll_height(1000, 100) >= 220
    assert analytics_scroll_height(1000, 400) == 400
    assert analytics_scroll_height(1000, 900) <= 700  # 0.70 * 1000
    assert analytics_scroll_height(2000, 1200) <= 900  # absolute max


def test_analytics_scrollbar_only_when_content_overflows() -> None:
    assert analytics_scrollbar_needed(200, 220) is False
    assert analytics_scrollbar_needed(220, 220) is False
    assert analytics_scrollbar_needed(221, 220) is True
    assert analytics_scrollbar_needed(800, 420) is True


def test_modality_legend_stays_inside_figure() -> None:
    """Regression: legend was clipped / overwritten at the cell edge."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    theme = load_chart_theme()
    index = AnalyticsFilterIndex(
        patients=(
            _PatientRow(_("Male"), 32.0, "White", frozenset({"CT", "MR", "CR", "DX", "US"})),
        ),
        series=(
            _SeriesRow("CT", "s1", True, False, False),
            _SeriesRow("MR", "s2", False, False, False),
            _SeriesRow("CR", "s3", False, False, False),
            _SeriesRow("DX", "s4", False, False, False),
            _SeriesRow("US", "s5", False, False, False),
        ),
        region_hits=(),
        organ_samples=(),
        segmented_modalities=("CT",),
    )
    snap = _assemble_from_index(index, datetime.now().astimezone())
    fig = build_modality_figure(theme, snap)
    try:
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        renderer = canvas.get_renderer()
        legend = fig.axes[0].get_legend()
        assert legend is not None
        extent = legend.get_window_extent(renderer)
        # Small slack for antialias / rounding — must not spill past the figure.
        assert extent.x1 <= fig.bbox.x1 + 2
        assert extent.y0 >= fig.bbox.y0 - 2
        assert extent.y1 <= fig.bbox.y1 + 2
        labels = [t.get_text() for t in legend.get_texts()]
        assert len(labels) >= 5
        assert all("(" in text and ")" in text for text in labels)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_transparent_is_invalid_matplotlib_facecolor() -> None:
    """Guard: CTk 'transparent' must never reach Figure — this is the live crash."""
    import pytest
    from matplotlib.figure import Figure

    with pytest.raises(ValueError, match="Invalid RGBA"):
        Figure(facecolor="transparent")


def test_transparent_board_fg_does_not_break_figures() -> None:
    """Dashboard board is transparent; matplotlib must not receive that color."""
    from anonymizer.view.shell.analytics_charts import _mpl_figure_facecolor

    theme = load_chart_theme()
    safe = _mpl_figure_facecolor("transparent", fallback=theme.fig)
    assert safe.casefold() != "transparent"
    assert safe == theme.fig

    def paint(ax) -> None:
        ax.plot([0, 1], [1, 0])

    fig = build_chart_figure(replace(theme, fig=safe), paint)
    try:
        assert fig.get_facecolor() is not None
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_render_board_with_transparent_parent_succeeds() -> None:
    """Regression: render path used to set theme.fig='transparent' and show Chart unavailable."""
    import customtkinter as ctk

    from anonymizer.view.shell.analytics_charts import render_analytics_board

    root = ctk.CTk()
    root.withdraw()
    try:
        board = ctk.CTkFrame(root, fg_color="transparent")
        board.pack()
        assert str(board.cget("fg_color")).casefold() == "transparent"
        render_analytics_board(board, _demo_snapshot())

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
    """docs_help-style: rasterize figures to PNG for layout inspection."""
    theme = load_chart_theme()
    snap = _demo_snapshot()
    out = tmp_path / "analytics_shots"
    out.mkdir()
    figures = {
        "sex.png": build_sex_figure(theme, snap),
        "age.png": build_age_figure(theme, snap),
        "organ.png": build_organ_figure(theme, OrganVolumeDistribution("brain", (OrganVolumeSample("p0", 400.0), OrganVolumeSample("p1", 450.0), OrganVolumeSample("p2", 500.0)))),
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
