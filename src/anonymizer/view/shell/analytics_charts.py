"""Matplotlib chart helpers for the Dashboard Dataset analytics board.

Uses the Agg backend and ``ImageTk.PhotoImage`` (ImageViewer pattern) so charts
never embed a TkAgg canvas (which deadlocks CustomTkinter's main loop).

Layout contract
---------------
* Relevance-gated ``WidgetSpec`` registry → only widgets with real data.
* ``plan_board_layout`` owns row/col/span: even 2-col flow; a lone last-row
  widget spans the full width so L→R space is used.
* Board width is forced to the scroll viewport (CTk scroll inner frames
  otherwise shrink-wrap and leave a dead right gutter).
* Viewport grows with content up to a screen fraction; scrollbar only when
  content still overflows that cap. Mouse-wheel steps are pixel-granular (see
  ``configure_granular_scroll``); scrollbar thumb/trough stay native.
* Every figure uses a fixed template; sample size is ``· n=`` in the title
  (same pattern as organ volume histograms). No Unknown-% caption band.
* ``select_widgets`` orders chart widgets first, then textual (AI coverage).
* Count axes: labeled majors every 5 (scaled 1/2/5×10^k up to 1e6 patients);
  unlabeled minors subdivide each major interval (e.g. 1–4 between 0 and 5).
"""
from __future__ import annotations

import contextlib
import io
import logging
import math
import re
import sys
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import customtkinter as ctk
import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import AutoMinorLocator
from PIL import Image, ImageTk

from anonymizer.controller.analytics import (
    AgeHistogram,
    DatasetAnalytics,
    Distribution,
    OrganVolumeDistribution,
    OrganVolumeSample,
    age_histogram_bin_edges,
    default_selected_organ_names,
    organ_display_name,
    organ_volume_axis_span,
    organ_volume_bin_edges,
    organ_volume_bin_patient_ids,
    organ_volume_ml_tick_values,
)
from anonymizer.utils.translate import _
from anonymizer.view.common.ctk_safe import release_mpl_frame_images
from anonymizer.view.common.tooltip import MotionTooltipController

logger = logging.getLogger(__name__)

WidgetPainter = Callable[[ctk.CTkFrame, DatasetAnalytics, "ChartTheme"], None]
WidgetPredicate = Callable[[DatasetAnalytics], bool]
AxesPainter = Callable[[Axes], None]
OrganBarActivate = Callable[[str, tuple[str, ...]], None]

_TK_GRAY_RE = re.compile(r"^gr[ae]y(\d+)$", re.IGNORECASE)

# Uniform cell size so the 2-column board looks even.
_CELL_FIGSIZE = (3.2, 2.55)
_CELL_FIGSIZE_WIDE = (6.6, 2.55)  # orphan last-row span (full board width)
_DONUT_RIGHT = 0.58  # leave room for external legend labels
_AI_PADX = 10
# Prefer growing the project window with content; scroll only past this cap.
ANALYTICS_SCROLL_SCREEN_FRACTION = 0.70
ANALYTICS_SCROLL_MIN_HEIGHT = 220
ANALYTICS_SCROLL_MAX_HEIGHT = 900
# Pixel step per wheel notch (scrollbar thumb/trough stay native moveto — no flicker).
ANALYTICS_SCROLL_STEP_PX = 48
# Major tick spacing for patient/series count axes (keeps labels readable).
COUNT_AXIS_TICK_STEP = 5
COUNT_AXIS_MAX_TICKS = 8


@dataclass(frozen=True)
class ChartTheme:
    """Resolved Analytics theme colors for the current appearance mode."""

    panel_fg: Any
    fig: str
    text: str
    muted: str
    accent: str
    spine: str
    wedge_edge: str
    normative_band: str
    normative_bound: str
    outlier_bar: str
    palette: tuple[str, ...]


@dataclass(frozen=True)
class WidgetSpec:
    """One optional cell on the analytics board."""

    key: str
    relevant: WidgetPredicate
    paint: WidgetPainter
    weight: int = 1
    graphical: bool = True


@dataclass(frozen=True)
class BoardPlacement:
    """One widget cell in the analytics board grid."""

    spec: WidgetSpec
    row: int
    col: int
    colspan: int


@dataclass(frozen=True)
class BoardLayout:
    """Simple layout manager output: columns + placements that fill L→R."""

    cols: int
    placements: tuple[BoardPlacement, ...]

    @property
    def rows(self) -> int:
        if not self.placements:
            return 0
        return max(p.row for p in self.placements) + 1

    def figsize_for(self, placement: BoardPlacement) -> tuple[float, float]:
        return _CELL_FIGSIZE_WIDE if placement.colspan > 1 else _CELL_FIGSIZE


def _appearance_color(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[1] if ctk.get_appearance_mode() == "Dark" else value[0])
    return str(value)


def _mpl_color(color: str) -> str:
    raw = (color or "").strip()
    if not raw or raw.startswith("#"):
        return raw
    lower = raw.casefold()
    if lower in {"white", "black", "none"}:
        return lower

    root = getattr(tk, "_default_root", None)
    if root is not None:
        with contextlib.suppress(tk.TclError):
            r, g, b = root.winfo_rgb(raw)
            return f"#{r >> 8:02x}{g >> 8:02x}{b >> 8:02x}"

    match = _TK_GRAY_RE.match(raw)
    if match:
        level = max(0, min(100, int(match.group(1))))
        value = round(255 * level / 100)
        return f"#{value:02x}{value:02x}{value:02x}"
    return raw


def _theme_mpl(value: Any) -> str:
    return _mpl_color(_appearance_color(value))


def _mpl_figure_facecolor(value: Any, *, fallback: str) -> str:
    """Matplotlib-safe facecolor; never pass CTk ``transparent`` through."""
    resolved = _theme_mpl(value)
    if not resolved or resolved.casefold() in {"transparent", "none", ""}:
        return fallback
    return resolved


def _theme_section(name: str) -> Mapping[str, Any]:
    section = ctk.ThemeManager.theme.get(name)
    return section if isinstance(section, dict) else {}


def load_chart_theme() -> ChartTheme:
    analytics = _theme_section("Analytics")
    frame = _theme_section("CTkFrame")
    label = _theme_section("CTkLabel")
    button = _theme_section("CTkButton")
    entry = _theme_section("CTkEntry")

    panel_fg = "transparent"
    fig = _theme_mpl(analytics.get("fig_color", frame.get("fg_color", ["gray90", "gray13"])))
    text = _theme_mpl(analytics.get("text_color", label.get("text_color", ["#014F8F", "white"])))
    muted = _theme_mpl(
        analytics.get("muted_text_color", entry.get("placeholder_text_color", ["gray52", "gray62"]))
    )
    accent = _theme_mpl(analytics.get("accent_color", button.get("fg_color", ["#3a7ebf", "#1f538d"])))
    spine = _theme_mpl(analytics.get("spine_color", ["gray70", "gray40"]))
    wedge_edge = _theme_mpl(analytics.get("wedge_edge_color", frame.get("fg_color", ["gray90", "gray13"])))
    normative_band = _theme_mpl(analytics.get("normative_band_color", ["#DCE4EE", "#1E3A5F"]))
    normative_bound = _theme_mpl(analytics.get("normative_bound_color", spine))
    outlier_bar = _theme_mpl(analytics.get("outlier_bar_color", muted))

    raw_palette = analytics.get("palette")
    if isinstance(raw_palette, list) and raw_palette:
        palette = tuple(_theme_mpl(item) for item in raw_palette)
    else:
        palette = (accent, text, spine, muted)

    return ChartTheme(
        panel_fg=panel_fg,
        fig=fig,
        text=text,
        muted=muted,
        accent=accent,
        spine=spine,
        wedge_edge=wedge_edge,
        normative_band=normative_band,
        normative_bound=normative_bound,
        outlier_bar=outlier_bar,
        palette=palette,
    )


def analytics_scroll_height(screen_height: int, content_height: int) -> int:
    """Viewport height: grow with content, then cap to a screen fraction."""
    cap = max(
        ANALYTICS_SCROLL_MIN_HEIGHT,
        min(ANALYTICS_SCROLL_MAX_HEIGHT, int(screen_height * ANALYTICS_SCROLL_SCREEN_FRACTION)),
    )
    return max(ANALYTICS_SCROLL_MIN_HEIGHT, min(content_height, cap))


def analytics_scrollbar_needed(content_height: int, viewport_height: int) -> bool:
    """True only when content strictly exceeds the scroll viewport."""
    return content_height > viewport_height


def _wheel_notches(delta: int) -> int:
    """Map a platform MouseWheel delta to a small signed notch count (±1…3)."""
    if not delta:
        return 0
    if sys.platform.startswith("win"):
        notches = -int(delta / 120)
        if notches == 0:
            notches = -1 if delta > 0 else 1
    else:
        # darwin/X11: dampen large trackpad bursts so one gesture ≠ full page.
        magnitude = min(3, max(1, abs(int(delta))))
        notches = -magnitude if delta > 0 else magnitude
    return notches


def configure_granular_scroll(
    scroll: ctk.CTkScrollableFrame,
    *,
    step_px: int = ANALYTICS_SCROLL_STEP_PX,
) -> None:
    """Pixel-level mouse-wheel steps; scrollbar ``moveto`` stays native (no flicker).

    CTk's default darwin ``yscrollincrement`` and raw ``event.delta`` can jump
    nearly a full viewport per wheel notch — dampen the wheel only. Rewriting
    scrollbar ``moveto`` fights thumb drag and causes flicker.
    """
    canvas = getattr(scroll, "_parent_canvas", None)
    if canvas is None:
        return

    step = max(1, int(step_px))
    canvas.configure(yscrollincrement=1, xscrollincrement=1)

    def _mouse_wheel_all(event: tk.Event) -> str | None:
        if not scroll.check_if_master_is_canvas(event.widget):
            return None
        notches = _wheel_notches(int(getattr(event, "delta", 0) or 0))
        if notches == 0:
            return None
        if canvas.yview() == (0.0, 1.0):
            return None
        canvas.yview_scroll(notches * step, "units")
        return "break"

    scroll._mouse_wheel_all = _mouse_wheel_all  # type: ignore[method-assign]


def plan_board_layout(widgets: Sequence[WidgetSpec], *, cols: int | None = None) -> BoardLayout:
    """Row-major 2-column layout: fill both columns before starting the next row.

    Widgets are placed left→right. Only a true leftover last cell (odd count)
    spans both columns so the row is not half-empty.
    """
    n = len(widgets)
    if n == 0:
        return BoardLayout(cols=1, placements=())
    resolved_cols = cols if cols is not None else 2
    placements: list[BoardPlacement] = []
    for idx, spec in enumerate(widgets):
        row, col = divmod(idx, resolved_cols)
        is_last = idx == n - 1
        orphan = is_last and n % resolved_cols != 0 and resolved_cols > 1
        span = resolved_cols if orphan else 1
        placements.append(BoardPlacement(spec=spec, row=row, col=col, colspan=span))
    return BoardLayout(cols=resolved_cols, placements=tuple(placements))


def _flow_placements(
    widgets: Sequence[WidgetSpec],
    *,
    cols: int = 2,
) -> list[tuple[WidgetSpec, int, int, int]]:
    """Compatibility wrapper around ``plan_board_layout`` for older tests."""
    layout = plan_board_layout(widgets, cols=cols)
    return [(p.spec, p.row, p.col, p.colspan) for p in layout.placements]


def _style_axes(ax: Axes, theme: ChartTheme) -> None:
    ax.tick_params(colors=theme.text, labelsize=7)
    ax.title.set_fontsize(8)
    ax.title.set_color(theme.text)
    for spine in ax.spines.values():
        spine.set_color(theme.spine)


def _clear_children(frame: ctk.CTkFrame) -> None:
    release_mpl_frame_images(frame)
    for child in list(frame.winfo_children()):
        with contextlib.suppress(tk.TclError):
            release_mpl_frame_images(child)
            child.destroy()
    frame._mpl_images = []  # type: ignore[attr-defined]


def _nice_count_step(raw: float, *, min_step: int = COUNT_AXIS_TICK_STEP) -> int:
    """Round ``raw`` up to 1/2/5 × 10^k, never below ``min_step`` (default 5)."""
    step = max(float(raw), float(min_step), 1.0)
    exp = math.floor(math.log10(step))
    base = 10.0**exp
    mantissa = step / base
    if mantissa <= 1.0:
        nice = 1.0
    elif mantissa <= 2.0:
        nice = 2.0
    elif mantissa <= 5.0:
        nice = 5.0
    else:
        nice = 10.0
    return max(int(min_step), int(nice * base))


def count_axis_tick_values(
    max_count: float,
    *,
    step: int = COUNT_AXIS_TICK_STEP,
    max_ticks: int = COUNT_AXIS_MAX_TICKS,
) -> list[int]:
    """Labeled major ticks for series/patient count axes.

    Always uses a consistent major grid (default every 5). The axis top is
    rounded up onto that grid. For large peaks the major step grows on a
    1/2/5 × 10^k scale so ~``max_ticks`` labels cover up to 1e6 patients.
    Unlabeled minors between majors are applied separately via
    ``_set_count_axis_ticks``.
    """
    peak = max(0, int(math.ceil(float(max_count) - 1e-9)))
    base = max(1, int(step))
    if peak <= 0:
        return [0, base]
    # Enough intervals for ≤ max_ticks+1 labels (including 0).
    raw = max(base, math.ceil(peak / max(1, max_ticks)))
    major = _nice_count_step(raw, min_step=base)
    top = max(major, int(math.ceil(peak / major) * major))
    return list(range(0, top + 1, major))


def _set_count_axis_ticks(
    ax: Axes,
    max_count: float,
    *,
    step: int = COUNT_AXIS_TICK_STEP,
    axis: str = "y",
) -> None:
    """Apply labeled majors + unlabeled minors (e.g. 1–4 between 0 and 5)."""
    ticks = count_axis_tick_values(max_count, step=step)
    top = ticks[-1]
    # Five subdivisions per major → four unlabeled ticks (1,2,3,4 when major=5).
    minor = AutoMinorLocator(5)
    if axis == "x":
        ax.set_xlim(0, top)
        ax.set_xticks(ticks)
        ax.xaxis.set_minor_locator(minor)
        ax.tick_params(axis="x", which="minor", labelbottom=False, length=2)
    else:
        ax.set_ylim(0, top)
        ax.set_yticks(ticks)
        ax.yaxis.set_minor_locator(minor)
        ax.tick_params(axis="y", which="minor", labelleft=False, length=2)


def _set_integer_count_ticks(ax: Axes, max_count: float) -> None:
    """Back-compat alias for vertical count axes."""
    _set_count_axis_ticks(ax, max_count, axis="y")


def _chart_title(label: str, count: int) -> str:
    """Shared title pattern for graphical widgets: ``Label · n=N``."""
    return _("{label} · n={count}").format(label=label, count=count)


def build_chart_figure(
    theme: ChartTheme,
    paint: AxesPainter,
    *,
    caption: str = "",
    caption_x: float = 0.5,
    figsize: tuple[float, float] = _CELL_FIGSIZE,
    legend_gutter: bool = False,
) -> Figure:
    """Fixed plot + optional caption band — stable under embed (no tight crop)."""
    fig = Figure(figsize=figsize, dpi=100, layout=None, facecolor=theme.fig)
    fig.patch.set_facecolor(theme.fig)
    left = 0.06 if legend_gutter else 0.14
    right = _DONUT_RIGHT if legend_gutter else 0.96
    if caption:
        gs = GridSpec(
            2,
            1,
            figure=fig,
            height_ratios=[1.0, 0.22],
            hspace=0.08,
            left=left,
            right=right,
            top=0.90,
            bottom=0.06,
        )
        ax = fig.add_subplot(gs[0, 0])
        cap_ax = fig.add_subplot(gs[1, 0])
        cap_ax.set_facecolor(theme.fig)
        cap_ax.set_axis_off()
        cap_ax.text(
            caption_x,
            0.55,
            caption,
            ha="center",
            va="center",
            color=theme.muted,
            fontsize=7,
            transform=cap_ax.transAxes,
        )
    else:
        ax = fig.add_subplot(111)
        fig.subplots_adjust(left=left, right=right, top=0.88, bottom=0.16)
    ax.set_facecolor(theme.fig)
    paint(ax)
    return fig


def _embed_figure(
    frame: ctk.CTkFrame,
    fig: Figure,
    theme: ChartTheme,
    *,
    on_organ_bar_activate: OrganBarActivate | None = None,
) -> None:
    """Rasterize at fixed figure size — do not use bbox_inches='tight' (breaks captions).

    Uses ``ImageTk.PhotoImage`` directly (ImageViewer pattern), not ``CTkImage``.
    CTkImage's scale-cache can drop PhotoImages without dispose on DPI/window resize,
    and those finalizers then crash when GC runs on a DICOM worker thread.
    """
    organ_hit = getattr(fig, "_analytics_organ_hit", None)
    buf = io.BytesIO()
    try:
        fig.savefig(
            buf,
            format="png",
            dpi=100,
            facecolor=theme.fig,
            edgecolor="none",
            transparent=False,
        )
        buf.seek(0)
        pil_image = Image.open(buf).convert("RGBA")
        photo_image = ImageTk.PhotoImage(pil_image)
        label = ctk.CTkLabel(frame, text="", image=photo_image, fg_color="transparent")
        # Expand so the image sits in the cell rather than hugging the left edge.
        label.pack(padx=2, pady=2, expand=True)
        # Strong refs like ImageViewer: widget.image + PhotoImage + PIL.
        label.image = photo_image  # type: ignore[attr-defined]
        refs: list[Any] = getattr(frame, "_mpl_images", [])
        refs.append((label, photo_image, pil_image))
        frame._mpl_images = refs  # type: ignore[attr-defined]
        if isinstance(organ_hit, dict):
            _bind_organ_histogram_interactions(
                label, organ_hit, on_bar_activate=on_organ_bar_activate
            )
    finally:
        plt.close(fig)


def _release_chart_cell(cell: ctk.CTkFrame) -> None:
    """ImageViewer-style teardown: dispose images on main thread, then destroy."""
    release_mpl_frame_images(cell)
    with contextlib.suppress(tk.TclError):
        cell.destroy()


def modality_distinct_count(dist: Distribution) -> int:
    return sum(1 for item in dist.items if item.count > 0)


def _donut(ax: Axes, theme: ChartTheme, dist: Distribution, title: str) -> None:
    labels = [item.label for item in dist.items if item.count > 0]
    sizes = [item.count for item in dist.items if item.count > 0]
    if not sizes:
        return
    colors = [theme.palette[i % len(theme.palette)] for i in range(len(sizes))]
    wedges, _texts = ax.pie(
        sizes,
        colors=colors,
        startangle=90,
        radius=1.0,
        wedgeprops={"width": 0.42, "edgecolor": theme.wedge_edge},
    )
    legend = ax.legend(
        wedges,
        [f"{label} ({count})" for label, count in zip(labels, sizes, strict=False)],
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        fontsize=7,
        frameon=False,
        handlelength=1.0,
        borderaxespad=0.0,
    )
    for text in legend.get_texts():
        text.set_color(theme.text)
    ax.set_title(title, fontsize=8, color=theme.text, pad=4)
    ax.set_aspect("equal")


def _cell_figsize(cell: ctk.CTkFrame) -> tuple[float, float]:
    value = getattr(cell, "_analytics_figsize", None)
    if isinstance(value, tuple) and len(value) == 2:
        return float(value[0]), float(value[1])
    return _CELL_FIGSIZE


def _count_hbar(ax: Axes, theme: ChartTheme, dist: Distribution, title: str) -> None:
    items = [item for item in dist.items if item.count > 0]
    labels = [item.label for item in items]
    values = [float(item.count) for item in items]
    if not values:
        return
    y = range(len(labels))
    ax.barh(list(y), values, color=theme.accent, height=0.6)
    ax.set_yticks(list(y), labels=labels)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel(_("count"), fontsize=7, color=theme.muted)
    _style_axes(ax, theme)
    _set_count_axis_ticks(ax, max(values), axis="x")


def _age_histogram(ax: Axes, theme: ChartTheme, age: AgeHistogram) -> None:
    samples = list(age.samples_years)
    edges = age_histogram_bin_edges(samples)
    counts, _bins, _patches = ax.hist(samples, bins=edges, color=theme.accent, edgecolor=theme.wedge_edge)
    ax.set_xlim(edges[0], edges[-1])
    ax.set_xlabel(_("Age (years)"), fontsize=7, color=theme.muted)
    ax.set_ylabel(_("patients"), fontsize=7, color=theme.muted)
    ax.set_title(_chart_title(_("Age at study"), age.known_total))
    _style_axes(ax, theme)
    _set_count_axis_ticks(ax, max(counts) if len(counts) else 1)


def _organ_histogram(ax: Axes, theme: ChartTheme, organ: OrganVolumeDistribution) -> None:
    samples = list(organ.samples)
    samples_ml = [s.ml for s in samples]
    title = _chart_title(
        _("{organ} volume (ml)").format(organ=organ_display_name(organ.organ_name)),
        organ.patient_count,
    )
    axis_lo, axis_hi, norm_lo, norm_hi, bin_width = organ_volume_axis_span(
        samples_ml, organ_name=organ.organ_name
    )
    edges = organ_volume_bin_edges(samples_ml, organ_name=organ.organ_name)
    # Normative band + two dotted bounds on every organ volume histogram.
    ax.axvspan(norm_lo, norm_hi, color=theme.normative_band, alpha=0.35, zorder=0, lw=0)
    ax.axvline(norm_lo, color=theme.normative_bound, linestyle="--", linewidth=1.0, zorder=3)
    ax.axvline(norm_hi, color=theme.normative_bound, linestyle="--", linewidth=1.0, zorder=3)
    max_count = 1.0
    if samples_ml:
        counts, bin_edges, patches = ax.hist(
            samples_ml,
            bins=edges,
            color=theme.accent,
            edgecolor=theme.wedge_edge,
            zorder=2,
        )
        for patch, left, right in zip(patches, bin_edges[:-1], bin_edges[1:], strict=False):
            mid = 0.5 * (float(left) + float(right))
            if mid < norm_lo or mid > norm_hi:
                patch.set_facecolor(theme.outlier_bar)
        max_count = float(max(counts) if len(counts) else 1)
    ax.set_xlim(edges[0], edges[-1])
    # Clean ml ticks only — do not force-label normative min/max (clutter/overwrite).
    ax.set_xticks(organ_volume_ml_tick_values(axis_lo, axis_hi, bin_width))
    ax.set_xlabel(_("ml"), fontsize=7, color=theme.muted)
    ax.set_ylabel(_("patients"), fontsize=7, color=theme.muted)
    ax.set_title(title)
    _style_axes(ax, theme)
    _set_count_axis_ticks(ax, max_count)
    # Hit-test metadata for bar tooltips / double-click and Norm band tip.
    pos = ax.get_position()
    bins_meta = _organ_bar_bin_hits(samples, edges)
    ax.figure._analytics_organ_hit = {  # type: ignore[attr-defined]
        "organ_name": organ.organ_name,
        "norm_lo": float(norm_lo),
        "norm_hi": float(norm_hi),
        "axis_lo": float(edges[0]),
        "axis_hi": float(edges[-1]),
        "axes_bbox": (float(pos.x0), float(pos.y0), float(pos.x1), float(pos.y1)),
        "norm_tip": _("Norm: [{lo}..{hi}]").format(
            lo=_format_ml_bound(norm_lo),
            hi=_format_ml_bound(norm_hi),
        ),
        "bins": bins_meta,
    }


def _organ_bar_bin_hits(
    samples: Sequence[OrganVolumeSample],
    edges: Sequence[float],
) -> list[dict[str, Any]]:
    """Per-bin tip metadata; patient ids from ``organ_volume_bin_patient_ids``."""
    if len(edges) < 2:
        return []
    id_bins = organ_volume_bin_patient_ids(samples, edges)
    bins: list[dict[str, Any]] = []
    for i, patients in enumerate(id_bins):
        lo = float(edges[i])
        hi = float(edges[i + 1])
        count = len(patients)
        tip = _("{lo}–{hi} ml · n={n}").format(
            lo=_format_ml_bound(lo),
            hi=_format_ml_bound(hi),
            n=count,
        )
        bins.append(
            {
                "lo": lo,
                "hi": hi,
                "count": count,
                "patient_ids": patients,
                "tip": tip,
            }
        )
    return bins


def _format_ml_bound(value: float) -> str:
    """Compact ml label for tooltips (drop useless .0)."""
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:g}"


def _figure_data_x_at(label: tk.Misc, hit: Mapping[str, Any], event: tk.Event) -> float | None:
    """Map a pointer event on an embedded chart label to data-x, or None if outside axes."""
    photo = getattr(label, "image", None)
    if photo is None:
        return None
    try:
        pw = int(photo.width())
        ph = int(photo.height())
        lw = max(int(label.winfo_width()), 1)
        lh = max(int(label.winfo_height()), 1)
    except Exception:
        return None
    if pw <= 0 or ph <= 0:
        return None
    x0 = (lw - pw) / 2.0
    y0 = (lh - ph) / 2.0
    if event.x < x0 or event.x > x0 + pw or event.y < y0 or event.y > y0 + ph:
        return None
    fx = (event.x - x0) / pw
    fy = 1.0 - (event.y - y0) / ph
    ax_x0, ax_y0, ax_x1, ax_y1 = hit["axes_bbox"]
    if not (ax_x0 <= fx <= ax_x1 and ax_y0 <= fy <= ax_y1):
        return None
    axis_lo = float(hit["axis_lo"])
    axis_hi = float(hit["axis_hi"])
    if axis_hi <= axis_lo:
        return None
    return axis_lo + (fx - ax_x0) / (ax_x1 - ax_x0) * (axis_hi - axis_lo)


def _bin_at_data_x(hit: Mapping[str, Any], data_x: float) -> Mapping[str, Any] | None:
    bins = hit.get("bins")
    if not isinstance(bins, list) or not bins:
        return None
    for i, raw in enumerate(bins):
        if not isinstance(raw, dict):
            continue
        lo = float(raw["lo"])
        hi = float(raw["hi"])
        last = i == len(bins) - 1
        if last:
            if lo <= data_x <= hi:
                return raw
        elif lo <= data_x < hi:
            return raw
    return None


def _bind_organ_histogram_interactions(
    label: ctk.CTkLabel,
    hit: Mapping[str, Any],
    *,
    on_bar_activate: OrganBarActivate | None = None,
) -> None:
    """Bar tip (value + n) preferred; Norm tip on empty band; double-click selects patients."""
    label._analytics_organ_hit = hit  # type: ignore[attr-defined]

    def _text_for_position(event: tk.Event) -> str | None:
        return _organ_histogram_tooltip_at(label, event)

    MotionTooltipController(label, _text_for_position, parent=label.winfo_toplevel(), debounce_ms=120).bind()

    if on_bar_activate is None:
        return

    def _on_double_click(event: tk.Event) -> str | None:
        data_x = _figure_data_x_at(label, hit, event)
        if data_x is None:
            return None
        bar = _bin_at_data_x(hit, data_x)
        if bar is None or int(bar.get("count") or 0) <= 0:
            return None
        patient_ids = tuple(str(p) for p in (bar.get("patient_ids") or ()))
        if not patient_ids:
            return None
        on_bar_activate(str(hit.get("organ_name") or ""), patient_ids)
        return "break"

    label.bind("<Double-Button-1>", _on_double_click, add="+")


def _organ_histogram_tooltip_at(label: tk.Misc, event: tk.Event) -> str | None:
    hit = getattr(label, "_analytics_organ_hit", None)
    if not isinstance(hit, dict):
        return None
    data_x = _figure_data_x_at(label, hit, event)
    if data_x is None:
        return None
    bar = _bin_at_data_x(hit, data_x)
    if bar is not None and int(bar.get("count") or 0) > 0:
        return str(bar.get("tip") or "") or None
    if float(hit["norm_lo"]) <= data_x <= float(hit["norm_hi"]):
        return str(hit.get("norm_tip") or "") or None
    return None


# --- Figure builders -----------------------------------------------------------


def build_sex_figure(
    theme: ChartTheme,
    analytics: DatasetAnalytics,
    *,
    figsize: tuple[float, float] = _CELL_FIGSIZE,
) -> Figure:
    sex = analytics.demographics.sex
    return build_chart_figure(
        theme,
        lambda ax: _donut(ax, theme, sex, _chart_title(_("Sex"), sex.known_total)),
        figsize=figsize,
        legend_gutter=True,
    )


def build_age_figure(
    theme: ChartTheme,
    analytics: DatasetAnalytics,
    *,
    figsize: tuple[float, float] = _CELL_FIGSIZE,
) -> Figure:
    return build_chart_figure(
        theme,
        lambda ax: _age_histogram(ax, theme, analytics.demographics.age),
        figsize=figsize,
    )


def build_ethnicity_figure(
    theme: ChartTheme,
    analytics: DatasetAnalytics,
    *,
    figsize: tuple[float, float] = _CELL_FIGSIZE,
) -> Figure:
    ethnicity = analytics.demographics.ethnicity
    return build_chart_figure(
        theme,
        lambda ax: _count_hbar(
            ax, theme, ethnicity, _chart_title(_("Ethnicity"), ethnicity.known_total)
        ),
        figsize=figsize,
    )


def build_modality_figure(
    theme: ChartTheme,
    analytics: DatasetAnalytics,
    *,
    figsize: tuple[float, float] = _CELL_FIGSIZE,
) -> Figure:
    modality = analytics.imaging.modality
    return build_chart_figure(
        theme,
        lambda ax: _donut(ax, theme, modality, _chart_title(_("Modality"), modality.total)),
        figsize=figsize,
        legend_gutter=True,
    )


def build_organ_figure(
    theme: ChartTheme,
    organ: OrganVolumeDistribution,
    *,
    figsize: tuple[float, float] = _CELL_FIGSIZE,
) -> Figure:
    return build_chart_figure(
        theme,
        lambda ax: _organ_histogram(ax, theme, organ),
        figsize=figsize,
    )


# --- Relevance ---------------------------------------------------------------


def _has_known_dist(dist: Distribution) -> bool:
    return dist.known_total > 0 and not dist.empty


def _relevant_sex(analytics: DatasetAnalytics) -> bool:
    return _has_known_dist(analytics.demographics.sex)


def _relevant_age(analytics: DatasetAnalytics) -> bool:
    age = analytics.demographics.age
    return age.known_total > 0 and not age.empty


def _relevant_ethnicity(analytics: DatasetAnalytics) -> bool:
    return _has_known_dist(analytics.demographics.ethnicity)


def _relevant_modality(analytics: DatasetAnalytics) -> bool:
    return modality_distinct_count(analytics.imaging.modality) > 1


def _relevant_ai(analytics: DatasetAnalytics) -> bool:
    dist = analytics.imaging.ai_coverage
    return any(item.count > 0 and round(dist.pct(item.count)) > 0 for item in dist.items)


# --- Painters ----------------------------------------------------------------


def _paint_sex(cell: ctk.CTkFrame, analytics: DatasetAnalytics, theme: ChartTheme) -> None:
    _embed_figure(cell, build_sex_figure(theme, analytics, figsize=_cell_figsize(cell)), theme)


def _paint_age(cell: ctk.CTkFrame, analytics: DatasetAnalytics, theme: ChartTheme) -> None:
    _embed_figure(cell, build_age_figure(theme, analytics, figsize=_cell_figsize(cell)), theme)


def _paint_ethnicity(cell: ctk.CTkFrame, analytics: DatasetAnalytics, theme: ChartTheme) -> None:
    _embed_figure(cell, build_ethnicity_figure(theme, analytics, figsize=_cell_figsize(cell)), theme)


def _paint_modality(cell: ctk.CTkFrame, analytics: DatasetAnalytics, theme: ChartTheme) -> None:
    _embed_figure(cell, build_modality_figure(theme, analytics, figsize=_cell_figsize(cell)), theme)


def _paint_ai_labels(cell: ctk.CTkFrame, analytics: DatasetAnalytics, theme: ChartTheme) -> None:
    dist = analytics.imaging.ai_coverage
    lines = [
        f"{item.label} {round(dist.pct(item.count))}%"
        for item in dist.items
        if item.count > 0 and round(dist.pct(item.count)) > 0
    ]
    if not lines:
        return
    holder = ctk.CTkFrame(cell, fg_color="transparent")
    holder.pack(expand=True, fill="both", padx=_AI_PADX, pady=8)
    ctk.CTkLabel(
        holder,
        text=_("AI COVERAGE"),
        text_color=theme.text,
        anchor="w",
        font=ctk.CTkFont(size=12),
    ).pack(anchor="w", pady=(0, 4))
    for line in lines:
        ctk.CTkLabel(
            holder,
            text=line,
            text_color=theme.accent,
            anchor="w",
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", pady=1)


def _make_organ_painter(
    organ: OrganVolumeDistribution,
    *,
    on_organ_bar_activate: OrganBarActivate | None = None,
) -> WidgetPainter:
    def _paint(cell: ctk.CTkFrame, _analytics: DatasetAnalytics, theme: ChartTheme) -> None:
        _embed_figure(
            cell,
            build_organ_figure(theme, organ, figsize=_cell_figsize(cell)),
            theme,
            on_organ_bar_activate=on_organ_bar_activate,
        )

    return _paint


@dataclass(frozen=True)
class BoardSections:
    """Chart widgets, selected organ histograms, then textual widgets."""

    charts: tuple[WidgetSpec, ...]
    organs: tuple[WidgetSpec, ...]
    texts: tuple[WidgetSpec, ...]

    @property
    def graphical(self) -> tuple[WidgetSpec, ...]:
        """Charts + organs (legacy); prefer ``ordered`` for layout."""
        return self.charts + self.organs

    @property
    def ordered(self) -> tuple[WidgetSpec, ...]:
        """2-col flow: sex, age, modality, volumes…, AI, then other charts.

        Volumes (or AI when none selected) always follow modality so both
        columns fill before wrapping.
        """
        pre = [c for c in self.charts if c.key in {"sex", "age"}]
        modality = [c for c in self.charts if c.key == "modality"]
        post = [c for c in self.charts if c.key not in {"sex", "age", "modality"}]
        return tuple(pre + modality + list(self.organs) + list(self.texts) + post)

    @property
    def all(self) -> tuple[WidgetSpec, ...]:
        return self.ordered


BOARD_WIDGETS: tuple[WidgetSpec, ...] = (
    WidgetSpec(key="sex", relevant=_relevant_sex, paint=_paint_sex),
    WidgetSpec(key="age", relevant=_relevant_age, paint=_paint_age),
    WidgetSpec(key="modality", relevant=_relevant_modality, paint=_paint_modality),
    WidgetSpec(key="ethnicity", relevant=_relevant_ethnicity, paint=_paint_ethnicity),
    WidgetSpec(key="ai", relevant=_relevant_ai, paint=_paint_ai_labels, graphical=False),
)


def select_board_sections(
    analytics: DatasetAnalytics,
    *,
    widgets: Sequence[WidgetSpec] | None = None,
    selected_organs: Sequence[str] | None = None,
    on_organ_bar_activate: OrganBarActivate | None = None,
) -> BoardSections:
    """Relevance filter + organ selection; use ``.ordered`` / ``.all`` for layout."""
    registry = tuple(widgets) if widgets is not None else BOARD_WIDGETS
    charts = tuple(spec for spec in registry if spec.graphical and spec.relevant(analytics))
    texts = tuple(spec for spec in registry if not spec.graphical and spec.relevant(analytics))
    available = analytics.anatomy.organ_volumes
    if selected_organs is None:
        names = set(default_selected_organ_names(available))
    else:
        names = {name for name in selected_organs if name}
    organs = tuple(
        WidgetSpec(
            key=f"organ:{organ.organ_name}",
            relevant=lambda _a: True,
            paint=_make_organ_painter(organ, on_organ_bar_activate=on_organ_bar_activate),
        )
        for organ in available
        if organ.organ_name in names
    )
    return BoardSections(charts=charts, organs=organs, texts=texts)


def select_widgets(
    analytics: DatasetAnalytics,
    *,
    widgets: Sequence[WidgetSpec] | None = None,
    selected_organs: Sequence[str] | None = None,
    on_organ_bar_activate: OrganBarActivate | None = None,
) -> tuple[WidgetSpec, ...]:
    """Ordered board widgets: fill both columns before wrapping to the next row."""
    return select_board_sections(
        analytics,
        widgets=widgets,
        selected_organs=selected_organs,
        on_organ_bar_activate=on_organ_bar_activate,
    ).ordered


def _reset_flow_grid(board: ctk.CTkFrame) -> None:
    """Drop stale row/col minsizes so a shorter layout can shrink."""
    cols, rows = board.grid_size()
    for r in range(max(rows, 1)):
        board.grid_rowconfigure(r, weight=0, minsize=0, pad=0)
    for c in range(max(cols, 1)):
        board.grid_columnconfigure(c, weight=0, minsize=0, pad=0)


def _configure_flow_grid(board: ctk.CTkFrame, cols: int, rows: int) -> None:
    _reset_flow_grid(board)
    # Rows size to content — weight 0 avoids huge empty vertical gaps.
    for r in range(max(1, rows)):
        board.grid_rowconfigure(r, weight=0, minsize=0)
    for c in range(cols):
        board.grid_columnconfigure(c, weight=1, uniform="analytics_col")


def _render_placement(
    board: ctk.CTkFrame,
    layout: BoardLayout,
    placement: BoardPlacement,
    analytics: DatasetAnalytics,
    theme: ChartTheme,
) -> ctk.CTkFrame:
    cell = ctk.CTkFrame(board, fg_color="transparent")
    cell.grid(
        row=placement.row,
        column=placement.col,
        columnspan=placement.colspan,
        sticky="nsew",
        padx=6,
        pady=6,
    )
    cell._analytics_key = placement.spec.key  # type: ignore[attr-defined]
    cell._analytics_figsize = layout.figsize_for(placement)  # type: ignore[attr-defined]
    logger.info(
        "Analytics charts: widget %s at (%d,%d) span=%d",
        placement.spec.key,
        placement.row,
        placement.col,
        placement.colspan,
    )
    try:
        placement.spec.paint(cell, analytics, theme)
    except Exception:
        logger.exception("Failed to render analytics widget %s", placement.spec.key)
        ctk.CTkLabel(cell, text=_("Chart unavailable"), text_color=theme.muted).pack(expand=True, padx=8, pady=8)
    return cell


def _repaint_cell(
    cell: ctk.CTkFrame,
    placement: BoardPlacement,
    analytics: DatasetAnalytics,
    theme: ChartTheme,
    figsize: tuple[float, float],
) -> None:
    _clear_children(cell)
    cell._analytics_figsize = figsize  # type: ignore[attr-defined]
    try:
        placement.spec.paint(cell, analytics, theme)
    except Exception:
        logger.exception("Failed to re-paint analytics widget %s", placement.spec.key)
        ctk.CTkLabel(cell, text=_("Chart unavailable"), text_color=theme.muted).pack(expand=True, padx=8, pady=8)


def render_widget_section(
    host: ctk.CTkFrame,
    widgets: Sequence[WidgetSpec],
    analytics: DatasetAnalytics,
    theme: ChartTheme | None = None,
) -> BoardLayout:
    """Fill ``host`` with a 2-col flow of ``widgets`` (clears host first)."""
    resolved = theme or load_chart_theme()
    _clear_children(host)
    _reset_flow_grid(host)
    host._analytics_cells = {}  # type: ignore[attr-defined]
    layout = plan_board_layout(widgets)
    if not widgets:
        return layout
    _configure_flow_grid(host, layout.cols, layout.rows)
    cells: dict[str, ctk.CTkFrame] = {}
    for placement in layout.placements:
        cells[placement.spec.key] = _render_placement(host, layout, placement, analytics, resolved)
    host._analytics_cells = cells  # type: ignore[attr-defined]
    return layout


def sync_widget_section(
    host: ctk.CTkFrame,
    widgets: Sequence[WidgetSpec],
    analytics: DatasetAnalytics,
    theme: ChartTheme | None = None,
) -> BoardLayout:
    """Update the 2-col flow in place — reuse unchanged cells (no full-board flicker).

    Added widgets are painted; removed widgets are destroyed; surviving widgets are
    only re-gridded (and re-painted when their figsize/span changes).
    """
    resolved = theme or load_chart_theme()
    layout = plan_board_layout(widgets)
    cells: dict[str, ctk.CTkFrame] = dict(getattr(host, "_analytics_cells", {}) or {})

    wanted_keys = {p.spec.key for p in layout.placements}
    for key, cell in list(cells.items()):
        if key not in wanted_keys:
            with contextlib.suppress(tk.TclError):
                _release_chart_cell(cell)
            del cells[key]

    _reset_flow_grid(host)
    if not widgets:
        host._analytics_cells = {}  # type: ignore[attr-defined]
        return layout

    _configure_flow_grid(host, layout.cols, layout.rows)
    for placement in layout.placements:
        key = placement.spec.key
        figsize = layout.figsize_for(placement)
        cell = cells.get(key)
        if cell is None or not cell.winfo_exists():
            cells[key] = _render_placement(host, layout, placement, analytics, resolved)
            continue
        cell.grid(
            row=placement.row,
            column=placement.col,
            columnspan=placement.colspan,
            sticky="nsew",
            padx=6,
            pady=6,
        )
        prev = getattr(cell, "_analytics_figsize", None)
        if prev != figsize:
            _repaint_cell(cell, placement, analytics, resolved, figsize)
        else:
            cell._analytics_figsize = figsize  # type: ignore[attr-defined]

    host._analytics_cells = cells  # type: ignore[attr-defined]
    logger.info(
        "Analytics charts: sync complete widgets=%s",
        [p.spec.key for p in layout.placements],
    )
    return layout


def resolve_board_theme(board: ctk.CTkFrame) -> ChartTheme:
    theme = load_chart_theme()
    with contextlib.suppress(Exception):
        board_fg = board.cget("fg_color")
        safe = _mpl_figure_facecolor(board_fg, fallback=theme.fig)
        theme = replace(theme, fig=safe, wedge_edge=safe)
    return theme


def render_analytics_board(
    board: ctk.CTkFrame,
    analytics: DatasetAnalytics,
    *,
    widgets: Sequence[WidgetSpec] | None = None,
    selected_organs: Sequence[str] | None = None,
    on_organ_bar_activate: OrganBarActivate | None = None,
) -> BoardLayout:
    """Fill ``board`` via ``plan_board_layout``; returns the layout used."""
    theme = resolve_board_theme(board)
    active = select_widgets(
        analytics,
        widgets=widgets,
        selected_organs=selected_organs,
        on_organ_bar_activate=on_organ_bar_activate,
    )
    layout = plan_board_layout(active)
    logger.info(
        "Analytics charts: render start sex_n=%s modality_n=%s widgets=%s",
        analytics.demographics.sex.total,
        analytics.imaging.modality.total,
        [w.key for w in active],
    )
    _clear_children(board)
    if not active:
        ctk.CTkLabel(
            board,
            text=_("No analytics available"),
            text_color=theme.muted,
            wraplength=520,
            justify="center",
        ).pack(expand=True, padx=12, pady=24)
        return layout

    _configure_flow_grid(board, layout.cols, layout.rows)
    for placement in layout.placements:
        _render_placement(board, layout, placement, analytics, theme)
    logger.info(
        "Analytics charts: render complete (%d widgets, %d cols, %d rows)",
        len(active),
        layout.cols,
        layout.rows,
    )
    return layout


def render_analytics_placeholder(board: ctk.CTkFrame, message: str) -> None:
    theme = load_chart_theme()
    _clear_children(board)
    ctk.CTkLabel(board, text=message, text_color=theme.muted, wraplength=520, justify="center").pack(
        expand=True, padx=12, pady=24
    )
