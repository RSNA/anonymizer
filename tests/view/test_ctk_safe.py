"""Tests for CustomTkinter scaling tracker safety helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from anonymizer.view.common.ctk_safe import dispose_photo_image, install_safe_scaling_tracker, mark_ctk_window_destroyed


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
    ScalingTracker.window_widgets_dict[window] = []
    ScalingTracker.window_dpi_scaling_dict[window] = 1.0

    mark_ctk_window_destroyed(window)

    assert window not in ScalingTracker.window_widgets_dict
    window.state.assert_not_called()


def test_dispose_photo_image_deletes_tk_image() -> None:
    widget = MagicMock()
    widget.winfo_exists.return_value = True
    photo = MagicMock()
    photo.name = "pyimage42"

    dispose_photo_image(widget, photo)

    widget.tk.call.assert_called_once_with("image", "delete", "pyimage42")
