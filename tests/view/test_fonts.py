"""Tests for centralized view font helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.view.common import fonts as fonts_module
from anonymizer.view.common.fonts import (
    AppFonts,
    canvas_label_font,
    char_width_px,
    create_app_fonts,
    default_char_width_px,
    theme_font_family,
    theme_font_size,
)


def test_theme_font_family_returns_non_empty_string() -> None:
    family = theme_font_family()
    assert isinstance(family, str)
    assert family


def test_theme_font_size_returns_int() -> None:
    assert isinstance(theme_font_size(), int)
    assert theme_font_size(default=13) >= 1


def test_canvas_label_font_is_tuple() -> None:
    font = canvas_label_font(10)
    assert font == (theme_font_family(), 10)


def test_default_char_width_px_uses_cached_font() -> None:
    fonts_module._default_ui_font = None
    mock_font = MagicMock()
    mock_font.measure.return_value = 8
    with patch("anonymizer.view.common.fonts.ctk.CTkFont", return_value=mock_font):
        first = default_char_width_px()
        second = default_char_width_px()
    assert first == 8
    assert first == second
    assert fonts_module._default_ui_font is mock_font


def test_char_width_px_delegates_to_font_measure() -> None:
    font = MagicMock()
    font.measure.return_value = 9
    assert char_width_px(font) == 9
    font.measure.assert_called_once_with("A")


def test_create_app_fonts_returns_frozen_dataclass() -> None:
    mock_font = MagicMock()
    with patch("anonymizer.view.common.fonts.ctk.CTkFont", return_value=mock_font):
        fonts = create_app_fonts()
    assert isinstance(fonts, AppFonts)
    assert fonts.mono is mock_font
    assert fonts.mono_large is mock_font
    assert fonts.small is mock_font
    assert fonts.bold is mock_font
    assert fonts.heading is mock_font
    assert fonts.title is mock_font
    assert fonts.label_large is mock_font


def test_histogram_uses_canvas_tuple_font() -> None:
    axis_font = canvas_label_font(10)
    assert isinstance(axis_font, tuple)
    assert axis_font[0]
    assert axis_font[1] == 10
