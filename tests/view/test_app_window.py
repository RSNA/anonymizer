"""Tests for shared app menubar bases and Window menu registry."""

from __future__ import annotations

import contextlib
import sys
import tkinter as tk
import weakref

import pytest

from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import (
    AppToplevel,
    attach_menubar_to_toplevels,
    find_app_menu_host,
    focus_app_window,
    refresh_app_window_menu,
    window_menu_label_for,
)


class _MenuHost(tk.Tk):
    """Minimal stand-in for Anonymizer window-menu hosting."""

    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.menu_bar = tk.Menu(self)
        self._window_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Window", menu=self._window_menu)
        self.config(menu=self.menu_bar)
        self._app_windows: list[weakref.ref] = []

    def _live_app_windows(self) -> list[tk.Misc]:
        live: list[tk.Misc] = []
        surviving: list[weakref.ref] = []
        for ref in self._app_windows:
            window = ref()
            if window is None:
                continue
            try:
                if not window.winfo_exists():
                    continue
            except tk.TclError:
                continue
            live.append(window)
            surviving.append(ref)
        self._app_windows = surviving
        return live

    def register_app_window(self, window: tk.Misc) -> None:
        for existing in self._live_app_windows():
            if existing is window:
                if attach_menubar_to_toplevels():
                    window.configure(menu=self.menu_bar)
                self.refresh_window_menu()
                return
        self._app_windows.append(weakref.ref(window))
        if attach_menubar_to_toplevels():
            window.configure(menu=self.menu_bar)
        self.refresh_window_menu()

    def unregister_app_window(self, window: tk.Misc) -> None:
        self._app_windows = [ref for ref in self._app_windows if ref() is not None and ref() is not window]
        self.refresh_window_menu()

    def refresh_window_menu(self) -> None:
        end = self._window_menu.index("end")
        if end is not None:
            self._window_menu.delete(0, end)
        self._window_menu.add_command(label=_("Dashboard"), command=lambda: None)
        for window in self._live_app_windows():
            self._window_menu.add_command(
                label=window_menu_label_for(window),
                command=lambda win=window: focus_app_window(win),
            )


@pytest.fixture
def menu_host():
    host = _MenuHost()
    yield host
    with contextlib.suppress(tk.TclError):
        host.destroy()


def test_attach_menubar_to_toplevels_matches_platform() -> None:
    assert attach_menubar_to_toplevels() is (sys.platform == "darwin")


def test_find_app_menu_host_walks_master_chain(menu_host: _MenuHost) -> None:
    child = tk.Toplevel(menu_host)
    try:
        assert find_app_menu_host(child) is menu_host
    finally:
        child.destroy()


def test_window_menu_label_prefers_title_and_override(menu_host: _MenuHost) -> None:
    child = tk.Toplevel(menu_host)
    try:
        child.title("View Dataset")
        assert window_menu_label_for(child) == "View Dataset"
        child.window_menu_label = "Dataset"  # type: ignore[attr-defined]
        assert window_menu_label_for(child) == "Dataset"
    finally:
        child.destroy()


def test_app_toplevel_registers_and_lists_in_window_menu(menu_host: _MenuHost) -> None:
    win_a = AppToplevel(menu_host)
    win_a.title("Alpha")
    win_b = AppToplevel(menu_host)
    win_b.title("Beta")
    menu_host.update_idletasks()
    # after_idle callbacks
    menu_host.update()

    labels = [menu_host._window_menu.entrycget(i, "label") for i in range(menu_host._window_menu.index("end") + 1)]
    assert _("Dashboard") in labels
    assert "Alpha" in labels
    assert "Beta" in labels
    if attach_menubar_to_toplevels():
        assert win_a.cget("menu") == str(menu_host.menu_bar)
    else:
        assert not str(win_a.cget("menu") or "").strip()

    win_a.destroy()
    menu_host.update()
    labels_after = [
        menu_host._window_menu.entrycget(i, "label") for i in range(menu_host._window_menu.index("end") + 1)
    ]
    assert "Alpha" not in labels_after
    assert "Beta" in labels_after

    win_b.destroy()
    menu_host.update()


def test_refresh_app_window_menu_updates_label_after_title_change(menu_host: _MenuHost) -> None:
    win = AppToplevel(menu_host)
    win.title("Series View")
    menu_host.update()
    labels = [menu_host._window_menu.entrycget(i, "label") for i in range(menu_host._window_menu.index("end") + 1)]
    assert "Series View" in labels

    win.title("Series View for Doe^Jane PHI ID:P1")
    refresh_app_window_menu(win)
    labels = [menu_host._window_menu.entrycget(i, "label") for i in range(menu_host._window_menu.index("end") + 1)]
    assert "Series View for Doe^Jane PHI ID:P1" in labels
    assert labels.count("Series View") == 0

    win.destroy()
    menu_host.update()
