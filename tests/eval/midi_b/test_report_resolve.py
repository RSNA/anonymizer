"""SCORECARD finds validation_results.db under either midi_b or run-named folder."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from eval.midi_b.report import resolve_validation_results_db, write_score_report


def _tiny_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE validation_results (action TEXT, check_passed INTEGER, "
            "tag_ds TEXT, tag_name TEXT)"
        )
        con.execute(
            "INSERT INTO validation_results VALUES ('<uid_changed>', 1, '<(0008,0018)>', 'SOP')"
        )
        con.execute(
            "INSERT INTO validation_results VALUES ('<uid_changed>', 0, '<(0008,0018)>', 'SOP')"
        )
        con.commit()
    finally:
        con.close()


def _tiny_scoring_xlsx(path: Path, *, score: str = "50.00%") -> None:
    """Minimal Scoring sheet matching MIDI validation reports_helper output."""
    import pandas as pd

    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        [
            {
                "Category": "All",
                "Blank": 0,
                "Fail": 1,
                "Pass": 1,
                "Total": 2,
                "Score": score,
            }
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Scoring", index=False)


def test_resolve_prefers_midi_b_then_run_name(tmp_path: Path) -> None:
    run = tmp_path / "validation_smoke5"
    run.mkdir()
    legacy = run / "official_score" / "midi_b" / "validation_results.db"
    _tiny_db(legacy)
    assert resolve_validation_results_db(run) == legacy

    alt_run = tmp_path / "validation_alt"
    alt_run.mkdir()
    named = alt_run / "official_score" / alt_run.name / "validation_results.db"
    _tiny_db(named)
    assert resolve_validation_results_db(alt_run) == named


def test_write_score_report_from_run_named_folder(tmp_path: Path) -> None:
    run = tmp_path / "validation_20261029T_smoke5"
    official = run / "official_score" / run.name
    _tiny_db(official / "validation_results.db")
    _tiny_scoring_xlsx(official / "scoring_report_instance.xlsx", score="50.00%")
    out = write_score_report(run)
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "**Final score: 50.00%**" in text
    assert "Mean check score" not in text
    assert "Binary pass rate" not in text
    assert "`<uid_changed>`" in text
    # Fail % is share of all checks (not per-action rate).
    assert "| `<uid_changed>` | 1 | 1 | 2 | 50.00% |" in text
    assert "| **Total** | **1** | **1** | **2** | **50.00%** |" in text


def test_resolve_missing_raises(tmp_path: Path) -> None:
    run = tmp_path / "empty_run"
    run.mkdir()
    with pytest.raises(FileNotFoundError):
        resolve_validation_results_db(run)
