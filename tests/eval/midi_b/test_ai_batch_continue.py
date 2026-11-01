"""AI batch outliers must not abort the full MIDI-B validate/test run."""

from __future__ import annotations

from eval.midi_b.cli import _abort_after_ai_batch, _dump_batch_errors


def test_abort_after_ai_batch_continues_when_series_failed() -> None:
    """Two series Failed: lines + exit 1 → continue to score (full-run case)."""
    lines = [
        "batch.log:   Failed: Missing required element: (0028,0006) 'Planar Configuration'",
        "batch.log:   Failed: SR slot count mismatch: text parts=14 compact_slots=15",
    ]
    assert _abort_after_ai_batch(batch_rc=1, series_error_lines=lines) is False


def test_abort_after_ai_batch_continues_on_clean_exit() -> None:
    assert _abort_after_ai_batch(batch_rc=0, series_error_lines=[]) is False
    assert _abort_after_ai_batch(batch_rc=0, series_error_lines=["x Failed: y"]) is False


def test_abort_after_ai_batch_stops_on_hard_failure() -> None:
    """Non-zero exit with no series log lines → abort (config / cancel / crash)."""
    assert _abort_after_ai_batch(batch_rc=1, series_error_lines=[]) is True
    assert _abort_after_ai_batch(batch_rc=2, series_error_lines=[]) is True


def test_dump_batch_errors_finds_failed_sublines(tmp_path) -> None:
    runs = tmp_path / "private" / "batch_runs"
    runs.mkdir(parents=True)
    (runs / "run.log").write_text(
        "Study 1\n"
        "  Failed: Missing required element: (0028,0006) 'Planar Configuration'\n"
        "Study 2\n"
        "  Failed: SR slot count mismatch: text parts=14 compact_slots=15\n",
        encoding="utf-8",
    )
    lines = _dump_batch_errors(tmp_path)
    assert len(lines) == 2
    assert "Planar Configuration" in lines[0]
    assert "SR slot count mismatch" in lines[1]
    assert _abort_after_ai_batch(batch_rc=1, series_error_lines=lines) is False
