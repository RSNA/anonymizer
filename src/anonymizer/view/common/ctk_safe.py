"""CustomTkinter safety helpers for Tk 9.0 on macOS (stale scaling tracker windows)."""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk

logger = logging.getLogger(__name__)

_PATCH_INSTALLED = False


def mark_ctk_window_alive(window: tk.Misc) -> None:
    window._anonymizer_ctk_alive = True  # type: ignore[attr-defined]


def mark_ctk_window_destroyed(window: tk.Misc) -> None:
    window._anonymizer_ctk_alive = False  # type: ignore[attr-defined]
    unregister_customtkinter_window(window)


def dispose_photo_image(widget: tk.Misc, photo_image) -> None:
    """Release a Tk PhotoImage on the main thread (avoids bus errors when GC runs elsewhere)."""
    if photo_image is None:
        return
    name = getattr(photo_image, "name", None)
    if not name:
        return
    master = widget
    with contextlib.suppress(tk.TclError):
        if not master.winfo_exists():
            master = master.winfo_toplevel()
    with contextlib.suppress(tk.TclError):
        master.tk.call("image", "delete", name)


def release_ctk_label_image(label: tk.Misc) -> None:
    """Clear a CTkLabel image reference before widget teardown."""
    with contextlib.suppress(Exception):
        label.configure(image=None)


def unregister_customtkinter_window(window: tk.Misc) -> None:
    with contextlib.suppress(Exception):
        from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

        ScalingTracker.remove_window(None, window)
        ScalingTracker.window_dpi_scaling_dict.pop(window, None)


def _is_main_ctk_root(window: tk.Misc) -> bool:
    return isinstance(window, tk.Tk) or type(window).__name__ == "CTk"


def install_safe_scaling_tracker() -> None:
    """Skip destroyed CTk toplevels in ScalingTracker.check_dpi_scaling (avoids Tk 9 segfaults)."""
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    @classmethod
    def safe_check_dpi_scaling(cls) -> None:
        for window in list(cls.window_widgets_dict.keys()):
            if _is_main_ctk_root(window):
                continue
            if getattr(window, "_anonymizer_ctk_alive", None) is False:
                cls.remove_window(None, window)
                cls.window_dpi_scaling_dict.pop(window, None)

        new_scaling_detected = False
        for window in list(cls.window_widgets_dict.keys()):
            if not getattr(window, "_anonymizer_ctk_alive", _is_main_ctk_root(window)):
                continue
            try:
                if not window.winfo_exists():
                    cls.remove_window(None, window)
                    cls.window_dpi_scaling_dict.pop(window, None)
                    continue
                current_dpi_scaling_value = cls.get_window_dpi_scaling(window)
            except tk.TclError:
                cls.remove_window(None, window)
                cls.window_dpi_scaling_dict.pop(window, None)
                continue

            if current_dpi_scaling_value != cls.window_dpi_scaling_dict.get(window):
                cls.window_dpi_scaling_dict[window] = current_dpi_scaling_value
                import sys

                if sys.platform.startswith("win"):
                    window.attributes("-alpha", 0.15)

                window.block_update_dimensions_event()
                cls.update_scaling_callbacks_for_window(window)
                window.unblock_update_dimensions_event()

                if sys.platform.startswith("win"):
                    window.attributes("-alpha", 1)

                new_scaling_detected = True

        for app in cls.window_widgets_dict:
            try:
                if new_scaling_detected:
                    app.after(cls.loop_pause_after_new_scaling, cls.check_dpi_scaling)
                else:
                    app.after(cls.update_loop_interval, cls.check_dpi_scaling)
                return
            except Exception:
                continue

        cls.update_loop_running = False

    ScalingTracker.check_dpi_scaling = safe_check_dpi_scaling
    _PATCH_INSTALLED = True
    logger.debug("Installed safe CustomTkinter scaling tracker")
