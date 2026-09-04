"""macOS CGWindow helpers for alpha-preserving window captures."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SWIFT_SRC = Path(__file__).with_name("list_cg_windows.swift")
_HELPER_CACHE = Path(tempfile.gettempdir()) / "anonymizer_list_cg_windows"


def _ensure_helper() -> Path:
    """Compile the Swift window-list helper once into a temp binary."""
    if _HELPER_CACHE.exists() and _HELPER_CACHE.stat().st_mtime >= _SWIFT_SRC.stat().st_mtime:
        return _HELPER_CACHE
    if not _SWIFT_SRC.exists():
        raise FileNotFoundError(_SWIFT_SRC)
    logger.info("Compiling macOS window-list helper → %s", _HELPER_CACHE)
    subprocess.run(
        ["swiftc", "-O", "-o", str(_HELPER_CACHE), str(_SWIFT_SRC)],
        check=True,
        capture_output=True,
        text=True,
    )
    return _HELPER_CACHE


def list_cg_windows() -> list[dict[str, Any]]:
    helper = _ensure_helper()
    proc = subprocess.run([str(helper)], check=True, capture_output=True, text=True)
    return json.loads(proc.stdout or "[]")


def _overlap_area(
    ax1: float, ay1: float, ax2: float, ay2: float, bx1: float, by1: float, bx2: float, by2: float
) -> float:
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def resolve_cg_window_id(widget: Any, *, pid: int | None = None) -> int | None:
    """Match a Tk/CTk widget to an on-screen CGWindow by PID + bounds overlap."""
    pid = os.getpid() if pid is None else pid
    try:
        x1 = float(widget.winfo_rootx())
        y1 = float(widget.winfo_rooty())
        x2 = x1 + float(max(widget.winfo_width(), widget.winfo_reqwidth()))
        y2 = y1 + float(max(widget.winfo_height(), widget.winfo_reqheight()))
    except Exception as exc:
        logger.debug("resolve_cg_window_id: widget bounds failed: %s", exc)
        return None

    try:
        windows = list_cg_windows()
    except Exception as exc:
        logger.warning("CGWindow list failed: %s", exc)
        return None

    best_id: int | None = None
    best_score = -1.0
    target_area = max((x2 - x1) * (y2 - y1), 1.0)

    for win in windows:
        if int(win.get("pid") or -1) != pid:
            continue
        wx, wy = float(win.get("x") or 0), float(win.get("y") or 0)
        ww, wh = float(win.get("w") or 0), float(win.get("h") or 0)
        if ww < 32 or wh < 32:
            continue
        wx2, wy2 = wx + ww, wy + wh
        overlap = _overlap_area(x1, y1, x2, y2, wx, wy, wx2, wy2)
        if overlap <= 0:
            continue
        win_area = ww * wh
        # Prefer windows that both overlap well and are close in size (dialogs vs root).
        score = (overlap / target_area) + (overlap / max(win_area, 1.0))
        # Prefer smaller layer (normal windows) slightly when scores are close.
        score -= 0.001 * float(win.get("layer") or 0)
        if score > best_score:
            best_score = score
            best_id = int(win["id"])

    if best_id is None:
        logger.warning("No CGWindow match for pid=%s bbox=(%.0f,%.0f)-(%.0f,%.0f)", pid, x1, y1, x2, y2)
    else:
        logger.info("Matched CGWindow id=%s score=%.3f for pid=%s", best_id, best_score, pid)
    return best_id


def screencapture_window(window_id: int, dest: Path, *, shadow: bool = False) -> Path:
    """Capture one window via ``screencapture -l`` (preserves rounded corners + alpha)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["screencapture", "-x", "-t", "png", "-l", str(window_id)]
    if not shadow:
        cmd.insert(2, "-o")
    cmd.append(str(dest))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size < 32:
        raise RuntimeError(
            f"screencapture -l {window_id} failed rc={proc.returncode} "
            f"stderr={proc.stderr.strip()!r}"
        )
    return dest
