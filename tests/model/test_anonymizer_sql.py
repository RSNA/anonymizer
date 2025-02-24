import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from anonymizer.model.project import ProjectModel
from src.anonymizer.model.anonymizer_sql import Base, AnonymizerModelSQL, PHI, Series, Study, UID
from pathlib import Path
import pytest

@pytest.fixture(scope="function")
def anonymizer_model():
    """Creates a fresh instance of AnonymizerModelSQL using an in-memory database."""
    test_db_url = "sqlite:///:memory:"  # Use in-memory database for testing
    model = AnonymizerModelSQL(
        site_id="TEST_SITE",
        uid_root="1.2.3",
        script_path=Path("src/anonymizer/assets/scripts/default-anonymizer.script"), 
        db_url=test_db_url
    )
    yield model
    model._session.close()  # Ensure session is closed after test

#Database

def test_anonymizer_model_initialization(anonymizer_model):
    """Ensure the anonymizer model initializes without errors and connects to the in-memory DB."""
    assert anonymizer_model is not None
    assert anonymizer_model._session is not None
    assert anonymizer_model._session.bind.url.database == ":memory:"

def test_database_insert_and_query(anonymizer_model):
    """Test inserting and retrieving PHI records."""
    new_phi = PHI(patient_id="test-patient-001", anon_patient_id="anon-001")
    anonymizer_model._session.add(new_phi)
    anonymizer_model._session.commit()

    retrieved_phi = anonymizer_model._session.query(PHI).filter_by(patient_id="test-patient-001").first()
    
    assert retrieved_phi is not None
    assert retrieved_phi.anon_patient_id == "anon-001"

#PHI

# Test for get_phi function
def test_get_phi(anonymizer_model):
    """Test fetching PHI record from the database using anonymized patient ID."""

    # Case 1: PHI record exists
    anon_patient_id_existing = "anon-patient-001"
    existing_phi = PHI(patient_id=anon_patient_id_existing, patient_name="John Doe", sex="M", dob="1990-01-01", ethnic_group="Caucasian")
    anonymizer_model._session.add(existing_phi)
    anonymizer_model._session.commit()

    fetched_phi = anonymizer_model.get_phi(anon_patient_id_existing)
    assert fetched_phi is not None
    assert fetched_phi.patient_id == anon_patient_id_existing
    assert fetched_phi.patient_name == "John Doe"

    # Case 2: PHI record does not exist
    anon_patient_id_nonexistent = "anon-patient-002"
    fetched_phi_nonexistent = anonymizer_model.get_phi(anon_patient_id_nonexistent)
    assert fetched_phi_nonexistent is None

# Test for get_phi_name function
def test_get_phi_name(anonymizer_model):
    """Test fetching patient's name from PHI table using anonymized patient ID."""

    # Case 1: PHI record exists with patient name
    anon_patient_id_existing = "anon-patient-001"
    existing_phi = PHI(patient_id=anon_patient_id_existing, patient_name="John Doe", sex="M", dob="1990-01-01", ethnic_group="Caucasian")
    anonymizer_model._session.add(existing_phi)
    anonymizer_model._session.commit()

    patient_name = anonymizer_model.get_phi_name(anon_patient_id_existing)
    assert patient_name == "John Doe"

    # Case 2: PHI record does not exist
    anon_patient_id_nonexistent = "anon-patient-002"
    patient_name_nonexistent = anonymizer_model.get_phi_name(anon_patient_id_nonexistent)
    assert patient_name_nonexistent is None

# Test for set_phi function
def test_set_phi(anonymizer_model):
    """Test inserting or updating PHI record in the database."""

    # Case 1: Insert a new PHI record
    anon_patient_id_new = "anon-patient-003"
    new_phi = PHI(patient_id=anon_patient_id_new, patient_name="Jane Doe", sex="F", dob="1992-02-02", ethnic_group="Asian")
    anonymizer_model.set_phi(anon_patient_id_new, new_phi)

    # Verify the new PHI record has been inserted
    inserted_phi = anonymizer_model._session.query(PHI).filter_by(patient_id=anon_patient_id_new).first()
    assert inserted_phi is not None
    assert inserted_phi.patient_name == "Jane Doe"

    # Case 2: Update an existing PHI record
    anon_patient_id_existing = "anon-patient-001"
    updated_phi = PHI(patient_id=anon_patient_id_existing, patient_name="John Smith", sex="M", dob="1990-01-01", ethnic_group="Caucasian")
    anonymizer_model.set_phi(anon_patient_id_existing, updated_phi)

    # Verify the existing PHI record has been updated
    updated_record = anonymizer_model._session.query(PHI).filter_by(patient_id=anon_patient_id_existing).first()
    assert updated_record is not None
    assert updated_record.patient_name == "John Smith"

    # Case 3: Ensure it doesn't insert a duplicate if same data is passed again
    anonymizer_model.set_phi(anon_patient_id_existing, updated_phi)
    duplicate_check = anonymizer_model._session.query(PHI).filter_by(patient_id=anon_patient_id_existing).count()
    assert duplicate_check == 1  # Ensure it hasn't created a second record


#Patient


def test_get_patient_id_count(anonymizer_model):
    """Ensure get_patient_id_count() correctly counts PHI records in the database."""
    assert anonymizer_model.get_patient_id_count() == 0  # Initially empty

    # Add a patient
    anonymizer_model._session.add(PHI(patient_id="test-patient-001", anon_patient_id="anon-001"))
    assert anonymizer_model.get_patient_id_count() == 1  # Should now return 1

    anonymizer_model._session.add(PHI(patient_id="test-patient-002", anon_patient_id="anon-002"))
    assert anonymizer_model.get_patient_id_count() == 2  # Should be 2 now

def test_set_and_get_anon_patient_id(anonymizer_model):
    """Ensure set_anon_patient_id updates an existing PHI record and get_anon_patient_id retrieves it."""
    
    # Insert a new PHI record manually
    new_phi = PHI(patient_id="test-patient-001", anon_patient_id="old-anon-001")
    anonymizer_model._session.add(new_phi)
    anonymizer_model._session.commit()

    # Update the anonymized patient ID
    anonymizer_model.set_anon_patient_id("test-patient-001", "anon-001")
    
    # Retrieve and validate
    retrieved_anon_id = anonymizer_model.get_anon_patient_id("test-patient-001")
    assert retrieved_anon_id == "anon-001"  # Should match updated ID

def test_set_anon_patient_id_no_phi(anonymizer_model):
    """Ensure set_anon_patient_id raises an error when the PHI record does not exist."""
    with pytest.raises(ValueError):
        anonymizer_model.set_anon_patient_id("non-existent-patient", "anon-999")

#UID

def test_uid_received(anonymizer_model):
    """Ensure uid_received() correctly detects if a UID exists in the database."""
    assert anonymizer_model.uid_received("phi-uid-123") is False  # Should not exist

    # Add a UID record
    anonymizer_model._session.add(UID(phi_uid="phi-uid-123", anon_uid="anon-uid-456"))
    anonymizer_model._session.commit()

    assert anonymizer_model.uid_received("phi-uid-123") is True  # Now it should exist

def test_get_anon_uid(anonymizer_model):
    """Ensure get_anon_uid() correctly retrieves anonymized UIDs."""
    phi_uid = "study-123"
    anon_uid = "anon-study-456"

    anonymizer_model.set_anon_uid(phi_uid, anon_uid)  # Store UID mapping
    retrieved_anon_uid = anonymizer_model.get_anon_uid(phi_uid)  # Retrieve it

    assert retrieved_anon_uid == anon_uid  # Should match what we set

def test_set_anon_uid(anonymizer_model):
    """Test setting anonymized UID for both existing and new mappings."""

    # Step 1: Case 1 - Insert a new UID mapping (when no entry exists)
    phi_uid_new = "phi-uid-1234"
    anon_uid_new = "anon-uid-1234"

    # Call the set_anon_uid function to insert a new mapping
    anonymizer_model.set_anon_uid(phi_uid_new, anon_uid_new)

    # Retrieve the newly inserted UID mapping
    uid_record = anonymizer_model._session.query(UID).filter_by(phi_uid=phi_uid_new).first()

    # Assertions for the new record
    assert uid_record is not None
    assert uid_record.phi_uid == phi_uid_new
    assert uid_record.anon_uid == anon_uid_new

    # Step 2: Case 2 - Update an existing UID mapping (change anon_uid)
    phi_uid_existing = "phi-uid-5678"
    anon_uid_existing = "anon-uid-5678"
    new_anon_uid = "anon-uid-updated"

    # Insert the initial record to update later
    anonymizer_model.set_anon_uid(phi_uid_existing, anon_uid_existing)

    # Call the set_anon_uid function to update the existing mapping
    anonymizer_model.set_anon_uid(phi_uid_existing, new_anon_uid)

    # Retrieve the updated UID mapping
    updated_uid_record = anonymizer_model._session.query(UID).filter_by(phi_uid=phi_uid_existing).first()

    # Assertions for the updated record
    assert updated_uid_record is not None
    assert updated_uid_record.phi_uid == phi_uid_existing
    assert updated_uid_record.anon_uid == new_anon_uid

def test_remove_uid(anonymizer_model):
    """Ensure remove_uid() correctly deletes a UID from the database."""
    anonymizer_model._session.add(UID(phi_uid="phi-uid-123", anon_uid="anon-uid-456"))
    anonymizer_model._session.commit()

    assert anonymizer_model.uid_received("phi-uid-123") is True  # Ensure it was added

    anonymizer_model.remove_uid("phi-uid-123")  # Remove UID
    assert anonymizer_model.uid_received("phi-uid-123") is False  # Should be gone

#Accession

def test_set_anon_acc_no(anonymizer_model):
    """Test setting an anonymized accession number for a study, with patient creation."""
    
    # Step 1: Create a PHI (patient)
    patient_id = "test-patient-001"
    anon_patient_id = "anon-001"
    phi_patient = PHI(patient_id=patient_id, anon_patient_id=anon_patient_id)
    anonymizer_model._session.add(phi_patient)
    anonymizer_model._session.commit()  # Commit to save the patient

    # Step 2: Create a Study and link it to the PHI (patient)
    study = Study(
        study_uid="study_1234",
        source="source_123",
        study_date="2025-02-01",
        anon_date_delta=0,
        accession_number="acc_no_1234",
        study_desc="Test Study",
        patient_id=patient_id  # Link to the patient via patient_id
    )
    anonymizer_model._session.add(study)
    anonymizer_model._session.commit()  # Commit to save the study

    # Step 3: Set the anonymized accession number for this study
    anonymizer_model.set_anon_acc_no("study_1234", "anon-accession-1234")

    # Step 4: Retrieve the study again and check if the anon_accession was updated
    updated_study = anonymizer_model._session.query(Study).filter_by(study_uid="study_1234").first()

    # Assertions
    assert updated_study is not None
    assert updated_study.anon_accession == "anon-accession-1234"
    assert updated_study.patient_id == patient_id  # Ensure the study is linked to the patient

#Instances



#Series



#Study



#Other
