"""Tests for welcome window sizing constants and guard tolerance."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

from anonymizer.view.welcome import WelcomeView


def test_welcome_window_width_fits_wraplength() -> None:
    assert WelcomeView.WELCOME_WINDOW_WIDTH >= WelcomeView.WELCOME_TEXT_WRAP_LENGTH + WelcomeView.PAD * 2


def test_welcome_window_needs_reapply_when_current_width_drifted() -> None:
    from anonymizer.anonymizer import Anonymizer

    root = tk.Tk()
    root.withdraw()
    app = Anonymizer.__new__(Anonymizer)
    app.welcome_size_tolerance = Anonymizer.welcome_size_tolerance
    app.welcome_view = MagicMock()
    app.welcome_view.winfo_exists.return_value = True
    app.welcome_view.winfo_reqwidth.return_value = WelcomeView.WELCOME_WINDOW_WIDTH
    app.welcome_view.winfo_reqheight.return_value = WelcomeView.WELCOME_WINDOW_HEIGHT
    app.welcome_view.update_idletasks = MagicMock()
    app._current_width = 120
    app._reverse_window_scaling = lambda value: value
    app.winfo_width = MagicMock(return_value=120)
    try:
        assert app._welcome_window_needs_reapply() is True
        app._current_width = WelcomeView.WELCOME_WINDOW_WIDTH
        app.winfo_width.return_value = WelcomeView.WELCOME_WINDOW_WIDTH
        assert app._welcome_window_needs_reapply() is False
    finally:
        root.destroy()


def test_project_window_target_size_uses_dashboard_not_welcome_width() -> None:
    from anonymizer.anonymizer import Anonymizer

    root = tk.Tk()
    root.withdraw()
    app = Anonymizer.__new__(Anonymizer)
    app.project_window_min_width = Anonymizer.project_window_min_width
    app.project_window_min_height = Anonymizer.project_window_min_height
    app._welcome_window_locked = False
    app._reverse_window_scaling = lambda value: value
    app.update_idletasks = MagicMock()
    app.dashboard = MagicMock()
    app.dashboard.winfo_exists.return_value = True
    app.dashboard.winfo_reqwidth.return_value = 860
    app.dashboard.winfo_reqheight.return_value = 280
    try:
        width, height = app._project_window_target_size()
        assert width >= Anonymizer.project_window_min_width
        assert width > WelcomeView.WELCOME_WINDOW_WIDTH
        assert height < WelcomeView.WELCOME_WINDOW_HEIGHT
    finally:
        root.destroy()
