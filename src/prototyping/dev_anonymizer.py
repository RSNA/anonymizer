#!/usr/bin/env python3
"""Run rsna-anonymizer and restart when Python sources under src/anonymizer change."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WATCH_DIR = REPO_ROOT / "src" / "anonymizer"
DEFAULT_DEBOUNCE = os.environ.get("ANONYMIZER_DEV_DEBOUNCE", "2s")


def run_watchexec(*, debounce: str) -> int:
    watchexec = shutil.which("watchexec")
    if watchexec is None:
        return 127

    watch_path = WATCH_DIR.relative_to(REPO_ROOT)
    print(f"Watching {watch_path}/ with watchexec (debounce={debounce})")
    print("Restarting rsna-anonymizer on .py changes (Ctrl+C to stop)\n", flush=True)
    return subprocess.run(
        [
            watchexec,
            "-r",
            "-e",
            "py",
            "-w",
            str(watch_path),
            "-d",
            debounce,
            "--",
            "uv",
            "run",
            "rsna-anonymizer",
        ],
        cwd=REPO_ROOT,
        check=False,
    ).returncode


def run_watchfiles(*, debounce_ms: int) -> int:
    try:
        from watchfiles import PythonFilter, run_process
    except ImportError:
        print("Missing watchfiles. Run: uv sync --group dev", file=sys.stderr)
        return 1

    print(f"Watching {WATCH_DIR.relative_to(REPO_ROOT)}/ with watchfiles (debounce={debounce_ms}ms)")
    print("Restarting rsna-anonymizer on .py changes (Ctrl+C to stop)\n", flush=True)

    def run_app() -> None:
        subprocess.run(["uv", "run", "rsna-anonymizer"], cwd=REPO_ROOT, check=False)

    run_process(
        str(WATCH_DIR),
        target=run_app,
        watch_filter=PythonFilter(),
        debounce=debounce_ms,
    )
    return 0


def main() -> None:
    debounce = DEFAULT_DEBOUNCE
    exit_code = run_watchexec(debounce=debounce)
    if exit_code != 127:
        raise SystemExit(exit_code)

    print("watchexec not found; falling back to watchfiles.", file=sys.stderr)
    print("Install watchexec for more reliable restarts: brew install watchexec\n", file=sys.stderr)
    fallback_ms = 2000
    if debounce.endswith("ms"):
        fallback_ms = max(500, int(debounce[:-2]))
    elif debounce.endswith("s"):
        fallback_ms = max(500, int(float(debounce[:-1]) * 1000))
    raise SystemExit(run_watchfiles(debounce_ms=fallback_ms))


if __name__ == "__main__":
    main()
