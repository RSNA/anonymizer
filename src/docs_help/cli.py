"""CLI for MkDocs help screenshot capture."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from docs_help.capture import CAPTURE_WORK, ShotResult, _existing, run_language
from docs_help.manifest import load_manifest
from docs_help.platform import require_host_platform, screen_capture_available

logger = logging.getLogger("docs_help")


def main(argv: list[str] | None = None) -> int:
    """Capture help screenshots into ``docs/<lang>/<workflow>/shots/<os>/``."""
    manifest = load_manifest()
    parser = argparse.ArgumentParser(
        description=(
            "Capture RSNA Anonymizer MkDocs help screenshots.\n\n"
            "Run on macOS and Windows separately; PNGs land under shots/<os>/."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--language", choices=sorted(manifest.languages), default="en_US")
    parser.add_argument("--all-languages", action="store_true")
    parser.add_argument(
        "--platform",
        choices=["auto", "macos", "windows"],
        default="auto",
        help="Target OS shot tree (default: auto = host OS; cross-OS refused)",
    )
    parser.add_argument("--only", nargs="+", metavar="SHOT")
    parser.add_argument("--settle-ms", type=int, default=500)
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--allow-placeholder", action="store_true")
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip shots whose PNG already exists (default: true)",
    )
    parser.add_argument("--force", action="store_true", help="Same as --no-skip-existing")
    parser.add_argument("--force-shot", nargs="+", metavar="SHOT")
    parser.add_argument("--skip-capture-check", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        capture_os = require_host_platform(args.platform)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    languages = list(manifest.languages) if args.all_languages else [args.language]
    only = set(args.only) if args.only else None
    force_shots = set(args.force_shot or ())
    skip_existing = False if args.force else bool(args.skip_existing)
    known = {s.id for s in manifest.all_shots()}
    if only:
        unknown = only - known
        if unknown:
            parser.error(f"Unknown shot id(s): {sorted(unknown)}")
    if force_shots - known:
        parser.error(f"Unknown --force-shot id(s): {sorted(force_shots - known)}")

    if sys.platform == "linux" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("ERROR: No DISPLAY/WAYLAND_DISPLAY", file=sys.stderr)
        return 2

    needs_ui = False
    for language in languages:
        for shot in manifest.all_shots():
            if only and shot.id not in only:
                continue
            dest = manifest.output_path(language, shot, capture_os=capture_os)
            if not skip_existing or shot.id in force_shots or _existing(dest) is None:
                needs_ui = True
                break
        if needs_ui:
            break

    if needs_ui and not args.skip_capture_check and not args.allow_placeholder and not screen_capture_available():
        print(
            "ERROR: Screen capture unavailable. Grant Screen Recording (macOS) or "
            "desktop capture permission (Windows), or use --allow-placeholder.",
            file=sys.stderr,
        )
        return 2

    all_results: list[ShotResult] = []
    for language in languages:
        print(
            f"\n=== Capturing language={language} platform={capture_os} "
            f"→ {manifest.languages[language]}/…/shots/{capture_os}/ ==="
        )
        all_results.extend(
            run_language(
                language,
                only=only,
                settle_ms=args.settle_ms,
                keep_work=args.keep_work,
                allow_placeholder=args.allow_placeholder,
                skip_existing=skip_existing,
                force_shots=force_shots,
                capture_os=capture_os,
            )
        )

    print()
    print(f"{'Shot':<32} {'Status':<10} Detail")
    print("-" * 80)
    for r in all_results:
        print(f"{r.shot_id:<32} {r.status:<10} {r.detail}")
    hard = [r for r in all_results if r.status == "hard_fail"]
    soft = [r for r in all_results if r.status == "soft_fail"]
    ok = [r for r in all_results if r.status == "ok"]
    skipped = [r for r in all_results if r.status == "skipped"]
    print(f"\nSummary: {len(ok)} ok, {len(skipped)} skipped, {len(soft)} soft-fail, {len(hard)} hard-fail")
    code = 1 if hard else 0
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
