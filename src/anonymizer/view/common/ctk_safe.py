"""CustomTkinter safety helpers for Tk 9.0 on macOS (stale scaling tracker windows)."""

from __future__ import annotations

import contextlib
import logging
import threading
import tkinter as tk

logger = logging.getLogger(__name__)

_PATCH_INSTALLED = False
_FONT_DEL_PATCHED = False
_scaling_check_paused = False


def mark_ctk_window_alive(window: tk.Misc) -> None:
    window._anonymizer_ctk_alive = True  # type: ignore[attr-defined]


def mark_ctk_window_destroyed(window: tk.Misc) -> None:
    window._anonymizer_ctk_alive = False  # type: ignore[attr-defined]
    unregister_customtkinter_window(window)


def dispose_photo_image(widget: tk.Misc, photo_image) -> None:
    """Release a Tk PhotoImage on the main thread (avoids bus errors when GC runs elsewhere)."""
    if photo_image is None:
        return
    if threading.current_thread() is not threading.main_thread():
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


def pause_scaling_tracker_check() -> None:
    """Pause DPI scaling callbacks while main-window geometry is being changed."""
    global _scaling_check_paused
    _scaling_check_paused = True


def resume_scaling_tracker_check() -> None:
    global _scaling_check_paused
    _scaling_check_paused = False


def purge_stale_scaling_windows() -> None:
    """Drop destroyed CTk windows from CustomTkinter's scaling tracker."""
    with contextlib.suppress(Exception):
        from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

        _prune_stale_scaling_windows(ScalingTracker)


def _is_main_ctk_root(window: tk.Misc) -> bool:
    return isinstance(window, tk.Tk) or type(window).__name__ == "CTk"


def _window_visible_for_scaling(window: tk.Misc) -> bool:
    with contextlib.suppress(tk.TclError):
        return bool(window.winfo_exists()) and str(window.state()) != "iconic"
    return False


def _prune_stale_scaling_windows(scaling_tracker) -> None:
    for window in list(scaling_tracker.window_widgets_dict.keys()):
        if _is_main_ctk_root(window):
            continue
        if getattr(window, "_anonymizer_ctk_alive", None) is False:
            scaling_tracker.remove_window(None, window)
            scaling_tracker.window_dpi_scaling_dict.pop(window, None)
            continue
        if not _window_visible_for_scaling(window):
            scaling_tracker.remove_window(None, window)
            scaling_tracker.window_dpi_scaling_dict.pop(window, None)


def _scaling_loop_anchor(scaling_tracker) -> tk.Misc | None:
    """Pick a stable main CTk root for scheduling the scaling poll loop."""
    for window in list(scaling_tracker.window_widgets_dict.keys()):
        if _is_main_ctk_root(window) and _window_visible_for_scaling(window):
            return window
    for window in list(scaling_tracker.window_widgets_dict.keys()):
        if getattr(window, "_anonymizer_ctk_alive", True) and _window_visible_for_scaling(window):
            return window
    return None


def _schedule_scaling_check(scaling_tracker, *, new_scaling_detected: bool) -> None:
    anchor = _scaling_loop_anchor(scaling_tracker)
    if anchor is None:
        scaling_tracker.update_loop_running = False
        return
    delay = (
        scaling_tracker.loop_pause_after_new_scaling
        if new_scaling_detected
        else scaling_tracker.update_loop_interval
    )
    with contextlib.suppress(tk.TclError):
        anchor.after(delay, scaling_tracker.check_dpi_scaling)
        scaling_tracker.update_loop_running = True
        return
    scaling_tracker.update_loop_running = False


def _tk_scheduling_anchor() -> tk.Misc | None:
    """Return a live Tk widget suitable for scheduling main-thread cleanup."""
    root = tk._default_root
    if root is not None:
        with contextlib.suppress(tk.TclError):
            if root.winfo_exists():
                return root

    with contextlib.suppress(Exception):
        from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

        return _scaling_loop_anchor(ScalingTracker)
    return None


def teardown_ctk_toplevel(
    window: tk.Misc,
    *,
    parent: tk.Misc | None = None,
) -> None:
    """Unified Toplevel close: unregister scaling, destroy, schedule GC."""
    from anonymizer.utils.memory import schedule_collect_garbage_on_tk

    mark_ctk_window_destroyed(window)
    with contextlib.suppress(tk.TclError):
        window.grab_release()
    with contextlib.suppress(tk.TclError):
        window.destroy()
    gc_parent = parent if parent is not None else window
    schedule_collect_garbage_on_tk(gc_parent)


def install_safe_tk_font_destructor() -> None:
    """Avoid bus errors when Font/CTkFont objects are GC'd off the main thread."""
    global _FONT_DEL_PATCHED
    if _FONT_DEL_PATCHED:
        return

    import tkinter.font as tkfont

    def _safe_font_del(self) -> None:
        try:
            if not self.delete_font:
                return
            if threading.current_thread() is threading.main_thread():
                self._call("font", "delete", self.name)
                return
            # Off-main-thread: scheduling via after_idle can bus-error when
            # the finaliser runs during GC (Tk is not re-entrant).
            # Let the font leak — count is bounded per session.
            self.delete_font = False
        except Exception:
            pass

    tkfont.Font.__del__ = _safe_font_del
    _FONT_DEL_PATCHED = True
    logger.debug("Installed safe tkinter Font destructor")


def install_safe_scaling_tracker() -> None:
    """Skip destroyed CTk toplevels in ScalingTracker.check_dpi_scaling (avoids Tk 9 segfaults)."""
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    @classmethod
    def safe_check_dpi_scaling(cls) -> None:
        _prune_stale_scaling_windows(cls)

        if _scaling_check_paused:
            _schedule_scaling_check(cls, new_scaling_detected=False)
            return

        new_scaling_detected = False
        for window in list(cls.window_widgets_dict.keys()):
            if not getattr(window, "_anonymizer_ctk_alive", _is_main_ctk_root(window)):
                continue
            if not _window_visible_for_scaling(window):
                continue
            try:
                current_dpi_scaling_value = cls.get_window_dpi_scaling(window)
            except tk.TclError:
                cls.remove_window(None, window)
                cls.window_dpi_scaling_dict.pop(window, None)
                continue

            if current_dpi_scaling_value != cls.window_dpi_scaling_dict.get(window):
                cls.window_dpi_scaling_dict[window] = current_dpi_scaling_value
                import sys

                if sys.platform.startswith("win"):
                    with contextlib.suppress(tk.TclError):
                        window.attributes("-alpha", 0.15)

                with contextlib.suppress(tk.TclError, AttributeError):
                    window.block_update_dimensions_event()
                    cls.update_scaling_callbacks_for_window(window)
                    window.unblock_update_dimensions_event()

                if sys.platform.startswith("win"):
                    with contextlib.suppress(tk.TclError):
                        window.attributes("-alpha", 1)

                new_scaling_detected = True

        _schedule_scaling_check(cls, new_scaling_detected=new_scaling_detected)

    ScalingTracker.check_dpi_scaling = safe_check_dpi_scaling
    _PATCH_INSTALLED = True
    logger.debug("Installed safe CustomTkinter scaling tracker")
