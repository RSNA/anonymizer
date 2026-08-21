"""Shared Toplevel bases: attach Anonymizer menubar and register for the Window menu."""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any, Protocol

import customtkinter as ctk

from anonymizer.view.common.ctk_safe import mark_ctk_window_alive

logger = logging.getLogger(__name__)


class AppMenuHost(Protocol):
    menu_bar: tk.Menu | None

    def register_app_window(self, window: tk.Misc) -> None: ...

    def unregister_app_window(self, window: tk.Misc) -> None: ...


def find_app_menu_host(widget: tk.Misc) -> AppMenuHost | None:
    """Walk the master chain to the Anonymizer root that owns the shared menubar."""
    current: tk.Misc | None = widget
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if callable(getattr(current, "register_app_window", None)) and callable(
            getattr(current, "unregister_app_window", None)
        ):
            return current  # type: ignore[return-value]
        nxt = getattr(current, "master", None)
        if nxt is None or nxt is current:
            break
        current = nxt
    return None


def window_menu_label_for(window: tk.Misc) -> str:
    override = getattr(window, "window_menu_label", None)
    if callable(override):
        text = str(override()).strip()
        if text:
            return text
    elif isinstance(override, str) and override.strip():
        return override.strip()
    try:
        title = str(window.title()).strip()
    except tk.TclError:
        title = ""
    if title:
        return title
    return window.__class__.__name__


def focus_app_window(window: tk.Misc) -> None:
    try:
        if not window.winfo_exists():
            return
        window.deiconify()
        window.lift()
        window.focus_force()
    except tk.TclError:
        logger.debug("focus_app_window failed for %s", window, exc_info=True)


def refresh_app_window_menu(window: tk.Misc) -> None:
    """Rebuild the Window menu so labels pick up a newly set ``title()``."""
    host = getattr(window, "_app_menu_host", None) or find_app_menu_host(window)
    refresh = getattr(host, "refresh_window_menu", None)
    if not callable(refresh):
        return
    try:
        refresh()
    except Exception:
        logger.debug("refresh_window_menu failed for %s", window, exc_info=True)


def _install_app_window(window: tk.Misc) -> None:
    mark_ctk_window_alive(window)
    window.bind("<Destroy>", lambda event, w=window: _on_app_window_destroy(event, w), add="+")
    # Title is usually set by the subclass after super().__init__; defer registration.
    window.after_idle(lambda: _finish_app_window_setup(window))


def _finish_app_window_setup(window: tk.Misc) -> None:
    try:
        if not window.winfo_exists():
            return
    except tk.TclError:
        return

    if getattr(window, "_app_window_registered", False):
        return

    host = find_app_menu_host(window) or getattr(window, "_app_menu_host", None)
    if host is None:
        logger.debug("No app menu host for %s", window)
        return
    window._app_menu_host = host  # type: ignore[attr-defined]

    menu_bar = getattr(host, "menu_bar", None)
    if menu_bar is not None:
        try:
            window.configure(menu=menu_bar)
        except tk.TclError:
            logger.debug("Could not attach menu_bar to %s", window, exc_info=True)

    try:
        host.register_app_window(window)
        window._app_window_registered = True  # type: ignore[attr-defined]
    except Exception:
        logger.debug("register_app_window failed for %s", window, exc_info=True)


def _on_app_window_destroy(event: tk.Event, window: tk.Misc) -> None:
    if event.widget is not window:
        return
    if not getattr(window, "_app_window_registered", False):
        return
    host = getattr(window, "_app_menu_host", None) or find_app_menu_host(window)
    window._app_window_registered = False  # type: ignore[attr-defined]
    if host is None:
        return
    try:
        host.unregister_app_window(window)
    except Exception:
        logger.debug("unregister_app_window failed for %s", window, exc_info=True)


class AppToplevel(tk.Toplevel):
    """Toplevel that shares the Anonymizer menubar and appears under Window."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        host = find_app_menu_host(self)
        if host is not None:
            self._app_menu_host = host
        _install_app_window(self)


class AppCTkToplevel(ctk.CTkToplevel):
    """CTkToplevel that shares the Anonymizer menubar and appears under Window."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        host = find_app_menu_host(self)
        if host is not None:
            self._app_menu_host = host
        _install_app_window(self)
