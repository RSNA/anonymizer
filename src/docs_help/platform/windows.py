"""Windows-only window capture via PrintWindow, with ImageGrab fallback.

Importing this module on non-Windows hosts is safe; Win32 APIs load lazily.

PrintWindow copies ``GetWindowRect``, which on Vista+ includes an *invisible*
resize/shadow margin filled with opaque black. macOS ``screencapture -l -o``
never includes that margin. Docs grabs crop that bitmap to
``DWMWA_EXTENDED_FRAME_BOUNDS`` so the PNG is the window chrome only — not a
screen BitBlt of the DWM rect, which would include desktop pixels around
rounded corners (white in Cursor, black on a dark desktop).
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from typing import Any, Iterator

from PIL import Image

from docs_help.platform.common import capture_bbox_imagegrab, is_blank_capture

logger = logging.getLogger(__name__)

# DwmGetWindowAttribute: on-screen window box without the invisible resize margin.
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_SRCCOPY = 0x00CC0020
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Win10 1703+).
_DPI_PER_MONITOR_V2 = -4


def _hwnd_from_winfo_id(wid: Any) -> int:
    """Tk ``winfo_id()`` may be an int, decimal/hex str, or raw HWND bytes."""
    if isinstance(wid, int):
        return wid
    if isinstance(wid, (bytes, bytearray, memoryview)):
        raw = bytes(wid)
        if not raw:
            raise ValueError("empty HWND bytes")
        return int.from_bytes(raw, "little")
    text = str(wid).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    try:
        return int(text, 10)
    except ValueError:
        return int(text, 16)


def _find_hwnd(widget: Any) -> int | None:
    """Resolve the Win32 HWND for a Tk/CTk toplevel when possible.

    Walk only ``WS_CHILD`` parents up to the owning top-level window. Do **not**
    follow ``GetParent`` into window *owners* — on Windows that collapses every
    ``transient`` dialog (Harmonize, brain prompt) onto Series View / the app
    root, so stacked grabs become duplicate overlapping Series Views.
    """
    if sys.platform != "win32":
        return None
    try:
        from ctypes import windll
        from ctypes.wintypes import HWND

        widget.update_idletasks()
        current = _hwnd_from_winfo_id(widget.winfo_id())
        user32 = windll.user32
        GWL_STYLE = -16
        WS_CHILD = 0x40000000
        get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        while current:
            style = int(get_style(HWND(current), GWL_STYLE))
            if not (style & WS_CHILD):
                break
            parent = int(user32.GetParent(HWND(current)) or 0)
            if not parent or parent == current:
                break
            current = parent
        return current or None
    except Exception as exc:
        logger.debug("HWND resolve failed: %s", exc)
        return None


def crop_box_for_visible_frame(
    window: tuple[int, int, int, int],
    visible: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    """Map a DWM visible rect onto a ``GetWindowRect`` bitmap (left, top, right, bottom).

    Returns ``None`` when the rects are not in the same coordinate space (typical
    DPI-unaware vs DWM physical mismatch) or the visible box would be empty.
    """
    wl, wt, wr, wb = window
    vl, vt, vr, vb = visible
    left = vl - wl
    top = vt - wt
    right_inset = wr - vr
    bottom_inset = wb - vb
    if min(left, top, right_inset, bottom_inset) < 0:
        return None
    width = wr - wl
    height = wb - wt
    box = (left, top, width - right_inset, height - bottom_inset)
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    return box


@contextmanager
def _per_monitor_dpi() -> Iterator[None]:
    """Query window rects and blit in physical pixels (same space as DWM)."""
    if sys.platform != "win32":
        yield
        return
    import ctypes
    from ctypes import windll

    set_ctx = getattr(windll.user32, "SetThreadDpiAwarenessContext", None)
    if set_ctx is None:
        yield
        return
    prev = set_ctx(ctypes.c_void_p(_DPI_PER_MONITOR_V2))
    try:
        yield
    finally:
        if prev:
            set_ctx(ctypes.c_void_p(int(prev)))


def _rect_tuple(rect: Any) -> tuple[int, int, int, int]:
    return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))


def _window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    from ctypes import byref, windll
    from ctypes.wintypes import HWND, RECT

    rect = RECT()
    if not windll.user32.GetWindowRect(HWND(hwnd), byref(rect)):
        return None
    box = _rect_tuple(rect)
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    return box


def _dwm_visible_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    from ctypes import byref, sizeof, windll
    from ctypes.wintypes import HWND, RECT

    frame = RECT()
    hr = windll.dwmapi.DwmGetWindowAttribute(
        HWND(hwnd),
        _DWMWA_EXTENDED_FRAME_BOUNDS,
        byref(frame),
        sizeof(frame),
    )
    if hr != 0:
        return None
    box = _rect_tuple(frame)
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    return box


def _hbitmap_to_image(gdi32: Any, mem_dc: int, bmp: int, width: int, height: int) -> Image.Image:
    import ctypes
    from ctypes import byref, sizeof

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32),
            ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = sizeof(BITMAPINFOHEADER)
    bmi.biWidth = width
    bmi.biHeight = -height  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf_len = width * height * 4
    buf = (ctypes.c_ubyte * buf_len)()
    gdi32.GetDIBits(mem_dc, bmp, 0, height, byref(buf), byref(bmi), 0)
    # RGBA so shared normalize_for_docs letterboxes like macOS screencapture.
    return Image.frombuffer("RGB", (width, height), bytes(buf), "raw", "BGRX", 0, 1).convert(
        "RGBA"
    )


def _bitblt_screen(bounds: tuple[int, int, int, int]) -> Image.Image | None:
    """Copy on-screen pixels of ``bounds`` (left, top, right, bottom)."""
    from ctypes import windll
    from ctypes.wintypes import HWND

    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    if width < 8 or height < 8:
        return None
    user32 = windll.user32
    gdi32 = windll.gdi32
    screen_dc = user32.GetDC(HWND(0))
    if not screen_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bmp)
    try:
        ok = gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, left, top, _SRCCOPY)
        if not ok:
            return None
        image = _hbitmap_to_image(gdi32, mem_dc, bmp, width, height)
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(HWND(0), screen_dc)
    if is_blank_capture(image):
        return None
    return image


def _printwindow_bitmap(hwnd: int, window: tuple[int, int, int, int]) -> Image.Image | None:
    """Render the full ``GetWindowRect`` window into a bitmap (includes DWM margin)."""
    from ctypes import windll
    from ctypes.wintypes import HWND

    width = window[2] - window[0]
    height = window[3] - window[1]
    user32 = windll.user32
    gdi32 = windll.gdi32
    hwnd_dc = user32.GetWindowDC(HWND(hwnd))
    if not hwnd_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bmp)
    try:
        # PW_RENDERFULLCONTENT = 0x00000002 (Win8.1+) — better for DWM/composited windows.
        PW_RENDERFULLCONTENT = 0x00000002
        ok = user32.PrintWindow(HWND(hwnd), mem_dc, PW_RENDERFULLCONTENT)
        if not ok:
            ok = user32.PrintWindow(HWND(hwnd), mem_dc, 0)
        if not ok:
            gdi32.BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, 0, 0, _SRCCOPY)
        image = _hbitmap_to_image(gdi32, mem_dc, bmp, width, height)
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(HWND(hwnd), hwnd_dc)
    if is_blank_capture(image):
        return None
    return image


def _capture_hwnd(hwnd: int) -> Image.Image | None:
    """Capture the window's own pixels (no desktop around rounded corners).

    PrintWindow renders the HWND; ``GetWindowRect`` is larger than the visible
    DWM frame, so the bitmap is cropped with that geometry (not an edge trim).
    Screen BitBlt is last-resort only — it copies whatever is behind the window
    (white Cursor canvas, wallpaper) into the PNG.
    """
    if sys.platform != "win32":
        return None

    with _per_monitor_dpi():
        window = _window_rect(hwnd)
        visible = _dwm_visible_rect(hwnd)
        if window is None:
            return None

        image = _printwindow_bitmap(hwnd, window)
        if image is not None and visible is not None:
            crop = crop_box_for_visible_frame(window, visible)
            if crop is not None and crop != (0, 0, image.size[0], image.size[1]):
                image = image.crop(crop)
        if image is not None and not is_blank_capture(image):
            return image

        target = visible or window
        image = _bitblt_screen(target)
        if image is not None:
            logger.warning("Win32 hwnd=%s fell back to screen BitBlt size=%s", hwnd, image.size)
            return image
        return None


def capture_window(widget: Any, dest: Any, label: str) -> Image.Image | None:
    """Capture a Tk/CTk window on Windows via PrintWindow cropped to the DWM frame."""
    hwnd = _find_hwnd(widget)
    if hwnd is None:
        return None
    try:
        image = _capture_hwnd(hwnd)
        if image is None:
            return None
        logger.info("Grab %s via Win32 hwnd=%s size=%s → %s", label, hwnd, image.size, dest)
        return image
    except Exception as exc:
        logger.warning("Windows window capture failed for %s: %s", label, exc)
        return None


def capture_bbox(bbox: tuple[int, int, int, int], dest_hint: Any = None) -> Image.Image:
    """Windows bbox grab via ImageGrab."""
    del dest_hint
    return capture_bbox_imagegrab(bbox)


def capture_screen(dest_hint: Any = None) -> Image.Image | None:
    """Full-screen grab via ImageGrab."""
    from PIL import ImageGrab

    del dest_hint
    return ImageGrab.grab()
