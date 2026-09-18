"""Tooltip theme styling and analytics scroll granularity."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import customtkinter as ctk
import pytest

from anonymizer.view.common.tooltip import tooltip_style
from anonymizer.view.shell.analytics_charts import (
    ANALYTICS_SCROLL_STEP_PX,
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
    small = _wheel_notches(1)
    assert small in (-1, 1)
    large = _wheel_notches(50)
    assert abs(large) <= 3
    assert large == -abs(large)  # positive delta → scroll up (negative notches)


def test_configure_granular_scroll_sets_pixel_increment() -> None:
    calls: list[tuple] = []

    class _Canvas:
        def configure(self, **kwargs):
            calls.append(("configure", kwargs))

        def yview(self, *args):
            calls.append(("yview", args))
            return (0.0, 0.5)

        def yview_scroll(self, *args):
            calls.append(("yview_scroll", args))

    canvas = _Canvas()
    scroll = SimpleNamespace(
        _parent_canvas=canvas,
        _scrollbar=None,
        check_if_master_is_canvas=lambda _w: True,
    )
    configure_granular_scroll(scroll, step_px=ANALYTICS_SCROLL_STEP_PX)
    assert any(c[0] == "configure" and c[1].get("yscrollincrement") == 1 for c in calls)
    assert callable(getattr(scroll, "_mouse_wheel_all", None))
    scroll._mouse_wheel_all(SimpleNamespace(widget=object(), delta=1))
    assert any(c[0] == "yview_scroll" for c in calls)
