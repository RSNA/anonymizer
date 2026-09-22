"""Tooltip theme styling and analytics scroll granularity."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import customtkinter as ctk
import pytest

from anonymizer.view.common.tooltip import tooltip_style
from anonymizer.view.shell.analytics_charts import (
    ANALYTICS_SCROLL_STEP_PX,
    _event_targets_analytics_scroll,
    _wheel_notches,
    configure_granular_scroll,
)

_THEME_PATH = Path(__file__).resolve().parents[2] / "src" / "anonymizer" / "assets" / "themes" / "rsna_theme.json"


@pytest.fixture(scope="module", autouse=True)
def _load_rsna_theme() -> None:
    ctk.set_default_color_theme(str(_THEME_PATH))


def test_tooltip_style_reads_theme_section() -> None:
    theme = ctk.ThemeManager.theme.get("Tooltip")
    assert isinstance(theme, dict)
    assert "fg_color" in theme and "text_color" in theme
    style = tooltip_style()
    assert style["bg"]
    assert style["fg"]
    assert style["border"]
    assert style["padx"] >= 1
    assert style["wraplength"] >= 100
    # Must not use the old hardcoded dark-gray / white pair as the only path.
    assert style["bg"] != "#333333"


def test_wheel_notches_are_bounded() -> None:
    assert _wheel_notches(0) == 0
    # Aqua Tk 8–style ±1 (no widget → darwin ±1 boost to 3 notches).
    small = _wheel_notches(1)
    assert small in (-3, -2, -1, 1, 2, 3)
    large = _wheel_notches(50)
    assert abs(large) <= 3
    assert large == -abs(large)  # positive delta → scroll up (negative notches)


def test_event_targets_scroll_walks_masters() -> None:
    canvas = object()
    scroll = SimpleNamespace(_parent_canvas=canvas)
    child = SimpleNamespace(master=scroll)
    grandchild = SimpleNamespace(master=child)
    outsider = SimpleNamespace(master=SimpleNamespace(master=None))
    assert _event_targets_analytics_scroll(scroll, canvas)
    assert _event_targets_analytics_scroll(scroll, scroll)
    assert _event_targets_analytics_scroll(scroll, grandchild)
    assert not _event_targets_analytics_scroll(scroll, outsider)
    assert not _event_targets_analytics_scroll(scroll, type("CTkScrollbar", (), {"master": None})())


def test_configure_granular_scroll_sets_pixel_increment() -> None:
    calls: list[tuple] = []
    binds: list[tuple] = []

    class _Canvas:
        def configure(self, **kwargs):
            calls.append(("configure", kwargs))

        def yview(self, *args):
            calls.append(("yview", args))
            return (0.0, 0.5)

        def yview_scroll(self, *args):
            calls.append(("yview_scroll", args))

    canvas = _Canvas()

    # Mimic Aqua Tk 8 (Python 3.14) so wheel boost is exercised.
    class _FakeTk:
        def call(self, *args: object) -> str:
            if args == ("tk", "windowingsystem"):
                return "aqua"
            if args == ("info", "patchlevel"):
                return "8.6.14"
            raise RuntimeError(args)

    scroll = SimpleNamespace(
        _parent_canvas=canvas,
        _scrollbar=None,
        tk=_FakeTk(),
        _check_if_valid_scroll=lambda _w: True,
        bind_all=lambda seq, fn, add=None: binds.append((seq, fn, add)),
    )
    # Chart label under the scroll inner frame (typical hover target).
    chart_label = SimpleNamespace(master=scroll)

    configure_granular_scroll(scroll, step_px=ANALYTICS_SCROLL_STEP_PX)
    assert any(c[0] == "configure" and c[1].get("yscrollincrement") == 1 for c in calls)
    assert callable(getattr(scroll, "_mouse_wheel_all", None))
    # CTk's captured handler is neutered; our handler is bind_all'd.
    assert scroll._check_if_valid_scroll(object()) is False
    assert any(seq == "<MouseWheel>" for seq, _fn, _add in binds)
    scroll._mouse_wheel_all(SimpleNamespace(widget=chart_label, delta=1))
    scroll_calls = [c for c in calls if c[0] == "yview_scroll"]
    assert scroll_calls
    # Tk 8 Aqua: 3 notches × step_px units.
    assert scroll_calls[-1][1] == (-3 * ANALYTICS_SCROLL_STEP_PX, "units")
    # Outside the board — no scroll.
    n = len(scroll_calls)
    scroll._mouse_wheel_all(SimpleNamespace(widget=SimpleNamespace(master=None), delta=1))
    assert len([c for c in calls if c[0] == "yview_scroll"]) == n
    # Idempotent — second call must not stack another bind_all.
    n_binds = len(binds)
    configure_granular_scroll(scroll, step_px=ANALYTICS_SCROLL_STEP_PX)
    assert len(binds) == n_binds
