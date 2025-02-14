import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.anonymizer.model.anonymizer_sql import PHI, AnonymizerModelSQL, Base, Series, Study


@pytest.fixture
def db_session():
    """Fixture to create a fresh in-memory database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    session = Session()

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    # Create tables
    PHI.metadata.create_all(engine)
    Study.metadata.create_all(engine)
    Series.metadata.create_all(engine)

    yield session

    session.close()


def test_database_initialization(db_session):
    """Test if the database initializes correctly."""
    assert db_session.query(PHI).count() == 0
    assert db_session.query(Study).count() == 0
    assert db_session.query(Series).count() == 0


def test_insert_phi(db_session):
    """Test inserting a PHI record into the database."""
    new_phi = PHI(patient_id="12345", patient_name="John Doe")
    db_session.add(new_phi)
    db_session.commit()

    retrieved_phi = db_session.query(PHI).filter_by(patient_id="12345").first()
    assert retrieved_phi is not None
    assert retrieved_phi.patient_name == "John Doe"


def test_relationships(db_session):
    """Test if the database correctly commits relationships."""

    # Create PHI
    phi = PHI(patient_id="123456", patient_name="John Doe", sex="M", dob="1990-01-01", ethnic_group="Unknown")

    # Create Study
    study = Study(
        study_uid="1.2.3.4.5",
        patient_id="123456",
        source="Hospital A",
        study_date="2023-01-01",
        anon_date_delta=5,
        accession_number="ACC12345",
        study_desc="Chest X-ray",
        target_instance_count=10,
    )

    # Create Series
    series = Series(
        series_uid="6.7.8.9.10",
        study_uid="1.2.3.4.5",
        series_desc="Lung Scan",
        modality="CT",
        instance_count=100,
    )

    # Add relationships
    study.series.append(series)
    phi.studies.append(study)

    # Add to session and commit
    db_session.add(phi)
    db_session.commit()

    # Check if study was added correctly
    saved_study = db_session.query(Study).filter_by(study_uid="1.2.3.4.5").first()
    assert saved_study is not None
    assert saved_study.patient_id == "123456"
