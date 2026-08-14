#!/usr/bin/env python3
"""Check welcome window sizing locally (CTk 6 + Tk 9 on macOS).

Run from the repo root::

    uv run python scripts/test_welcome_window.py

Exit 0 when the welcome window keeps its target width after layout; exit 1 otherwise.
Use ``--interactive`` to keep the window open for visual inspection.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "src" / "anonymizer"


def _prepare_environment() -> Path:
    os.chdir(PACKAGE_DIR)
    logs_dir = Path(tempfile.mkdtemp(prefix="anonymizer-welcome-test-"))
    return logs_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify welcome window dimensions after CTk layout.")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Keep the welcome window open after the automated check (default: exit once check passes).",
    )
    parser.add_argument(
        "--check-ms",
        type=int,
        default=800,
        help="Milliseconds after startup to measure window size (default: 800).",
    )
    parser.add_argument(
        "--simulate-drift",
        action="store_true",
        help=(
            "After layout, force a narrow window like Retina Configure drift on ccarr's MacBook, "
            "then verify the welcome guard restores full width before the final check."
        ),
    )
    parser.add_argument(
        "--simulate-drift-ms",
        type=int,
        default=600,
        help="When --simulate-drift is set, inject the bad geometry at this time (default: 600).",
    )
    args = parser.parse_args()

    print(f"Python: {sys.version.split()[0]}")
    print(f"Tk: {tk.TkVersion}  working dir: {os.getcwd()}")

    logs_dir = _prepare_environment()

    from anonymizer.anonymizer import Anonymizer
    from anonymizer.view.common.ctk_safe import install_safe_scaling_tracker

    install_safe_scaling_tracker()
    app = Anonymizer(logs_dir)

    result = {"ok": False, "drift_recovered": not args.simulate_drift}

    def simulate_retina_configure_drift() -> None:
        """Mimic macOS Retina startup: CTk reads a tiny width before layout settles."""
        print("Simulating Configure drift (narrow window, stale _current_width)...")
        app._block_update_dimensions_event = False
        app._current_width = 120
        app._current_height = 900
        app.minsize(120, 400)
        app.maxsize(120, 2000)
        app.geometry("120x900")
        app.update_idletasks()
        # Re-enable welcome lock path (guard should still be active).
        app._welcome_window_locked = True
        app._block_update_dimensions_event = True

    def run_check() -> None:
        target_w, target_h = app._welcome_target_size()
        min_w = int(target_w * app.welcome_size_tolerance)
        current_w = app._current_width
        winfo_w = app.winfo_width()
        detected_w = app._reverse_window_scaling(winfo_w) if winfo_w > 1 else current_w
        effective_w = max(current_w, detected_w)
        ok = effective_w >= min_w and app._welcome_window_locked
        if args.simulate_drift:
            ok = ok and result["drift_recovered"]
        result["ok"] = ok
        try:
            widget_scaling = app._get_widget_scaling()
            window_scaling = app._get_window_scaling()
        except Exception:
            widget_scaling = window_scaling = "?"

        print()
        print("Welcome window check")
        print(f"  target (CTk units):     {target_w} x {target_h}")
        print(f"  minimum width (85%):    {min_w}")
        print(f"  _current_width/height:  {current_w} x {app._current_height}")
        print(f"  winfo width/height:     {winfo_w} x {app.winfo_height()}")
        print(f"  detected width (CTk):   {detected_w}")
        print(f"  effective width:        {effective_w}")
        print(f"  welcome locked:         {app._welcome_window_locked}")
        if args.simulate_drift:
            print(f"  drift recovered:        {result['drift_recovered']}")
        print(f"  scaling widget/window:  {widget_scaling} / {window_scaling}")
        print(f"  result:                 {'PASS' if ok else 'FAIL'}")
        print()

        if ok and not args.interactive:
            app.quit()

    if args.simulate_drift:

        def inject_drift() -> None:
            simulate_retina_configure_drift()
            # Guard runs every 500ms; allow one cycle to recover before we record it.
            app.after(app.welcome_guard_interval_ms + 50, _record_drift_recovery)

        def _record_drift_recovery() -> None:
            min_w = int(app._welcome_target_size()[0] * app.welcome_size_tolerance)
            effective_w = max(
                app._current_width,
                app._reverse_window_scaling(app.winfo_width()) if app.winfo_width() > 1 else 0,
            )
            result["drift_recovered"] = effective_w >= min_w
            print(
                f"Post-drift recovery: effective width={effective_w} "
                f"(min={min_w}) -> {'OK' if result['drift_recovered'] else 'FAIL'}"
            )

        app.after(args.simulate_drift_ms, inject_drift)

    check_ms = args.check_ms
    if args.simulate_drift:
        min_check = args.simulate_drift_ms + app.welcome_guard_interval_ms + 100
        if check_ms < min_check:
            check_ms = min_check
            print(f"Adjusted --check-ms to {check_ms} so drift recovery can complete")

    app.after(check_ms, run_check)
    app.mainloop()

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
