"""Additive SQLite schema sync for existing project anonymizer.db files.

After Base.metadata.create_all, call :func:`ensure_sqlite_columns` so older
released databases (e.g. PyPI / master 19.0.10) gain newly mapped columns and
the pixel→embedded renames. Non-SQLite URLs are a no-op.

Data moves for the retired lookup_patient table use connection SQL (that
table is no longer an ORM class). Unreleased intermediate formats are not handled.
"""

import logging
from typing import Any

from sqlalchemy import Boolean, Column, Integer, MetaData, String, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# (table, legacy column, current column) — released 19.0.10 → current names.
_LEGACY_COLUMN_RENAMES: tuple[tuple[str, str, str], ...] = (
    ("instances", "pixel_phi", "embedded_phi"),
    ("series", "pixel_phi_scanned", "embedded_phi_scanned"),
)

_LOOKUP_PATIENT_TABLE = "lookup_patient"
_DEFAULT_PHI_PATIENT_ID = ""


def _sqlite_column_type(column: Column[Any]) -> str | None:
    """Map a SQLAlchemy column to a SQLite ADD COLUMN type, or None if unsupported."""
    column_type = column.type
    if isinstance(column_type, String):
        return "TEXT"
    if isinstance(column_type, Integer):
        return "INTEGER"
    if isinstance(column_type, Boolean):
        return "INTEGER"
    logger.warning(
        "SQLite schema sync: unsupported column type %r for %s.%s",
        column_type,
        column.table.name if column.table is not None else "?",
        column.name,
    )
    return None


def _sqlite_add_column_sql(table_name: str, column: Column[Any]) -> str | None:
    """Build ALTER TABLE … ADD COLUMN from an ORM column, or None if unsupported."""
    sqlite_type = _sqlite_column_type(column)
    if sqlite_type is None:
        return None

    parts = [f"ALTER TABLE {table_name} ADD COLUMN {column.name} {sqlite_type}"]
    if not column.nullable and column.default is not None:
        default = column.default.arg if hasattr(column.default, "arg") else column.default
        if isinstance(default, bool):
            default = int(default)
        parts.append(f"DEFAULT {default!r}" if isinstance(default, str) else f"DEFAULT {default}")
    return " ".join(parts)


def _table_exists(conn: Any, table_name: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"),
        {"name": table_name},
    ).fetchone()
    return row is not None


def _column_names(conn: Any, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})"))}


def _fold_lookup_patient_into_phi(conn: Any) -> None:
    """Copy released lookup_patient rows onto phi, then drop the table."""
    if not _table_exists(conn, _LOOKUP_PATIENT_TABLE):
        return
    if not _table_exists(conn, "phi"):
        return

    rows = conn.execute(
        text(
            "SELECT patient_id, anon_patient_id, date_offset "
            f"FROM {_LOOKUP_PATIENT_TABLE}"
        )
    ).fetchall()
    for patient_id, anon_patient_id, date_offset in rows:
        if patient_id == _DEFAULT_PHI_PATIENT_ID:
            continue
        existing = conn.execute(
            text("SELECT 1 FROM phi WHERE patient_id = :pid"),
            {"pid": patient_id},
        ).fetchone()
        if existing:
            conn.execute(
                text(
                    "UPDATE phi SET anon_patient_id = :anon, date_offset = :off "
                    "WHERE patient_id = :pid"
                ),
                {"anon": anon_patient_id, "off": date_offset, "pid": patient_id},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO phi (patient_id, anon_patient_id, date_offset) "
                    "VALUES (:pid, :anon, :off)"
                ),
                {"pid": patient_id, "anon": anon_patient_id, "off": date_offset},
            )
    conn.execute(text(f"DROP TABLE {_LOOKUP_PATIENT_TABLE}"))
    logger.info(
        "SQLite schema sync: folded %d lookup_patient row(s) into phi and dropped table",
        len(rows),
    )


def ensure_sqlite_columns(engine: Engine, metadata: MetaData, *, db_url: str) -> None:
    """
    Add any ORM-mapped columns missing from an existing SQLite database.

    Also applies the finite 19.0.10 pixel→embedded renames and folds
    lookup_patient into phi when that legacy table is present.

    Args:
        engine: SQLAlchemy engine bound to the project database.
        metadata: Declarative metadata (typically Base.metadata).
        db_url: Database URL; non-sqlite URLs are skipped.
    """
    if not db_url.startswith("sqlite"):
        logger.debug("SQLite schema sync skipped for non-sqlite database URL.")
        return

    with engine.connect() as conn:
        for table in metadata.sorted_tables:
            if not _table_exists(conn, table.name):
                continue

            existing_columns = _column_names(conn, table.name)
            for legacy_table, old_name, new_name in _LEGACY_COLUMN_RENAMES:
                if (
                    legacy_table == table.name
                    and old_name in existing_columns
                    and new_name not in existing_columns
                ):
                    conn.execute(
                        text(f"ALTER TABLE {table.name} RENAME COLUMN {old_name} TO {new_name}")
                    )
                    existing_columns = (existing_columns - {old_name}) | {new_name}
                    logger.info(
                        "SQLite schema sync: renamed %s.%s -> %s",
                        table.name,
                        old_name,
                        new_name,
                    )
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                add_column_sql = _sqlite_add_column_sql(table.name, column)
                if add_column_sql is None:
                    continue
                conn.execute(text(add_column_sql))
                logger.info("SQLite schema sync: added %s.%s", table.name, column.name)

        _fold_lookup_patient_into_phi(conn)
        conn.commit()
