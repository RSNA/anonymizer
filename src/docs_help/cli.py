"""CLI for MkDocs help screenshot capture."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from docs_help.capture import ShotResult, _existing, format_capture_report, run_language
from docs_help.interrupt import hard_exit, install_hard_interrupt
from docs_help.manifest import load_manifest
from docs_help.platform import require_host_platform, screen_capture_available

logger = logging.getLogger("docs_help")


def main(argv: list[str] | None = None) -> int:
    """Capture help screenshots into ``docs/<lang>/<workflow>/shots/<os>/``."""
    install_hard_interrupt()
    try:
        return _main(argv)
    except KeyboardInterrupt:
        hard_exit()


def _main(argv: list[str] | None = None) -> int:
    """Capture help screenshots into ``docs/<lang>/<workflow>/shots/<os>/``."""
    manifest = load_manifest()
    parser = argparse.ArgumentParser(
        description=(
            "Capture RSNA Anonymizer MkDocs help screenshots.\n\n"
            "Full capture (all languages, chapter order, resume-safe):\n"
            "  uv run python -m docs_help -v\n\n"
            "Languages run in manifest order: en_US → de → es → fr.\n"
            "Existing PNGs stay on disk (report status: exists); re-run to resume.\n"
            "One language:  uv run python -m docs_help --language de -v\n"
            "Shots follow docs/screenshots-manifest.yaml (help-chapter order).\n"
            "Shared TSEG cache: docs/.capture_work/fixture_cache/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    lang_codes = manifest.language_codes()
    parser.add_argument(
        "--language",
        choices=lang_codes,
        default=None,
        help="Capture one UI language. Default: all languages in order.",
    )
    parser.add_argument(
        "--all-languages",
        action="store_true",
        help="Capture every language in manifest order (default when --language is omitted).",
    )
    parser.add_argument(
        "--platform",
        choices=["auto", "macos", "windows"],
        default="auto",
        help="Target OS shot tree (default: auto = host OS; cross-OS refused)",
    )
    parser.add_argument("--only", nargs="+", metavar="SHOT")
    parser.add_argument("--settle-ms", type=int, default=500)
    parser.add_argument(
        "--keep-work",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep docs/.capture_work/<lang> after the run so a later invocation can resume (default: true)",
    )
    parser.add_argument(
        "--reset-work",
        action="store_true",
        help="Wipe docs/.capture_work/<lang> before capturing. Does not delete docs/.capture_work/fixture_cache/.",
    )
    parser.add_argument("--allow-placeholder", action="store_true")
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Leave shots whose PNG already exists (report status: exists). Default: true",
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

    if args.language and args.all_languages:
        parser.error("use --language for one locale, or omit it / pass --all-languages for a full run")
    languages = list(lang_codes) if args.language is None or args.all_languages else [args.language]
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

    print(
        f"Full capture languages ({len(languages)}): " + " → ".join(languages),
        flush=True,
    )
    all_results: list[ShotResult] = []
    for lang_i, language in enumerate(languages, start=1):
        print(
            f"\n=== [{lang_i}/{len(languages)}] language={language} platform={capture_os} "
            f"→ {manifest.languages[language]}/…/shots/{capture_os}/ ===",
            flush=True,
        )
        all_results.extend(
            run_language(
                language,
                only=only,
                settle_ms=args.settle_ms,
                keep_work=bool(args.keep_work),
                allow_placeholder=args.allow_placeholder,
                skip_existing=skip_existing,
                force_shots=force_shots,
                capture_os=capture_os,
                reset_work=bool(args.reset_work),
            )
        )

    print()
    print(
        format_capture_report(
            all_results,
            shot_order=tuple(s.id for s in manifest.all_shots()),
            languages=tuple(languages),
            capture_os=capture_os,
        )
    )
    hard = [r for r in all_results if r.status == "hard_fail"]
    code = 1 if hard else 0
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
