"""Pointer and wheel helpers that stay stable across Tk versions.

On macOS Aqua with Tk 8.x, physical middle and right clicks are reported as
Tk buttons 3 and 2 (swapped vs X11). Tk 9 Aqua and all X11/Win32 builds use
the X11 numbering (middle=2, right=3). Series View binds pan to middle and
window/level to right — without this mapping those roles swap when the
interpreter ships Tk 8.6 (e.g. uv Python 3.13/3.14) vs Tk 9 (e.g. 3.12).

MouseWheel ``event.delta`` also differs: Win32 uses multiples of 120; classic
Aqua Tk 8 usually reports ±1 per notch; Aqua Tk 9 / high-res trackpads can
report larger magnitudes for the same gesture. Normalize to notch counts so
analytics (and other) scroll speed stays consistent across Python builds.
"""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass


@dataclass(frozen=True)
class PointerButtons:
    """Tk button numbers for physical middle and right clicks."""

    middle: int
    right: int

    @property
    def pan_press(self) -> str:
        return f"<ButtonPress-{self.middle}>"

    @property
    def pan_motion(self) -> str:
        return f"<B{self.middle}-Motion>"

    @property
    def pan_release(self) -> str:
        return f"<ButtonRelease-{self.middle}>"

    @property
    def pan_double(self) -> str:
        return f"<Double-Button-{self.middle}>"

    @property
    def right_press(self) -> str:
        return f"<ButtonPress-{self.right}>"

    @property
    def right_motion(self) -> str:
        return f"<B{self.right}-Motion>"

    @property
    def right_release(self) -> str:
        return f"<ButtonRelease-{self.right}>"


def _tk_major_version(widget: tk.Misc) -> int:
    patchlevel = str(widget.tk.call("info", "patchlevel"))
    major = patchlevel.split(".", 1)[0]
    try:
        return int(major)
    except ValueError:
        return 8


def _windowing_system(widget: tk.Misc) -> str:
    try:
        return str(widget.tk.call("tk", "windowingsystem"))
    except tk.TclError:
        return ""


def aqua_middle_right_swapped(widget: tk.Misc) -> bool:
    """True when Aqua reports middle/right as Tk buttons 3/2."""
    return _windowing_system(widget) == "aqua" and _tk_major_version(widget) < 9


def pointer_buttons(widget: tk.Misc) -> PointerButtons:
    """Return middle/right Tk button numbers for ``widget``'s Tk runtime."""
    if aqua_middle_right_swapped(widget):
        return PointerButtons(middle=3, right=2)
    return PointerButtons(middle=2, right=3)


def mouse_wheel_notches(delta: int, widget: tk.Misc | None = None) -> int:
    """Map a MouseWheel ``delta`` to a signed notch count (±1…3).

    * Win32 (and any |delta| ≥ 120): classic 120-unit notches.
    * Aqua Tk 8 (Python 3.13/3.14 on macOS): delta is usually ±1 — boost to
      three notches so scroll speed matches Aqua Tk 9 / Python 3.12 feel.
    * Aqua Tk 9 / X11: dampen large trackpad bursts (cap at 3).
    """
    if not delta:
        return 0

    if sys.platform.startswith("win") or abs(int(delta)) >= 120:
        notches = -int(delta / 120)
        if notches == 0:
            notches = -1 if delta > 0 else 1
        return max(-3, min(3, notches))

    aqua_tk8 = False
    if widget is not None:
        aqua_tk8 = _windowing_system(widget) == "aqua" and _tk_major_version(widget) < 9
    elif sys.platform == "darwin":
        # No widget (unit tests / early init): assume classic Aqua ±1 reporting.
        aqua_tk8 = abs(int(delta)) == 1

    if aqua_tk8:
        # One physical notch → three logical notches (matches Tk 9 dampen cap).
        return -3 if delta > 0 else 3

    magnitude = min(3, max(1, abs(int(delta))))
    return -magnitude if delta > 0 else magnitude
