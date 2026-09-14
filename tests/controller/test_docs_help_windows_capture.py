"""Visible-frame crop math for Windows DWM window grabs."""

from docs_help.platform.windows import crop_box_for_visible_frame


def test_crop_box_typical_dwm_resize_margin() -> None:
    """GetWindowRect is 7px larger on left/right/bottom; top matches the caption."""
    window = (100, 80, 600, 480)
    visible = (107, 80, 593, 473)
    assert crop_box_for_visible_frame(window, visible) == (7, 0, 493, 393)


def test_crop_box_identity_when_rects_match() -> None:
    window = (10, 20, 110, 220)
    assert crop_box_for_visible_frame(window, window) == (0, 0, 100, 200)


def test_crop_box_rejects_dpi_mismatch() -> None:
    """DWM physical rect larger than a DPI-virtualized GetWindowRect."""
    window = (0, 0, 100, 100)
    visible = (0, 0, 125, 125)
    assert crop_box_for_visible_frame(window, visible) is None


def test_crop_box_rejects_empty_visible() -> None:
    window = (0, 0, 500, 400)
    visible = (0, 0, 4, 4)
    assert crop_box_for_visible_frame(window, visible) is None
