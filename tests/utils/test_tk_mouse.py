"""Tests for logical mouse-button and wheel mapping across Tk Aqua / X11."""

from __future__ import annotations

from types import SimpleNamespace

from anonymizer.utils.tk_mouse import (
    PointerButtons,
    aqua_middle_right_swapped,
    mouse_wheel_notches,
    pointer_buttons,
)


class _FakeTk:
    def __init__(self, *, windowing: str, patchlevel: str) -> None:
        self._windowing = windowing
        self._patchlevel = patchlevel

    def call(self, *args: object) -> str:
        if args == ("tk", "windowingsystem"):
            return self._windowing
        if args == ("info", "patchlevel"):
            return self._patchlevel
        raise RuntimeError(f"unexpected tk call: {args}")


def _widget(*, windowing: str, patchlevel: str) -> SimpleNamespace:
    return SimpleNamespace(tk=_FakeTk(windowing=windowing, patchlevel=patchlevel))


def test_pointer_buttons_x11_standard() -> None:
    ptr = pointer_buttons(_widget(windowing="x11", patchlevel="8.6.14"))
    assert ptr == PointerButtons(middle=2, right=3)
    assert not aqua_middle_right_swapped(_widget(windowing="x11", patchlevel="8.6.14"))


def test_pointer_buttons_win32_standard() -> None:
    ptr = pointer_buttons(_widget(windowing="win32", patchlevel="8.6.14"))
    assert ptr == PointerButtons(middle=2, right=3)


def test_pointer_buttons_aqua_tk8_swapped() -> None:
    """uv Python 3.13/3.14 on macOS currently ships Tk 8.6 Aqua."""
    ptr = pointer_buttons(_widget(windowing="aqua", patchlevel="8.6.14"))
    assert aqua_middle_right_swapped(_widget(windowing="aqua", patchlevel="8.6.14"))
    assert ptr == PointerButtons(middle=3, right=2)
    assert ptr.pan_press == "<ButtonPress-3>"
    assert ptr.right_press == "<ButtonPress-2>"
    assert ptr.pan_motion == "<B3-Motion>"
    assert ptr.right_motion == "<B2-Motion>"


def test_pointer_buttons_aqua_tk9_standard() -> None:
    """uv/pyenv Python 3.12 on macOS currently ships Tk 9 Aqua."""
    ptr = pointer_buttons(_widget(windowing="aqua", patchlevel="9.0.2"))
    assert not aqua_middle_right_swapped(_widget(windowing="aqua", patchlevel="9.0.2"))
    assert ptr == PointerButtons(middle=2, right=3)
    assert ptr.pan_press == "<ButtonPress-2>"
    assert ptr.right_press == "<ButtonPress-3>"


def test_mouse_wheel_notches_win32_style() -> None:
    assert mouse_wheel_notches(0) == 0
    assert mouse_wheel_notches(120) == -1
    assert mouse_wheel_notches(-240) == 2
    assert abs(mouse_wheel_notches(1200)) <= 3


def test_mouse_wheel_notches_aqua_tk8_boosted() -> None:
    """Tk 8 Aqua ±1 → three notches so scroll matches Tk 9 feel (Python 3.13/3.14)."""
    w = _widget(windowing="aqua", patchlevel="8.6.14")
    assert mouse_wheel_notches(1, w) == -3
    assert mouse_wheel_notches(-1, w) == 3


def test_mouse_wheel_notches_aqua_tk9_damped() -> None:
    w = _widget(windowing="aqua", patchlevel="9.0.2")
    assert mouse_wheel_notches(1, w) == -1
    assert abs(mouse_wheel_notches(50, w)) <= 3
    assert mouse_wheel_notches(50, w) == -abs(mouse_wheel_notches(50, w))
