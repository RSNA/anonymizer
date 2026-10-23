"""Emit official MIDI validator ``id_old,id_new`` mapping CSVs."""

import csv
import logging
import sqlite3
from pathlib import Path

from sqlalchemy import select

from anonymizer.model.anonymizer import AnonymizerModel, PHI, UID

logger = logging.getLogger(__name__)


def write_uid_mapping(model: AnonymizerModel, path: Path) -> int:
    """Dump ``UID`` table as bare ``id_old,id_new`` CSV (official scorer wraps ``<>``)."""
    rows = model.session.execute(select(UID.phi_uid, UID.anon_uid)).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id_old", "id_new"])
        n = 0
        for phi_uid, anon_uid in rows:
            old = str(phi_uid or "").strip()
            new = str(anon_uid or "").strip()
            if not old or not new:
                continue
            w.writerow([old, new])
            n += 1
    logger.info("wrote %d uid mappings → %s", n, path)
    return n


def write_patid_mapping(model: AnonymizerModel, path: Path) -> int:
    """Dump ``PHI`` patient_id → anon_patient_id (skip empty default PHI key)."""
    rows = model.session.execute(select(PHI.patient_id, PHI.anon_patient_id)).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id_old", "id_new"])
        n = 0
        for patient_id, anon_patient_id in rows:
            old = str(patient_id if patient_id is not None else "").strip()
            new = str(anon_patient_id or "").strip()
            # Default PHI row uses empty patient_id PK — not a challenge id.
            if old == AnonymizerModel.DEFAULT_PHI_PATIENT_ID_PK_VALUE or not new:
                continue
            w.writerow([old, new])
            n += 1
    logger.info("wrote %d patid mappings → %s", n, path)
    return n


def filter_answer_db(
    source_db: Path,
    dest_db: Path,
    *,
    patient_ids: list[str] | None = None,
    sop_uids: list[str] | None = None,
) -> int:
    """Copy a subset of ``answer_data`` rows into ``dest_db`` for smoke scoring."""
    if not patient_ids and not sop_uids:
        raise ValueError("filter_answer_db requires patient_ids and/or sop_uids")

    source_db = Path(source_db)
    dest_db = Path(dest_db)
    if dest_db.exists():
        dest_db.unlink()
    dest_db.parent.mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(str(source_db))
    try:
        # Preserve schema.
        schema = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='answer_data'"
        ).fetchone()
        if not schema or not schema[0]:
            raise RuntimeError(f"no answer_data table in {source_db}")

        dst = sqlite3.connect(str(dest_db))
        try:
            dst.execute(schema[0])
            cols = [r[1] for r in src.execute("PRAGMA table_info(answer_data)")]
            # Quote identifiers — answer_data has a column named ``index``.
            col_list = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join("?" for _ in cols)

            where: list[str] = []
            params: list[object] = []
            if patient_ids:
                where.append(
                    f'CAST("PatientID" AS TEXT) IN ({",".join("?" for _ in patient_ids)})'
                )
                params.extend(str(p) for p in patient_ids)
            if sop_uids:
                where.append(
                    f'"SOPInstanceUID" IN ({",".join("?" for _ in sop_uids)})'
                )
                params.extend(sop_uids)
            sql = f'SELECT {col_list} FROM answer_data WHERE {" AND ".join(where)}'
            rows = src.execute(sql, params).fetchall()
            dst.executemany(
                f"INSERT INTO answer_data ({col_list}) VALUES ({placeholders})",
                rows,
            )
            dst.commit()
            logger.info(
                "filtered answer key %d → %d rows → %s",
                src.execute("SELECT COUNT(*) FROM answer_data").fetchone()[0],
                len(rows),
                dest_db,
            )
            return len(rows)
        finally:
            dst.close()
    finally:
        src.close()
