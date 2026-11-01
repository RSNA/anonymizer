"""Answer-key subset filter quotes reserved column names."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from eval.midi_b.answer_filter import filter_answer_db


def test_filter_answer_db_quotes_index_column(tmp_path: Path) -> None:
    src = tmp_path / "full.db"
    con = sqlite3.connect(str(src))
    try:
        con.execute(
            'CREATE TABLE answer_data ("index" INTEGER, "group" INTEGER, '
            "PatientID INTEGER, SOPInstanceUID TEXT, AnswerData TEXT)"
        )
        con.executemany(
            'INSERT INTO answer_data ("index", "group", PatientID, SOPInstanceUID, AnswerData) '
            "VALUES (?, ?, ?, ?, ?)",
            [
                (0, 1, 1011144680, "1.2.3", "a"),
                (1, 1, 999, "1.2.9", "b"),
                (2, 1, 105230877, "1.2.4", "c"),
            ],
        )
        con.commit()
    finally:
        con.close()

    dest = tmp_path / "filtered.db"
    n = filter_answer_db(src, dest, patient_ids=["1011144680", "105230877"])
    assert n == 2
    out = sqlite3.connect(str(dest))
    try:
        rows = out.execute(
            'SELECT CAST("PatientID" AS TEXT) FROM answer_data ORDER BY "index"'
        ).fetchall()
    finally:
        out.close()
    assert [r[0] for r in rows] == ["1011144680", "105230877"]
