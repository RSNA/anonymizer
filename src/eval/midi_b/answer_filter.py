"""Copy a patient/SOP subset of the MIDI answer-key SQLite DB."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path


def filter_answer_db(
    source_db: Path,
    dest_db: Path,
    *,
    patient_ids: Sequence[str] | None = None,
) -> int:
    """
    Copy answer_data rows for selected PatientID values into dest_db.

    Args:
        source_db: Full Validation answer-key path.
        dest_db: Destination SQLite path (replaced if present).
        patient_ids: PatientID strings to keep; required for a subset.

    Returns:
        Number of rows copied.

    Raises:
        ValueError: When patient_ids is empty.
        RuntimeError: When answer_data schema is missing.
    """
    if not patient_ids:
        raise ValueError("filter_answer_db requires patient_ids")

    source_db = Path(source_db)
    dest_db = Path(dest_db)
    if dest_db.exists():
        dest_db.unlink()
    dest_db.parent.mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(str(source_db))
    try:
        schema = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='answer_data'"
        ).fetchone()
        if not schema or not schema[0]:
            raise RuntimeError(f"no answer_data table in {source_db}")

        dst = sqlite3.connect(str(dest_db))
        try:
            dst.execute(schema[0])
            # Quote identifiers — answer_data has columns named ``index`` / ``group``.
            cols = [str(d[1]) for d in src.execute("PRAGMA table_info(answer_data)").fetchall()]
            col_list = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join("?" for _ in cols)
            in_list = ", ".join("?" for _ in patient_ids)
            rows = src.execute(
                f'SELECT {col_list} FROM answer_data '
                f'WHERE CAST("PatientID" AS TEXT) IN ({in_list})',
                [str(p) for p in patient_ids],
            ).fetchall()
            dst.executemany(
                f"INSERT INTO answer_data ({col_list}) VALUES ({placeholders})",
                rows,
            )
            dst.commit()
            return len(rows)
        finally:
            dst.close()
    finally:
        src.close()
