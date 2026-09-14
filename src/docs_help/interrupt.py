"""Ctrl+C must terminate help capture immediately.

Python's SIGINT handler only raises ``KeyboardInterrupt`` on the main thread,
and then capture ``finally`` blocks try to shut down pynetdicom / Tk / Harmonize
workers — which hang. On Windows, TotalSegmentator/torch in C also delay SIGINT
until the native call returns.

A console control handler calls ``os._exit`` from a dedicated Windows thread so
Ctrl+C kills the process even while nnUNet or EasyOCR is in native code.
"""

from __future__ import annotations

import logging
import os
import signal
import sys

logger = logging.getLogger(__name__)

INTERRUPT_EXIT_CODE = 130
_CTRL_HANDLER_REF = None


def hard_exit(code: int = INTERRUPT_EXIT_CODE) -> None:
    """Skip ``finally`` / Tk / SCP shutdown and kill every thread."""
    try:
        sys.stderr.write("\nInterrupted.\n")
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


def install_hard_interrupt() -> None:
    """Make Ctrl+C / Ctrl+Break terminate capture instead of hanging in teardown."""
    signal.signal(signal.SIGINT, lambda _s, _f: hard_exit())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda _s, _f: hard_exit())
    if sys.platform == "win32":
        _install_windows_console_handler()


def _install_windows_console_handler() -> None:
    """``SetConsoleCtrlHandler`` runs on a Windows thread; ``os._exit`` from there
    is not blocked by torch/nnUNet on the main thread."""
    global _CTRL_HANDLER_REF
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    CTRL_C_EVENT = 0
    CTRL_BREAK_EVENT = 1

    def _console_ctrl(ctrl_type: int) -> int:
        if ctrl_type in (CTRL_C_EVENT, CTRL_BREAK_EVENT):
            hard_exit()
        return 0

    _CTRL_HANDLER_REF = HandlerRoutine(_console_ctrl)
    if not kernel32.SetConsoleCtrlHandler(_CTRL_HANDLER_REF, True):
        logger.warning("SetConsoleCtrlHandler failed: %s", ctypes.get_last_error())
