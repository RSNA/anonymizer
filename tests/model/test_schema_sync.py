"""Tests for additive SQLite schema sync (released 19.0.10 → current)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from tests.opened_anonymizer_model import opened_anonymizer_model

CURRENT_PHI_COLUMNS = {
    "patient_id",
    "anon_patient_id",
    "patient_name",
    "sex",
    "dob",
    "ethnic_group",
    "date_offset",
    "base_date",
}

CURRENT_METADATA_COLUMNS = (
    ("instances", "embedded_phi"),
    ("series", "harmonized_description"),
    ("series", "face_blur_algorithm_applied"),
    ("series", "embedded_phi_scanned"),
    ("studies", "harmonized_description"),
)

LOOKUP_PATIENT_TABLE = "lookup_patient"


def _column_names(db_path: Path, table_name: str) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        names = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})"))}
    engine.dispose()
    return names


def _table_names(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
    engine.dispose()
    return names


def _create_released_v19_0_10_shaped_db(db_path: Path) -> None:
    """Create an anonymizer.db shape matching PyPI / master 19.0.10."""
    engine = create_engine(f"sqlite:///{db_path}")
    statements = [
        """
        CREATE TABLE phi (
            patient_id TEXT PRIMARY KEY,
            anon_patient_id TEXT NOT NULL UNIQUE,
            patient_name TEXT,
            sex TEXT,
            dob TEXT,
            ethnic_group TEXT,
            date_offset INTEGER
        )
        """,
        """
        CREATE TABLE studies (
            study_uid TEXT PRIMARY KEY,
            anon_study_uid TEXT NOT NULL UNIQUE,
            patient_id TEXT NOT NULL,
            source TEXT NOT NULL,
            study_date TEXT NOT NULL,
            anon_date_delta INTEGER NOT NULL,
            accession_number TEXT,
            anon_accession_number TEXT,
            description TEXT,
            harmonized_description TEXT,
            target_instance_count INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(patient_id) REFERENCES phi(patient_id)
        )
        """,
        """
        CREATE TABLE series (
            series_uid TEXT PRIMARY KEY,
            anon_series_uid TEXT NOT NULL UNIQUE,
            study_uid TEXT NOT NULL,
            modality TEXT,
            description TEXT,
            harmonized_description TEXT,
            face_blur_algorithm_applied TEXT,
            pixel_phi_scanned BOOLEAN NOT NULL DEFAULT 0,
            FOREIGN KEY(study_uid) REFERENCES studies(study_uid)
        )
        """,
        """
        CREATE TABLE instances (
            sop_instance_uid TEXT PRIMARY KEY,
            anon_sop_instance_uid TEXT NOT NULL UNIQUE,
            series_uid TEXT NOT NULL,
            pixel_phi TEXT,
            FOREIGN KEY(series_uid) REFERENCES series(series_uid)
        )
        """,
        """
        CREATE TABLE UID_map (
            mapping_pk INTEGER PRIMARY KEY AUTOINCREMENT,
            anon_uid TEXT NOT NULL UNIQUE,
            phi_uid TEXT NOT NULL UNIQUE
        )
        """,
        """
        CREATE TABLE lookup_patient (
            patient_id TEXT PRIMARY KEY,
            anon_patient_id TEXT NOT NULL,
            date_offset INTEGER
        )
        """,
        """
        INSERT INTO phi (patient_id, anon_patient_id)
        VALUES ('', '574856-000000')
        """,
        """
        INSERT INTO lookup_patient (patient_id, anon_patient_id, date_offset)
        VALUES ('MRN1', 'SITE-1', 42)
        """,
        """
        INSERT INTO studies (
            study_uid, anon_study_uid, patient_id, source, study_date, anon_date_delta
        ) VALUES ('s', 'as', '', 'x', '20240101', 0)
        """,
        """
        INSERT INTO series (
            series_uid, anon_series_uid, study_uid, pixel_phi_scanned
        ) VALUES ('se', 'ase', 's', 1)
        """,
        """
        INSERT INTO instances (
            sop_instance_uid, anon_sop_instance_uid, series_uid, pixel_phi
        ) VALUES ('i', 'ai', 'se', 'Jane Doe')
        """,
    ]
    with engine.connect() as conn:
        for statement in statements:
            conn.execute(text(statement))
        conn.commit()
    engine.dispose()


def test_fresh_db_has_current_phi_and_metadata_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    with opened_anonymizer_model(f"sqlite:///{db_path}"):
        pass

    assert LOOKUP_PATIENT_TABLE not in _table_names(db_path)
    assert CURRENT_PHI_COLUMNS.issubset(_column_names(db_path, "phi"))
    for table_name, column_name in CURRENT_METADATA_COLUMNS:
        assert column_name in _column_names(db_path, table_name)


def test_ensure_sqlite_columns_is_idempotent_on_current_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    db_url = f"sqlite:///{db_path}"

    with opened_anonymizer_model(db_url):
        pass
    columns_after_first = {
        table: _column_names(db_path, table) for table, _ in CURRENT_METADATA_COLUMNS
    }
    phi_after_first = _column_names(db_path, "phi")

    with opened_anonymizer_model(db_url):
        pass
    columns_after_second = {
        table: _column_names(db_path, table) for table, _ in CURRENT_METADATA_COLUMNS
    }
    phi_after_second = _column_names(db_path, "phi")

    assert columns_after_first == columns_after_second
    assert phi_after_first == phi_after_second


def test_released_v19_0_10_db_gains_base_date_renames_and_folds_lookup(tmp_path: Path) -> None:
    db_path = tmp_path / "released.db"
    _create_released_v19_0_10_shaped_db(db_path)

    assert "base_date" not in _column_names(db_path, "phi")
    assert "pixel_phi" in _column_names(db_path, "instances")
    assert "pixel_phi_scanned" in _column_names(db_path, "series")
    assert LOOKUP_PATIENT_TABLE in _table_names(db_path)

    with opened_anonymizer_model(f"sqlite:///{db_path}") as model:
        assert model.series_embedded_phi_scanned("ase") is True

    assert "base_date" in _column_names(db_path, "phi")
    assert "embedded_phi" in _column_names(db_path, "instances")
    assert "pixel_phi" not in _column_names(db_path, "instances")
    assert "embedded_phi_scanned" in _column_names(db_path, "series")
    assert "pixel_phi_scanned" not in _column_names(db_path, "series")
    assert LOOKUP_PATIENT_TABLE not in _table_names(db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT embedded_phi FROM instances")).scalar() == "Jane Doe"
        row = conn.execute(
            text("SELECT anon_patient_id, date_offset, base_date FROM phi WHERE patient_id = 'MRN1'")
        ).fetchone()
    engine.dispose()
    assert row is not None
    assert row[0] == "SITE-1"
    assert row[1] == 42
    assert row[2] is None


def test_released_upgrade_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "released.db"
    _create_released_v19_0_10_shaped_db(db_path)
    db_url = f"sqlite:///{db_path}"

    with opened_anonymizer_model(db_url):
        pass
    after_first = {
        "phi": _column_names(db_path, "phi"),
        "instances": _column_names(db_path, "instances"),
        "series": _column_names(db_path, "series"),
        "tables": _table_names(db_path),
    }

    with opened_anonymizer_model(db_url):
        pass
    after_second = {
        "phi": _column_names(db_path, "phi"),
        "instances": _column_names(db_path, "instances"),
        "series": _column_names(db_path, "series"),
        "tables": _table_names(db_path),
    }

    assert after_first == after_second
