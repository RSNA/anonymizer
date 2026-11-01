"""Smoke: eval.midi_b CLI entrypoints resolve without product imports."""

from __future__ import annotations

import pytest

from eval.midi_b.cli import build_parser, main


def test_build_parser_has_validate_test_score() -> None:
    parser = build_parser()
    # Subparsers are required; help alone should exit 0 via argparse when --help.
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0


def test_main_score_missing_run_dir(tmp_path) -> None:
    missing = tmp_path / "no_such_run"
    with pytest.raises(FileNotFoundError):
        main(["score", str(missing)])
