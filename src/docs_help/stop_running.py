"""Stop other RSNA Anonymizer GUI processes before help screenshot capture.

Capture runs Anonymizer in-process. A second desktop instance steals focus,
holds SCP ports, and can make window grabs hit the wrong app. Call
``stop_running_anonymizer_apps`` once before the first UI shot.

Public API
----------
stop_running_anonymizer_apps(*, timeout_s: float = 8.0) -> list[int]
    Terminate other Anonymizer GUI processes; return the PIDs that were signalled.

cmdline_looks_like_anonymizer_gui(cmdline) -> bool
    True when a process command line is an Anonymizer GUI (not docs_help/tests).

owner_looks_like_anonymizer_app(owner) -> bool
    True when a window owner / process display name is the Anonymizer app (not a browser tab).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Packaged product name (CHANGELOG / installer) and window-title stem.
_APP_PROCESS_NAMES = frozenset({"anonymizer", "rsna-anonymizer", "rsna dicom anonymizer"})
_WINDOW_TITLE_MARKERS = (
    "RSNA DICOM Anonymizer",
    "RSNA DICOM Anonymizer Version",
)
_CMDLINE_INCLUDE = (
    "-m anonymizer",
    "anonymizer.anonymizer",
    "anonymizer.__main__",
    "rsna-anonymizer",
)
_CMDLINE_EXCLUDE = (
    "docs_help",
    "-m docs_help",
    "pytest",
    "unittest",
    "py.test",
)


def stop_running_anonymizer_apps(*, timeout_s: float = 8.0) -> list[int]:
    """Terminate other Anonymizer GUI processes; return the PIDs that were signalled.

    Never signals this process or its parent. Best-effort: logs and continues if
    a PID is already gone or cannot be killed.
    """
    self_pids = _protected_pids()
    candidates = sorted((_candidate_pids() - self_pids))
    if not candidates:
        logger.info("No other Anonymizer GUI process found before capture")
        return []

    logger.warning(
        "Stopping %d other Anonymizer process(es) before capture: %s",
        len(candidates),
        candidates,
    )
    _quit_packaged_macos_app()
    for pid in candidates:
        _terminate_pid(pid)

    deadline = time.monotonic() + max(0.5, float(timeout_s))
    remaining = set(candidates)
    while remaining and time.monotonic() < deadline:
        alive = {pid for pid in remaining if _pid_alive(pid)}
        for pid in remaining - alive:
            logger.info("Stopped Anonymizer pid=%s", pid)
        remaining = alive
        if remaining:
            time.sleep(0.2)

    for pid in sorted(remaining):
        logger.warning("Force-killing Anonymizer pid=%s", pid)
        _kill_pid(pid)
        time.sleep(0.1)

    still = [pid for pid in candidates if _pid_alive(pid)]
    if still:
        logger.error("Anonymizer process(es) still running after stop: %s", still)
    return candidates


def _protected_pids() -> set[int]:
    pids = {os.getpid()}
    try:
        pids.add(os.getppid())
    except Exception:
        pass
    return pids


def _candidate_pids() -> set[int]:
    found: set[int] = set()
    found.update(_pids_from_process_table())
    if sys.platform == "darwin":
        found.update(_pids_from_cg_windows())
    elif sys.platform == "win32":
        found.update(_pids_from_windows_titles())
    return found


def cmdline_looks_like_anonymizer_gui(cmdline: str) -> bool:
    """True when a process command line is an Anonymizer GUI (not docs_help/tests)."""
    text = " ".join((cmdline or "").split())
    if not text:
        return False
    low = text.casefold()
    if any(marker in low for marker in _CMDLINE_EXCLUDE):
        return False
    exe = Path(text.split()[0]).name.casefold()
    if exe in _APP_PROCESS_NAMES or exe.endswith(".app"):
        # Packaged binary / shortcut name.
        if "anonymizer" in exe:
            return True
    if any(marker in low for marker in _CMDLINE_INCLUDE):
        return True
    # ``python …/anonymizer/anonymizer.py`` or ``…/anonymizer/__main__.py``
    if "anonymizer" in low and (
        low.rstrip().endswith("anonymizer.py")
        or "__main__.py" in low
        or "/anonymizer " in low
        or "\\anonymizer " in low
    ):
        return True
    return False


def _pids_from_process_table() -> set[int]:
    rows: list[tuple[int, str]] = []
    try:
        if sys.platform == "win32":
            rows = _windows_process_rows()
        else:
            rows = _posix_process_rows()
    except Exception as exc:
        logger.warning("Process table scan failed: %s", exc)
        return set()

    out: set[int] = set()
    for pid, cmd in rows:
        if pid <= 0:
            continue
        if cmdline_looks_like_anonymizer_gui(cmd):
            out.add(pid)
    return out


def _posix_process_rows() -> list[tuple[int, str]]:
    proc = subprocess.run(
        ["ps", "-ax", "-o", "pid=,command="],
        check=False,
        capture_output=True,
        text=True,
    )
    rows: list[tuple[int, str]] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            rows.append((int(parts[0]), parts[1]))
        except ValueError:
            continue
    return rows


def _windows_process_rows() -> list[tuple[int, str]]:
    # Prefer PowerShell: CommandLine is often empty in tasklist.
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,CommandLine,Name | "
        "ForEach-Object { '{0}\t{1}\t{2}' -f $_.ProcessId, $_.Name, $_.CommandLine }"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )
    rows: list[tuple[int, str]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        name = parts[1] if len(parts) > 1 else ""
        cmd = parts[2] if len(parts) > 2 else ""
        rows.append((pid, f"{name} {cmd}".strip()))
    return rows


def owner_looks_like_anonymizer_app(owner: str) -> bool:
    """True when a window owner / process display name is the Anonymizer app.

    Browser tabs often show ``RSNA DICOM Anonymizer`` in the title (docs, GitHub).
    Never treat title text alone as the running product — only the owning app name.
    """
    text = (owner or "").strip()
    if not text:
        return False
    low = Path(text).name.casefold()
    if low.endswith(".exe"):
        low = low[: -len(".exe")]
    if low in _APP_PROCESS_NAMES:
        return True
    # Packaged display name, e.g. "RSNA DICOM Anonymizer".
    return "anonymizer" in low


def _pids_from_cg_windows() -> set[int]:
    try:
        from docs_help.platform.macos import list_cg_windows
    except Exception as exc:
        logger.warning("CGWindow scan unavailable: %s", exc)
        return set()
    try:
        windows = list_cg_windows()
    except Exception as exc:
        logger.warning("CGWindow list failed: %s", exc)
        return set()
    out: set[int] = set()
    for win in windows:
        owner = str(win.get("owner") or "")
        # Title markers alone are unsafe (Safari/Chrome tab titles). Owner must be us.
        if not owner_looks_like_anonymizer_app(owner):
            continue
        try:
            pid = int(win.get("pid") or 0)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            out.add(pid)
    return out


def _pids_from_windows_titles() -> set[int]:
    """Find PIDs of Anonymizer top-level windows (owner process name, not tab title)."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return set()

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    found: set[int] = set()
    get_pid = user32.GetWindowThreadProcessId
    get_text = user32.GetWindowTextW
    get_text_len = user32.GetWindowTextLengthW
    is_visible = user32.IsWindowVisible

    def _process_image_name(pid: int) -> str:
        """Best-effort executable base name for ``pid`` (empty on failure)."""
        access = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(access, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(len(buf))
            query = getattr(kernel32, "QueryFullProcessImageNameW", None)
            if query is None:
                return ""
            if not query(handle, 0, buf, ctypes.byref(size)):
                return ""
            return Path(buf.value or "").name
        except Exception:
            return ""
        finally:
            kernel32.CloseHandle(handle)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):  # type: ignore[no-untyped-def]
        if not is_visible(hwnd):
            return True
        length = int(get_text_len(hwnd) or 0)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        get_text(hwnd, buf, length + 1)
        title = buf.value or ""
        if not any(marker.casefold() in title.casefold() for marker in _WINDOW_TITLE_MARKERS):
            return True
        pid = wintypes.DWORD()
        get_pid(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        # Same Safari/Chrome trap as macOS: tab title ≠ owning app.
        if not owner_looks_like_anonymizer_app(_process_image_name(int(pid.value))):
            return True
        found.add(int(pid.value))
        return True

    user32.EnumWindows(_enum, 0)
    return found


def _quit_packaged_macos_app() -> None:
    if sys.platform != "darwin":
        return
    # Best-effort AppleEvent quit for the installed app bundle name.
    for app_name in ("Anonymizer", "RSNA DICOM Anonymizer"):
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{app_name}" to quit'],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception as exc:
            logger.debug("osascript quit %s: %s", app_name, exc)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                check=False,
                capture_output=True,
                text=True,
            )
            out = proc.stdout or ""
            return str(pid) in out and "No tasks" not in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _terminate_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid)],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception as exc:
        logger.warning("SIGTERM pid=%s failed: %s", pid, exc)


def _kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception as exc:
        logger.warning("SIGKILL pid=%s failed: %s", pid, exc)
