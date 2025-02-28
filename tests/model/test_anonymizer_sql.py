import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from pydicom import Dataset
import pytest
from sqlalchemy import func

from src.anonymizer.model.anonymizer_sql import PHI, UID, AnonymizerModelSQL, Series, Study, TagKeep


@pytest.fixture(scope="function")
def anonymizer_model():
    """Creates a fresh instance of AnonymizerModelSQL using an in-memory database."""
    test_db_url = "sqlite:///:memory:"  # Use in-memory database for testing
    model = AnonymizerModelSQL(
        site_id="TEST_SITE",
        uid_root="1.2.3",
        script_path=Path("src/anonymizer/assets/scripts/default-anonymizer.script"),
        db_url=test_db_url,
    )
    yield model
    del model
    # model._session.close()  # Ensure session is closed after test


def test_is_tag_kept(anonymizer_model):
    """Test if is_tag_kept() correctly identifies kept tags."""
    anonymizer_model._session.add(TagKeep(tag="PatientName", operation="KEEP"))
    anonymizer_model._session.commit()

    assert anonymizer_model.is_tag_kept("PatientName") is True
    assert anonymizer_model.is_tag_kept("StudyInstanceUID") is False


def test_get_tag_operation(anonymizer_model):
    """Test if get_tag_operation() correctly retrieves operations."""
    anonymizer_model._session.add(TagKeep(tag="PatientName", operation="KEEP"))
    anonymizer_model._session.add(TagKeep(tag="StudyDate", operation="REMOVE"))
    anonymizer_model._session.commit()

    assert anonymizer_model.get_tag_operation("PatientName") == "KEEP"
    assert anonymizer_model.get_tag_operation("StudyDate") == "REMOVE"
    assert anonymizer_model.get_tag_operation("NonExistentTag") == ""


# Database


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


# Model functions


def test_get_class_name(anonymizer_model):
    """Test getting the class name."""

    # Check if the returned class name is correct
    assert anonymizer_model.get_class_name() == "AnonymizerModelSQL", "Class name returned is incorrect"


def test_repr(anonymizer_model):
    """Test the __repr__ function that provides a summary of the model."""

    # Mock the database queries to avoid hitting the actual DB
    with patch.object(anonymizer_model._session, "query") as mock_query:
        mock_query.return_value.count.return_value = 10  # Mock count for PHI, Study, Series
        mock_query.return_value.scalar.return_value = 100  # Mock sum for instances

        # Mock quarantined value
        anonymizer_model._quarantined = 5

        # Run the __repr__ method and check if it contains the expected info
        repr_output = repr(anonymizer_model)

        # Check if it contains the expected parts of the output
        assert "patients': 10" in repr_output
        assert "studies': 10" in repr_output
        assert "series': 10" in repr_output
        assert "instances': 100" in repr_output
        assert "quarantined': 5" in repr_output


def test_get_totals(anonymizer_model):
    """Test getting the totals for patients, studies, series, instances, and quarantined."""

    # Mock the database queries to avoid hitting the actual DB
    with patch.object(anonymizer_model._session, "query") as mock_query:
        mock_query.return_value.count.return_value = 10  # Mock count for PHI, Study, Series
        mock_query.return_value.scalar.return_value = 100  # Mock sum for instances

        # Mock quarantined value
        anonymizer_model._quarantined = 5

        # Run the get_totals method and verify the returned object
        totals = anonymizer_model.get_totals()

        # Check if the returned totals match the mocked values
        assert totals.patients == 10, "Patients count is incorrect"
        assert totals.studies == 10, "Studies count is incorrect"
        assert totals.series == 10, "Series count is incorrect"
        assert totals.instances == 100, "Instances count is incorrect"
        assert totals.quarantined == 5, "Quarantined count is incorrect"


def test_save_success(anonymizer_model):
    """Test that save() commits the session successfully."""
    new_patient = PHI(patient_id="12345", anon_patient_id="ANON-12345")
    anonymizer_model._session.add(new_patient)

    assert anonymizer_model.save() is True  # Check that save() returns True

    # Verify data was actually committed
    result = anonymizer_model._session.query(PHI).filter_by(patient_id="12345").first()
    assert result is not None
    assert result.anon_patient_id == "ANON-12345"


def test_save_failure(anonymizer_model):
    """Test that save() rolls back on failure."""
    with patch.object(anonymizer_model._session, "commit", side_effect=Exception("DB error")):
        assert anonymizer_model.save() is False  # Should return False on failure


# Load_script function tests


def test_load_script_real_data(anonymizer_model):
    """Test loading the real anonymization script file."""

    script_path = Path("src/anonymizer/assets/scripts/default-anonymizer.script")
    assert script_path.exists(), f"Script file not found: {script_path}"

    # Run the function
    anonymizer_model.load_script(script_path)

    # Fetch some known entries from the script and check the database
    known_tags = {"00080001": "@remove()", "00080005": "", "00080006": "@remove()", "00080008": ""}

    for tag, expected_op in known_tags.items():
        db_entry = anonymizer_model._session.query(TagKeep).filter_by(tag=tag).first()
        if "@remove" in expected_op:
            assert db_entry is None  # Should not be stored
        else:
            assert db_entry is not None and db_entry.operation == expected_op


def test_load_script_twice(anonymizer_model):
    """Ensure running load_script twice does not duplicate entries."""

    script_path = Path("src/anonymizer/assets/scripts/default-anonymizer.script")
    assert script_path.exists(), f"Script file not found: {script_path}"

    anonymizer_model.load_script(script_path)
    first_count = anonymizer_model._session.query(TagKeep).count()

    anonymizer_model.load_script(script_path)
    second_count = anonymizer_model._session.query(TagKeep).count()

    assert first_count == second_count, "Duplicate entries were created!"


def test_load_script_invalid_file(anonymizer_model):
    """Test behavior when an invalid script file is provided."""

    invalid_script_path = Path("non_existent_script.xml")

    with pytest.raises(FileNotFoundError):
        anonymizer_model.load_script(invalid_script_path)


def test_load_script_corrupt_xml(anonymizer_model, tmp_path):
    """Test behavior when a corrupt XML file is used."""

    corrupt_script = tmp_path / "corrupt.script"
    corrupt_script.write_text("<script><e t='00080001'>@remove()")  # Malformed XML

    with pytest.raises(ET.ParseError):
        anonymizer_model.load_script(corrupt_script)


def test_load_script_update_existing(anonymizer_model):
    """Test updating existing tag operations using the real script file."""

    script_path = Path("src/anonymizer/assets/scripts/default-anonymizer.script")
    assert script_path.exists(), f"Script file not found: {script_path}"

    tag_to_test = "00080005"

    # Ensure the tag is in a known state before the test
    existing_entry = anonymizer_model._session.query(TagKeep).filter_by(tag=tag_to_test).first()
    if existing_entry:
        existing_entry.operation = "OLD_VALUE"
    else:
        anonymizer_model._session.add(TagKeep(tag=tag_to_test, operation="OLD_VALUE"))

    anonymizer_model._session.commit()  # Save changes before running load_script

    # Run the function to load the script
    anonymizer_model.load_script(script_path)

    # Check if the existing entry was updated
    tag_entry = anonymizer_model._session.query(TagKeep).filter_by(tag=tag_to_test).first()
    assert tag_entry is not None and tag_entry.operation == "", f"Tag {tag_to_test} operation was not updated correctly"


def test_load_script_empty(anonymizer_model, tmp_path):
    """Test loading an empty XML file (should insert nothing)."""

    script_path_empty = tmp_path / "empty_script.xml"
    script_path_empty.write_text("<?xml version='1.0'?><script></script>")

    initial_count = anonymizer_model._session.query(TagKeep).count()

    anonymizer_model.load_script(script_path_empty)

    assert anonymizer_model._session.query(TagKeep).count() == initial_count, (
        "Empty script should not insert any records"
    )


# PHI


# Test for get_phi function
def test_get_phi(anonymizer_model):
    """Test fetching PHI record from the database using anonymized patient ID."""

    # Case 1: PHI record exists
    anon_patient_id_existing = "anon-patient-001"
    existing_phi = PHI(
        patient_id=anon_patient_id_existing,
        patient_name="John Doe",
        sex="M",
        dob="1990-01-01",
        ethnic_group="Caucasian",
    )
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
    existing_phi = PHI(
        patient_id=anon_patient_id_existing,
        patient_name="John Doe",
        sex="M",
        dob="1990-01-01",
        ethnic_group="Caucasian",
    )
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
    new_phi = PHI(
        patient_id=anon_patient_id_new, patient_name="Jane Doe", sex="F", dob="1992-02-02", ethnic_group="Asian"
    )
    anonymizer_model.set_phi(anon_patient_id_new, new_phi)

    # Verify the new PHI record has been inserted
    inserted_phi = anonymizer_model._session.query(PHI).filter_by(patient_id=anon_patient_id_new).first()
    assert inserted_phi is not None
    assert inserted_phi.patient_name == "Jane Doe"

    # Case 2: Update an existing PHI record
    anon_patient_id_existing = "anon-patient-001"
    updated_phi = PHI(
        patient_id=anon_patient_id_existing,
        patient_name="John Smith",
        sex="M",
        dob="1990-01-01",
        ethnic_group="Caucasian",
    )
    anonymizer_model.set_phi(anon_patient_id_existing, updated_phi)

    # Verify the existing PHI record has been updated
    updated_record = anonymizer_model._session.query(PHI).filter_by(patient_id=anon_patient_id_existing).first()
    assert updated_record is not None
    assert updated_record.patient_name == "John Smith"

    # Case 3: Ensure it doesn't insert a duplicate if same data is passed again
    anonymizer_model.set_phi(anon_patient_id_existing, updated_phi)
    duplicate_check = anonymizer_model._session.query(PHI).filter_by(patient_id=anon_patient_id_existing).count()
    assert duplicate_check == 1  # Ensure it hasn't created a second record


# Patient


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


# UID


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


def test_remove_uid_inverse(anonymizer_model):
    """Test removing a UID record by anonymized UID."""
    # Insert a test UID record
    phi_uid = "1.2.3.4.5"
    anon_uid = "1.2.3.TEST.1"
    uid_entry = UID(phi_uid=phi_uid, anon_uid=anon_uid)
    anonymizer_model._session.add(uid_entry)
    anonymizer_model._session.commit()

    # Ensure the UID record exists
    assert anonymizer_model._session.query(UID).filter_by(anon_uid=anon_uid).first() is not None

    # Remove the UID by anon_uid
    anonymizer_model.remove_uid_inverse(anon_uid)

    # Ensure the UID record is deleted
    assert anonymizer_model._session.query(UID).filter_by(anon_uid=anon_uid).first() is None


def test_get_uid_count(anonymizer_model):
    """Test retrieving the count of UID mappings in the database."""
    # Ensure initial count is zero
    assert anonymizer_model.get_uid_count() == 0

    # Insert some UID mappings
    anonymizer_model._session.add_all(
        [
            UID(phi_uid="1.2.3.4.1", anon_uid="1.2.3.TEST.1"),
            UID(phi_uid="1.2.3.4.2", anon_uid="1.2.3.TEST.2"),
            UID(phi_uid="1.2.3.4.3", anon_uid="1.2.3.TEST.3"),
        ]
    )
    anonymizer_model._session.commit()

    # Ensure count is correct
    assert anonymizer_model.get_uid_count() == 3


def test_get_next_anon_uid(anonymizer_model):
    """Test generating and storing a new anonymized UID."""
    phi_uid_1 = "1.2.3.4.1"
    phi_uid_2 = "1.2.3.4.2"

    # Generate the first anonymized UID
    anon_uid_1 = anonymizer_model.get_next_anon_uid(phi_uid_1)
    assert anon_uid_1.startswith(anonymizer_model._uid_prefix)  # Check prefix
    assert anonymizer_model._session.query(UID).filter_by(phi_uid=phi_uid_1).first() is not None

    # Generate a second anonymized UID and check it's incremented
    anon_uid_2 = anonymizer_model.get_next_anon_uid(phi_uid_2)
    assert anon_uid_2.startswith(anonymizer_model._uid_prefix)
    assert anon_uid_2 != anon_uid_1  # Ensure it's a new unique UID

    # Ensure the UID count is updated correctly
    assert anonymizer_model.get_uid_count() == 2


# Accession


def test_get_next_anon_acc_no(anonymizer_model):
    """Test that get_next_anon_acc_no assigns sequential anonymized accession numbers correctly."""
    session = anonymizer_model._session

    # Ensure database starts empty
    assert session.query(Study).count() == 0

    # Call function before inserting any studies
    anon_acc_no_1 = anonymizer_model.get_next_anon_acc_no("PHI_ACC_001")
    assert anon_acc_no_1 == "1"  # First accession number should be 1

    # Insert a study with anon_accession_number_count = 5
    study = Study(
        study_uid="1.2.3.4",
        patient_id="PATIENT_001",
        anon_accession_number_count=5,  # Simulating an existing record
        anon_accession_number="5"
    )
    session.add(study)
    session.commit()

    # Call function again to get the next available number
    anon_acc_no_2 = anonymizer_model.get_next_anon_acc_no("PHI_ACC_002")
    assert anon_acc_no_2 == "6"  # Should increment from 5 to 6

    # Insert another study with anon_accession_number_count = 10
    study_2 = Study(
        study_uid="1.2.3.5",
        patient_id="PATIENT_002",
        anon_accession_number_count=10,
        anon_accession_number="10"
    )
    session.add(study_2)
    session.commit()

    # Call function again
    anon_acc_no_3 = anonymizer_model.get_next_anon_acc_no("PHI_ACC_003")
    assert anon_acc_no_3 == "11"  # Should increment from 10 to 11


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
        patient_id=patient_id,  # Link to the patient via patient_id
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


def test_get_anon_acc_no(anonymizer_model):
    """Test retrieving the anonymized accession number for a given PHI accession number."""

    # Create and insert a PHI (patient) entry first
    patient_id = "test-patient-001"
    anonymizer_model._session.add(PHI(patient_id=patient_id, anon_patient_id="anon-001"))
    anonymizer_model._session.commit()

    phi_acc_no = "ACC-12345"
    anon_acc_no = "ANON-54321"

    # Insert a study with a valid patient ID and accession number mapping
    study_entry = Study(
        study_uid="STUDY-001",
        patient_id=patient_id,  # FK to PHI table
        accession_number=phi_acc_no,
        anon_accession_number=anon_acc_no,
    )
    anonymizer_model._session.add(study_entry)
    anonymizer_model._session.commit()

    # Retrieve anonymized accession number
    retrieved_anon_acc_no = anonymizer_model.get_anon_acc_no(phi_acc_no)

    # Ensure the retrieved value matches expected
    assert retrieved_anon_acc_no == anon_acc_no

    # Test case: Accessing non-existent accession number should return None
    assert anonymizer_model.get_anon_acc_no("NON_EXISTENT_ACC") is None


def test_get_acc_no_count(anonymizer_model):
    """Test retrieving the highest anonymized accession number count."""

    # Ensure initial count is zero
    assert anonymizer_model.get_acc_no_count() == 0

    # Create and insert a PHI (patient) entry first
    patient_id = "test-patient-002"
    anonymizer_model._session.add(PHI(patient_id=patient_id, anon_patient_id="anon-002"))
    anonymizer_model._session.commit()

    # Insert studies with a valid patient ID and different accession number counts
    anonymizer_model._session.add_all(
        [
            Study(
                study_uid="STUDY-002",
                patient_id=patient_id,
                accession_number="ACC-1",
                anon_accession_number="ANON-1",
                anon_accession_number_count=1,
            ),
            Study(
                study_uid="STUDY-003",
                patient_id=patient_id,
                accession_number="ACC-2",
                anon_accession_number="ANON-2",
                anon_accession_number_count=2,
            ),
            Study(
                study_uid="STUDY-004",
                patient_id=patient_id,
                accession_number="ACC-3",
                anon_accession_number="ANON-3",
                anon_accession_number_count=5,
            ),
        ]
    )
    anonymizer_model._session.commit()

    # Ensure highest accession number count is returned
    assert anonymizer_model.get_acc_no_count() == 5


# Instances


def test_get_stored_instance_count(anonymizer_model):
    """Test retrieving the number of stored instances for a given patient and study."""

    # Create and insert a PHI (patient)
    patient_id = "test-patient-003"
    anonymizer_model._session.add(PHI(patient_id=patient_id, anon_patient_id="anon-003"))
    anonymizer_model._session.commit()

    # Create and insert a Study entry
    study_uid = "STUDY-005"
    anonymizer_model._session.add(Study(study_uid=study_uid, patient_id=patient_id))
    anonymizer_model._session.commit()

    # Ensure count is zero before adding Series data
    assert anonymizer_model.get_stored_instance_count(patient_id, study_uid) == 0

    # Insert multiple Series linked to the Study
    anonymizer_model._session.add_all(
        [
            Series(series_uid="SERIES-001", study_uid=study_uid, instance_count=3),
            Series(series_uid="SERIES-002", study_uid=study_uid, instance_count=5),
        ]
    )
    anonymizer_model._session.commit()

    # Ensure total stored instance count is correct (3+5=8)
    assert anonymizer_model.get_stored_instance_count(patient_id, study_uid) == 8

    # Test case: If study UID does not exist, should return 0
    assert anonymizer_model.get_stored_instance_count(patient_id, "NON_EXISTENT_STUDY") == 0

    # Test case: If patient ID does not exist, should return 0
    assert anonymizer_model.get_stored_instance_count("NON_EXISTENT_PATIENT", study_uid) == 0


def test_get_pending_instance_count(anonymizer_model):
    """Test retrieving pending instance count for a study."""

    # Create and insert a PHI (patient)
    patient_id = "test-patient-004"
    anonymizer_model._session.add(PHI(patient_id=patient_id, anon_patient_id="anon-004"))
    anonymizer_model._session.commit()

    # Create and insert a Study entry
    study_uid = "STUDY-006"
    target_instance_count = 10  # Expected number of instances
    anonymizer_model._session.add(Study(study_uid=study_uid, patient_id=patient_id))
    anonymizer_model._session.commit()

    # Ensure all instances are pending before any Series data
    assert anonymizer_model.get_pending_instance_count(patient_id, study_uid, target_instance_count) == 10

    # Insert multiple Series linked to the Study
    anonymizer_model._session.add_all(
        [
            Series(series_uid="SERIES-003", study_uid=study_uid, instance_count=4),
            Series(series_uid="SERIES-004", study_uid=study_uid, instance_count=3),
        ]
    )
    anonymizer_model._session.commit()

    # Ensure pending instance count is correct (10 - (4+3) = 3)
    assert anonymizer_model.get_pending_instance_count(patient_id, study_uid, target_instance_count) == 3

    # Test case: If study does not exist, should return target count
    assert anonymizer_model.get_pending_instance_count(patient_id, "NON_EXISTENT_STUDY", target_instance_count) == 10

    # Test case: If patient does not exist, should return target count
    assert anonymizer_model.get_pending_instance_count("NON_EXISTENT_PATIENT", study_uid, target_instance_count) == 10


# Series


def test_series_complete(anonymizer_model):
    """Test checking if a series is complete based on instance count."""

    # Create mock study and series data
    ptid = "anon-pt-123"
    study_uid = "study-123"
    series_uid = "series-123"
    target_count = 10

    # Insert a series with fewer instances than the target
    series_entry = Series(series_uid=series_uid, study_uid=study_uid, instance_count=5)
    anonymizer_model._session.add(series_entry)
    anonymizer_model._session.commit()

    # Check that the series is NOT complete
    assert not anonymizer_model.series_complete(ptid, study_uid, series_uid, target_count), (
        "Series should not be complete"
    )

    # Update instance count to meet target
    anonymizer_model._session.query(Series).filter_by(series_uid=series_uid).update({"instance_count": 10})
    anonymizer_model._session.commit()

    # Check that the series is now complete
    assert anonymizer_model.series_complete(ptid, study_uid, series_uid, target_count), (
        "Series should be complete when instance count meets target"
    )

    # Check with a higher target count (should return False)
    assert not anonymizer_model.series_complete(ptid, study_uid, series_uid, 15), (
        "Series should not be complete when instance count is below target"
    )


# Study


def test_new_study_from_dataset(anonymizer_model):
    """Test creating a new study from a dataset and ensuring it is linked to a valid patient."""

    new_phi = PHI(patient_id="test-patient-001", anon_patient_id="old-anon-001")
    anonymizer_model._session.add(new_phi)
    anonymizer_model._session.commit()

    # Mock a DICOM dataset with a patient ID
    ds = Dataset()
    ds.PatientID = "test-patient-001"
    ds.StudyInstanceUID = "1.2.3.4.5"
    ds.StudyDate = "20240226"
    ds.AccessionNumber = "A12345"
    ds.StudyDescription = "Test Study"
    ds.SeriesInstanceUID = "1.2.3.4.5.6"
    ds.SeriesDescription = "Test Series"
    ds.Modality = "CT"

    source = "TEST_SOURCE"
    date_delta = 5

    # Check the max anon_accession_number_count before adding
    prev_max_count = anonymizer_model._session.query(func.max(Study.anon_accession_number_count)).scalar() or 0

    # Call the function
    anonymizer_model.new_study_from_dataset(ds, source, date_delta)

    # Ensure the study is linked to the correct patient
    stored_study = anonymizer_model._session.query(Study).filter_by(study_uid="1.2.3.4.5").first()
    assert stored_study is not None, "Study was not inserted into the database"
    assert stored_study.patient_id == "test-patient-001", "Study is not linked to the correct patient"

    # Verify anon_accession_number_count is correctly incremented
    assert stored_study.anon_accession_number_count == prev_max_count + 1, \
        "anon_accession_number_count was not correctly incremented"

    # Ensure anon_accession_number is stored as a string
    assert stored_study.anon_accession_number == str(prev_max_count + 1), \
        "anon_accession_number is not stored as a string"

    # Ensure study metadata is correctly set
    assert stored_study.study_date == "20240226"
    assert stored_study.accession_number == "A12345"
    assert stored_study.study_desc == "Test Study"
    assert stored_study.source == "TEST_SOURCE"

    # Ensure a Series is also created
    stored_series = anonymizer_model._session.query(Series).filter_by(series_uid="1.2.3.4.5.6").first()
    assert stored_series is not None, "Series was not inserted into the database"
    assert stored_series.series_desc == "Test Series"
    assert stored_series.modality == "CT"
    assert stored_series.instance_count == 1

    print("Test passed: new_study_from_dataset correctly assigns patient_id and works as expected!")


# Quarantined


def test_increment_quarantined(anonymizer_model):
    """Test incrementing the quarantined counter."""

    initial_value = anonymizer_model._quarantined

    # Increment the counter
    anonymizer_model.increment_quarantined()

    # Check if the counter was incremented
    assert anonymizer_model._quarantined == initial_value + 1, "Quarantined counter did not increment correctly"
