"""Visible-frame crop math and HWND parsing for Windows DWM window grabs."""

from PIL import Image

from docs_help.platform.common import normalize_for_docs
from docs_help.platform.windows import _hwnd_from_winfo_id, crop_box_for_visible_frame


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


def test_hwnd_from_winfo_id_accepts_int_hex_and_bytes() -> None:
    assert _hwnd_from_winfo_id(0x790638) == 0x790638
    assert _hwnd_from_winfo_id("0x790638") == 0x790638
    assert _hwnd_from_winfo_id(b"8\x06y\x00\x00\x00\x00\x00") == 0x790638


def test_normalize_for_docs_letterbox_rgb_is_white() -> None:
    """Shared normalize: RGB stays RGB with white side pads (macOS path)."""
    src = Image.new("RGB", (400, 120), (200, 200, 200))
    out = normalize_for_docs(src)
    assert out.size == (960, 120)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (255, 255, 255)
    x = (960 - 400) // 2
    assert out.getpixel((x, 60)) == (200, 200, 200)


def test_normalize_for_docs_letterbox_rgba_is_transparent() -> None:
    """Shared normalize: RGBA letterbox matches macOS screencapture."""
    src = Image.new("RGBA", (400, 120), (200, 200, 200, 255))
    out = normalize_for_docs(src)
    assert out.size == (960, 120)
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0
    x = (960 - 400) // 2
    assert out.getpixel((x, 60))[:3] == (200, 200, 200)
    assert out.getpixel((x, 60))[3] == 255


def test_normalize_for_docs_rgb_and_rgba_share_960_canvas() -> None:
    rgb = Image.new("RGB", (730, 992), (200, 200, 200))
    rgba = Image.new("RGBA", (730, 992), (200, 200, 200, 255))
    out_rgb = normalize_for_docs(rgb)
    out_rgba = normalize_for_docs(rgba)
    assert out_rgb.size == (960, 992)
    assert out_rgba.size == (960, 992)
    x = (960 - 730) // 2
    assert out_rgb.getpixel((x, 40)) == (200, 200, 200)
    assert out_rgba.getpixel((x, 40))[:3] == (200, 200, 200)


def test_normalize_for_docs_downscales_wide_shots() -> None:
    src = Image.new("RGB", (1920, 400), (180, 180, 180))
    out = normalize_for_docs(src)
    assert out.size == (960, 200)
