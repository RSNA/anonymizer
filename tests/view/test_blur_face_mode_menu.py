"""Tests for Series View face blur mode menu helpers."""

from __future__ import annotations

from anonymizer.controller.blur_face import FaceBlurMode
from anonymizer.view.blur_face_results import (
    face_blur_mode_display_label,
    face_blur_mode_from_menu_label,
    face_blur_mode_menu_values,
)


def test_face_blur_mode_menu_round_trip() -> None:
    values = face_blur_mode_menu_values()
    assert len(values) == len(FaceBlurMode)
    for mode in FaceBlurMode:
        label = face_blur_mode_display_label(mode)
        assert label in values
        assert face_blur_mode_from_menu_label(label) is mode
