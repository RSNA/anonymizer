"""Windows-only window capture via Win32 PrintWindow / BitBlt, with ImageGrab fallback.

Importing this module on non-Windows hosts is safe; Win32 APIs load lazily.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from PIL import Image

from docs_help.platform.common import capture_bbox_imagegrab, is_blank_capture

logger = logging.getLogger(__name__)


def _find_hwnd(widget: Any) -> int | None:
    """Resolve the Win32 HWND for a Tk/CTk toplevel when possible."""
    if sys.platform != "win32":
        return None
    try:
        from ctypes import windll
        from ctypes.wintypes import HWND

        widget.update_idletasks()
        wid = int(widget.winfo_id())
        user32 = windll.user32
        hwnd = HWND(wid)
        parent = user32.GetParent(hwnd)
        root = hwnd
        while parent:
            root = parent
            parent = user32.GetParent(root)
        return int(root) if root else int(hwnd)
    except Exception as exc:
        logger.debug("HWND resolve failed: %s", exc)
        return None


def _capture_hwnd(hwnd: int) -> Image.Image | None:
    """Capture a window client/frame via PrintWindow into a PIL image."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import byref, sizeof, windll
    from ctypes.wintypes import HWND, RECT

    user32 = windll.user32
    gdi32 = windll.gdi32

    rect = RECT()
    if not user32.GetWindowRect(HWND(hwnd), byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 8 or height < 8:
        return None

    hwnd_dc = user32.GetWindowDC(HWND(hwnd))
    if not hwnd_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bmp)

    # PW_RENDERFULLCONTENT = 0x00000002 (Win8.1+) — better for DWM/composited windows.
    PW_RENDERFULLCONTENT = 0x00000002
    ok = user32.PrintWindow(HWND(hwnd), mem_dc, PW_RENDERFULLCONTENT)
    if not ok:
        ok = user32.PrintWindow(HWND(hwnd), mem_dc, 0)
    if not ok:
        gdi32.BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, 0, 0, 0x00CC0020)  # SRCCOPY

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

    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(HWND(hwnd), hwnd_dc)

    image = Image.frombuffer("RGB", (width, height), bytes(buf), "raw", "BGRX", 0, 1)
    if is_blank_capture(image):
        return None
    return image


def capture_window(widget: Any, dest: Any, label: str) -> Image.Image | None:
    """Capture a Tk/CTk window on Windows via PrintWindow when possible."""
    hwnd = _find_hwnd(widget)
    if hwnd is None:
        return None
    try:
        image = _capture_hwnd(hwnd)
        if image is None:
            return None
        logger.info("Grab %s via PrintWindow hwnd=%s size=%s → %s", label, hwnd, image.size, dest)
        return image
    except Exception as exc:
        logger.warning("Windows window capture failed for %s: %s", label, exc)
        return None


def capture_bbox(bbox: tuple[int, int, int, int], dest_hint: Any = None) -> Image.Image:
    """Windows bbox grab via ImageGrab."""
    del dest_hint
    return capture_bbox_imagegrab(bbox)
