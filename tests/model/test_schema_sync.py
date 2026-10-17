"""Tests for SQLite schema sync on AnonymizerModel open."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydicom import Dataset
from sqlalchemy import create_engine, text

from anonymizer.controller.phi.phi_io import build_phi_index
from tests.opened_anonymizer_model import opened_anonymizer_model

V3_METADATA_COLUMNS = (
    ("instances", "embedded_phi"),
    ("series", "harmonized_description"),
    ("series", "face_blur_algorithm_applied"),
    ("studies", "harmonized_description"),
)

LOOKUP_PATIENT_TABLE = "lookup_patient"
PHI_BASE_DATE_COLUMN = "base_date"


def _create_v2_shaped_db(db_path: Path) -> None:
    """Create a pre-v3 anonymizer.db schema (no metadata columns)."""
    engine = create_engine(f"sqlite:///{db_path}")
    statements = [
        """
        CREATE TABLE phi (
            patient_id TEXT PRIMARY KEY,
            anon_patient_id TEXT NOT NULL UNIQUE,
            patient_name TEXT,
            sex TEXT,
            dob TEXT,
            ethnic_group TEXT
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
            FOREIGN KEY(study_uid) REFERENCES studies(study_uid)
        )
        """,
        """
        CREATE TABLE instances (
            sop_instance_uid TEXT PRIMARY KEY,
            anon_sop_instance_uid TEXT NOT NULL UNIQUE,
            series_uid TEXT NOT NULL,
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
        INSERT INTO phi (patient_id, anon_patient_id)
        VALUES ('', '574856-000000')
        """,
    ]
    with engine.connect() as conn:
        for statement in statements:
            conn.execute(text(statement))
        conn.commit()
    engine.dispose()


def _column_names(db_path: Path, table_name: str) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        names = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})"))}
    engine.dispose()
    return names


@pytest.fixture
def mock_dataset() -> Dataset:
    ds = Dataset()
    ds.PatientID = "574856-000099"
    ds.PatientName = "Legacy^Patient"
    ds.StudyInstanceUID = "1.2.3.4.5.6.7.8.9.0"
    ds.SeriesInstanceUID = "1.2.3.4.5.6.7.8.9.1"
    ds.SOPInstanceUID = "1.2.3.4.5.6.7.8.9.2"
    ds.Modality = "CT"
    ds.StudyDate = "20240101"
    ds.SeriesDescription = "Legacy Series"
    ds.StudyDescription = "Legacy Study"
    return ds


def test_lookup_patient_table_absent_and_phi_has_base_date(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    with opened_anonymizer_model(f"sqlite:///{db_path}"):
        pass
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
    engine.dispose()
    assert LOOKUP_PATIENT_TABLE not in tables
    assert PHI_BASE_DATE_COLUMN in _column_names(db_path, "phi")


def test_legacy_lookup_patient_migrates_into_phi_then_dropped(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_lookup.db"
    _create_v2_shaped_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE phi ADD COLUMN date_offset INTEGER"))
        conn.execute(
            text(
                """
                CREATE TABLE lookup_patient (
                    patient_id TEXT PRIMARY KEY,
                    anon_patient_id TEXT NOT NULL,
                    date_offset INTEGER,
                    basedate TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO lookup_patient (patient_id, anon_patient_id, date_offset, basedate) "
                "VALUES ('MRN1', 'SITE-1', 42, '20180327')"
            )
        )
        conn.commit()
    engine.dispose()

    with opened_anonymizer_model(f"sqlite:///{db_path}"):
        pass

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        row = conn.execute(
            text("SELECT anon_patient_id, date_offset, base_date FROM phi WHERE patient_id = 'MRN1'")
        ).fetchone()
    engine.dispose()
    assert LOOKUP_PATIENT_TABLE not in tables
    assert row is not None
    assert row[0] == "SITE-1"
    assert row[1] == 42
    assert row[2] == "20180327"


def test_ensure_schema_columns_adds_v3_metadata_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_v2.db"
    _create_v2_shaped_db(db_path)

    for table_name, column_name in V3_METADATA_COLUMNS:
        assert column_name not in _column_names(db_path, table_name)

    with opened_anonymizer_model(f"sqlite:///{db_path}"):
        pass

    for table_name, column_name in V3_METADATA_COLUMNS:
        assert column_name in _column_names(db_path, table_name)


def test_legacy_pixel_phi_columns_are_renamed_with_data(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_pixel_phi.db"
    _create_v2_shaped_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE instances ADD COLUMN pixel_phi TEXT"))
        conn.execute(text("ALTER TABLE series ADD COLUMN pixel_phi_scanned BOOLEAN NOT NULL DEFAULT 0"))
        conn.execute(text("INSERT INTO studies (study_uid, anon_study_uid, patient_id, source, study_date, anon_date_delta) VALUES ('s','as','','x','20240101',0)"))
        conn.execute(text("INSERT INTO series (series_uid, anon_series_uid, study_uid, pixel_phi_scanned) VALUES ('se','ase','s',1)"))
        conn.execute(text("INSERT INTO instances (sop_instance_uid, anon_sop_instance_uid, series_uid, pixel_phi) VALUES ('i','ai','se','Jane Doe')"))
        conn.commit()
    engine.dispose()

    with opened_anonymizer_model(f"sqlite:///{db_path}") as model:
        assert model.series_embedded_phi_scanned("ase") is True

    assert "pixel_phi" not in _column_names(db_path, "instances")
    assert "pixel_phi_scanned" not in _column_names(db_path, "series")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT embedded_phi FROM instances")).scalar() == "Jane Doe"
    engine.dispose()


def test_ensure_schema_columns_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_v2.db"
    _create_v2_shaped_db(db_path)
    db_url = f"sqlite:///{db_path}"

    with opened_anonymizer_model(db_url):
        pass
    columns_after_first_open = {table: _column_names(db_path, table) for table, _ in V3_METADATA_COLUMNS}

    with opened_anonymizer_model(db_url):
        pass
    columns_after_second_open = {table: _column_names(db_path, table) for table, _ in V3_METADATA_COLUMNS}

    assert columns_after_first_open == columns_after_second_open


def test_get_phi_index_after_schema_sync(tmp_path: Path, mock_dataset: Dataset) -> None:
    db_path = tmp_path / "legacy_v2.db"
    _create_v2_shaped_db(db_path)

    with opened_anonymizer_model(f"sqlite:///{db_path}") as model:
        model.capture_phi(source="pytest", ds=mock_dataset, date_offset_from_hash=0)

        records = build_phi_index(model)
        assert records is not None
        assert len(records) >= 1
        assert records[-1].phi_patient_id == mock_dataset.PatientID
