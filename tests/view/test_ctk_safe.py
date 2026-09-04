"""Tests for CustomTkinter scaling tracker safety helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.view.common.ctk_safe import (
    dispose_photo_image,
    install_safe_scaling_tracker,
    install_safe_tk_font_destructor,
    mark_ctk_window_destroyed,
    pause_scaling_tracker_check,
    resume_scaling_tracker_check,
    teardown_ctk_toplevel,
)


def test_install_safe_scaling_tracker_replaces_check_once() -> None:
    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    original = ScalingTracker.check_dpi_scaling
    install_safe_scaling_tracker()
    assert ScalingTracker.check_dpi_scaling is not original
    install_safe_scaling_tracker()
    assert ScalingTracker.check_dpi_scaling is not original


def test_mark_destroyed_skips_window_in_safe_check() -> None:
    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    install_safe_scaling_tracker()
    window = MagicMock()
    window._anonymizer_ctk_alive = True
    window.winfo_exists.return_value = True
    window.state.return_value = "normal"
    ScalingTracker.window_widgets_dict[window] = []
    ScalingTracker.window_dpi_scaling_dict[window] = 1.0

    mark_ctk_window_destroyed(window)

    assert window not in ScalingTracker.window_widgets_dict
    window.state.assert_not_called()


def test_safe_scaling_check_schedules_only_on_main_root() -> None:
    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    install_safe_scaling_tracker()
    stale = MagicMock()
    stale._anonymizer_ctk_alive = False
    stale.winfo_exists.return_value = False
    main_root = MagicMock()
    type(main_root).__name__ = "CTk"
    main_root.winfo_exists.return_value = True
    main_root.state.return_value = "normal"

    ScalingTracker.window_widgets_dict.clear()
    ScalingTracker.window_dpi_scaling_dict.clear()
    ScalingTracker.window_widgets_dict[stale] = []
    ScalingTracker.window_widgets_dict[main_root] = []
    ScalingTracker.window_dpi_scaling_dict[main_root] = 1.0
    ScalingTracker.update_loop_running = True

    ScalingTracker.check_dpi_scaling()

    stale.after.assert_not_called()
    main_root.after.assert_called_once()


def test_safe_scaling_check_skips_work_while_paused() -> None:
    from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

    install_safe_scaling_tracker()
    main_root = MagicMock()
    type(main_root).__name__ = "CTk"
    main_root.winfo_exists.return_value = True
    main_root.state.return_value = "normal"

    ScalingTracker.window_widgets_dict.clear()
    ScalingTracker.window_dpi_scaling_dict.clear()
    ScalingTracker.window_widgets_dict[main_root] = [MagicMock()]
    ScalingTracker.window_dpi_scaling_dict[main_root] = 1.0
    ScalingTracker.update_loop_running = True

    pause_scaling_tracker_check()
    try:
        ScalingTracker.check_dpi_scaling()
    finally:
        resume_scaling_tracker_check()

    main_root.block_update_dimensions_event.assert_not_called()
    main_root.after.assert_called_once()


def test_dispose_photo_image_deletes_tk_image() -> None:
    widget = MagicMock()
    widget.winfo_exists.return_value = True
    photo = MagicMock()
    photo.name = "pyimage42"

    dispose_photo_image(widget, photo)

    widget.tk.call.assert_called_once_with("image", "delete", "pyimage42")


def test_install_safe_tk_font_destructor_skips_delete_off_main_thread() -> None:
    import tkinter.font as tkfont

    install_safe_tk_font_destructor()
    font = MagicMock()
    font.delete_font = True
    font.name = "TkFontMock0"
    font._tk = MagicMock()

    worker = MagicMock()
    with patch("anonymizer.view.common.ctk_safe.threading.current_thread", return_value=worker):
        with patch("anonymizer.view.common.ctk_safe._tk_scheduling_anchor", return_value=None):
            tkfont.Font.__del__(font)

    font._call.assert_not_called()


def test_install_safe_tk_font_destructor_deletes_on_main_thread() -> None:
    import tkinter.font as tkfont

    install_safe_tk_font_destructor()
    font = MagicMock()
    font.delete_font = True
    font.name = "TkFontMock1"
    font._call = MagicMock()

    tkfont.Font.__del__(font)

    font._call.assert_called_once_with("font", "delete", "TkFontMock1")


def test_teardown_ctk_toplevel_destroys_and_schedules_gc() -> None:
    window = MagicMock()
    parent = MagicMock()
    with patch("anonymizer.view.common.ctk_safe.mark_ctk_window_destroyed") as mark_destroyed:
        with patch("anonymizer.utils.memory.schedule_collect_garbage_on_tk") as schedule_gc:
            teardown_ctk_toplevel(window, parent=parent)
    mark_destroyed.assert_called_once_with(window)
    window.destroy.assert_called_once()
    schedule_gc.assert_called_once_with(parent)


def test_font_gc_off_main_thread_does_not_call_tcl_directly() -> None:
    import threading
    import tkinter.font as tkfont

    install_safe_tk_font_destructor()
    font = MagicMock()
    font.delete_font = True
    font.name = "TkFontMockWorker"
    font._tk = MagicMock()
    worker = MagicMock()

    def collect_off_thread() -> None:
        with patch("anonymizer.view.common.ctk_safe.threading.current_thread", return_value=worker):
            with patch("anonymizer.view.common.ctk_safe._tk_scheduling_anchor", return_value=None):
                tkfont.Font.__del__(font)

    thread = threading.Thread(target=collect_off_thread)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    font._call.assert_not_called()
