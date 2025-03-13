"""
This module contains the AnonymizerModel class, which is responsible for storing PHI (Protected Health Information)
and anonymization lookups. It also includes data classes for Series, Study, and PHI, as well as a Totals namedtuple.
"""

from contextlib import contextmanager
import logging
import threading
import xml.etree.ElementTree as ET
from collections import namedtuple
from dataclasses import dataclass, fields
from pathlib import Path
from pprint import pformat
from typing import ClassVar, Dict, List, Optional, Set, Tuple

from pydicom import Dataset
from pydicom.valuerep import PersonName
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, relationship, scoped_session, sessionmaker, Session

from anonymizer.model.project import DICOMNode
from anonymizer.utils.storage import JavaAnonymizerExportedStudy

logger = logging.getLogger(__name__)
Base = declarative_base()


class Series(Base):
    __tablename__ = "Series"

    study_uid = Column(String, ForeignKey("Study.study_uid"))

    series_uid = Column(String, primary_key=True)
    series_desc = Column(String, nullable=True)
    modality = Column(String)
    instance_count = Column(Integer, default=0)


class Study(Base):
    __tablename__ = "Study"  # What the table name in the db is called, links the class to the table

    study_uid = Column(String, primary_key=True)  # unique, non-nullable, required, PK
    phi_pk = Column(Integer, ForeignKey("PHI.phi_pk"), nullable=False)

    source = Column(String)
    study_date = Column(String)
    anon_date_delta = Column(Integer)
    accession_number = Column(String, index=True)
    anon_accession_number_count = Column(Integer, index=True, autoincrement=True, unique=True)
    anon_accession_number = Column(String, index=True)
    study_desc = Column(String, nullable=True)
    target_instance_count = Column(Integer, default=0)

    series = relationship("Series", cascade="all, delete-orphan")  # Creating one-to-many linking relationship


class PHI(Base):
    __tablename__ = "PHI"

    phi_pk = Column(Integer, primary_key=True)
    patient_id = Column(String, nullable=True)
    anon_patient_id = Column(String, index=True)
    patient_name = Column(String, nullable=True)
    sex = Column(String, nullable=True)
    dob = Column(String, nullable=True)
    ethnic_group = Column(String, nullable=True)

    studies = relationship("Study", cascade="all, delete-orphan")


# Used to map DICOM UIDs to anon UIDs
class UID(Base):
    __tablename__ = "UID"

    uid_pk = Column(Integer, primary_key=True)
    anon_uid = Column(String, index=True)
    phi_uid = Column(String, index=True)


# DICOM tags to keep after anonomization
class TagKeep(Base):
    __tablename__ = "tag_keep"

    tag = Column(String, primary_key=True)
    operation = Column(String)


@dataclass
class PHI_IndexRecord:
    anon_patient_id: str
    anon_patient_name: str
    phi_patient_name: str
    phi_patient_id: str
    date_offset: int
    phi_study_date: str
    anon_accession: str
    phi_accession: str
    anon_study_uid: str
    phi_study_uid: str
    num_series: int
    num_instances: int

    field_titles: ClassVar[Dict[str, str]] = {
        "anon_patient_id": "ANON-PatientID",
        "anon_patient_name": "ANON-PatientName",
        "phi_patient_name": "PHI-PatientName",
        "phi_patient_id": "PHI-PatientID",
        "date_offset": "DateOffset",
        "phi_study_date": "PHI-StudyDate",
        "anon_accession": "ANON-AccNo",
        "phi_accession": "PHI-AccNo",
        "anon_study_uid": "ANON-StudyUID",
        "phi_study_uid": "PHI-StudyUID",
        "num_series": "Series",
        "num_instances": "Instances",
    }

    @classmethod
    def get_field_titles(cls) -> list:
        return [cls.field_titles.get(field.name) for field in fields(cls)]

    def flatten(self) -> Tuple:
        return tuple(getattr(self, field.name) for field in fields(self))

    @classmethod
    def get_field_names(cls) -> list:
        return [field.name for field in fields(cls)]


# Data type used to return the counts of the different data types, not a var that is used, a type that is used
Totals = namedtuple("Totals", ["patients", "studies", "series", "instances", "quarantined"])

# TODO: change AnonymizerController "def load_model(self) -> AnonymizerModel:" to load from the database instead
# lookup function to find if accession number exits: get_anon_acc_num
# check get_next_anon_acc_no


class AnonymizerModel:
    """
    The Anonymizer data model class to store PHI (Protected Health Information) and anonymization lookups.
    """

    # Model Version Control
    MODEL_VERSION = 2
    MAX_PATIENTS = 1000000  # 1 million patients

    # _lock = threading.Lock()

    # ✅ Changed
    def __init__(self, site_id: str, uid_root: str, script_path: Path, db_url: str = "sqlite:///anonymizer.db"):
        """
        Initializes an instance of the AnonymizerModelSQL class.

        Args:
            site_id (str): The site ID.
            uid_root (str): The UID root.
            script_path (Path): The path to the script.
            db_url (str): The database URL (default: SQLite file `anonymizer.db`).
        """

        self._version = AnonymizerModel.MODEL_VERSION
        self._site_id = site_id
        self._uid_root = uid_root
        self._script_path = script_path

        self._uid_prefix = f"{self._uid_root}.{self._site_id}"
        self.default_anon_pt_id: str = site_id + "-" + "".zfill(len(str(self.MAX_PATIENTS)) - 1)

        # Database connection
        self.engine = create_engine(db_url, echo=False)  
        self.session_factory = scoped_session(sessionmaker(bind=self.engine)) #session factory that can generate new Session instances for multiple threads.

        # Create tables if they don't exist
        Base.metadata.create_all(self.engine)

        # Initialize quarantined totals
        self._quarantined = 0  # TODO: Implement quarantined tracking, send it quarantined directory to count

        self._tag_keep: Dict[str, str] = {}

        # Use session context manager for DB operations
        self.load_tag_keep()
        self.add_default()

        self.load_script(script_path)

    # Database manager

    @contextmanager
    def get_session(self):
        """Provides a scoped SQLAlchemy session."""
        session = self.session_factory()
        try:
            yield session #yields the session, all changes before a commit are in memory only, Every session starts a transaction implicitly.
            session.commit() # Writes all changes to the database permanently.
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # Model functions

    # # ✅Added, ⭕ needs testing
    # def __del__(self):
    #     """Ensure the database session is closed properly when the instance is deleted."""
    #     try:
    #         self.SessionFactory.remove()  # Closes all sessions in the scoped session
    #     except Exception as e:
    #         logger.error(f"Fatal Error in __del__, error: {e}")

    # ✅ Changed, ✅ Tested
    def get_class_name(self) -> str:
        return self.__class__.__name__

    # ✅ Changed, ✅ Tested
    def __repr__(self) -> str:
        """Returns a summary of the model"""
        with self.get_session() as session:
            num_patients = session.query(PHI).count()
            num_studies = session.query(Study).count()
            num_series = session.query(Series).count()
            num_instances = session.query(func.sum(Study.target_instance_count)).scalar() or 0

        model_summary = {
            "site_id": self._site_id,
            "uid_root": self._uid_root,
            "patients": num_patients,
            "studies": num_studies,
            "series": num_series,
            "instances": num_instances,
            "quarantined": self._quarantined,  # TODO: Implement quarantined tracking in DB
        }

        return f"{self.get_class_name()}\n({pformat(model_summary)})"

    # ✅ Changed, ✅ Tested
    def get_totals(self) -> Totals:
        with self.get_session() as session:
            return Totals(
                session.query(PHI).count(),
                session.query(Study).count(),
                session.query(Series).count(),
                session.query(func.sum(Study.target_instance_count)).scalar() or 0,
                self._quarantined,
            )

    # ✅ Changed, ✅ Tested
    def save(self) -> bool:
        """
        Commits the current state of the database session to persist all changes.

        Returns:
            bool: True if the commit was successful, False otherwise.
        """
        try:
            with self.get_session() as session:
                session.commit()
                logger.debug("Anonymizer Model changes committed to the database.")
            return True
        except Exception as e:
            logger.error(f"Fatal Error in save, error: {e}")
            return False

    # ✅Added, ✅ Tested
    def add_default(self):
        """
        Ensures a default PHI record exists in the database.
        """
        with self.get_session() as session:
            # Check if the default user already exists
            existing_phi = session.query(PHI).filter_by(anon_patient_id=self.default_anon_pt_id).first()
            if existing_phi:
                return

            default_phi = PHI(patient_id="", anon_patient_id=self.default_anon_pt_id)
            session.add(default_phi)

    # load_script

    # ✅ Changed, ✅ Tested
    def load_script(self, script_path: Path):
        """
        Load and parse an anonymize script file and store tag operations in the database.

        Args:
            script_path (Path): The path to the script file.

        Raises:
            FileNotFoundError: If the script file is not found.
            ET.ParseError: If there is an error parsing the script file.
            Exception: If there is any other generic exception.

        Returns:
            None
        """
        logger.info(f"Load script file: {script_path} to create AnonymizerModel._tag_keep")

        root = ET.parse(script_path).getroot()

        with self.get_session() as session:
            for e in root.findall("e"):
                tag = str(e.attrib.get("t"))
                operation = str(e.text) if e.text is not None else ""

                if "@remove" not in operation:
                    existing_entry = session.query(TagKeep).filter_by(tag=tag).first()

                    if existing_entry:
                        current_operation = session.query(TagKeep.operation).filter_by(tag=tag).scalar()

                        if current_operation != operation:
                            session.query(TagKeep).filter_by(tag=tag).update({"operation": operation})
                            logger.info(f"Updated operation for tag: {tag}")
                    else:
                        new_entry = TagKeep(tag=tag, operation=operation)
                        session.add(new_entry)

        logger.info(f"Loaded {len(root.findall('e'))} tags into _tag_keep database table.")

    # PHI

    # ✅ Changed, ✅ Tested
    def get_phi(self, anon_patient_id: str) -> PHI | None:
        """
        Fetch PHI record from the database using the anonymized patient ID.
        """
        with self.get_session() as session:
            return session.query(PHI).filter_by(patient_id=anon_patient_id).first()

    # ✅ Changed, ✅ Tested
    def get_phi_name(self, anon_patient_id: str) -> str | None:
        """
        Fetch the patient's name from PHI table based on the anonymized patient ID.
        """
        with self.get_session() as session:
            phi = session.query(PHI).filter_by(patient_id=anon_patient_id).first()
            return str(phi.patient_name) if phi is not None and phi.patient_name is not None else None

    # ✅ Changed, ✅ Tested
    def set_phi(self, anon_patient_id: str, phi: PHI):
        """
        Insert or update PHI record in the database.
        """
        with self.get_session() as session:
            existing_phi = session.query(PHI).filter_by(patient_id=anon_patient_id).first()

            if existing_phi:
                # Update existing record
                existing_phi.patient_name = phi.patient_name
                existing_phi.sex = phi.sex
                existing_phi.dob = phi.dob
                existing_phi.ethnic_group = phi.ethnic_group
            else:
                # Insert new PHI record
                new_phi = PHI(
                    patient_id=anon_patient_id,
                    patient_name=phi.patient_name,
                    sex=phi.sex,
                    dob=phi.dob,
                    ethnic_group=phi.ethnic_group,
                )
                session.add(new_phi)

            session.commit()

    # ✅ Changed, ⭕ needs testing
    def get_phi_index(self) -> List[PHI_IndexRecord]:
        """
        Reformats PHI data into a format usable by the index.

        Returns:
            List[PHI_IndexRecord]: A list of PHI_IndexRecord instances.
        """
        with self.get_session() as session:
            # Fetch all necessary data in a single query
            phi_records = (
                session.query(
                    PHI.patient_id,
                    PHI.patient_name,
                    Study.study_uid,
                    Study.study_date,
                    Study.anon_date_delta,
                    Study.accession_number,
                    Study.anon_accession_number,
                    func.count(Series.series_uid).label("num_series"),
                    func.coalesce(func.sum(Series.instance_count), 0).label("num_instances"),
                )
                .join(Study, PHI.phi_pk == Study.phi_pk)
                .outerjoin(Series, Study.study_uid == Series.study_uid)
                .group_by(
                    PHI.patient_id,
                    PHI.patient_name,
                    Study.study_uid,
                    Study.study_date,
                    Study.anon_date_delta,
                    Study.accession_number,
                    Study.anon_accession_number,
                )
                .all()
            )

        if not phi_records:
            return []

        # Caches to avoid redundant database lookups
        anon_uid_cache = {}
        anon_acc_cache = {}

        return [
            PHI_IndexRecord(
                anon_patient_id := anon_uid_cache.setdefault(pid, self.get_anon_patient_id(pid)),
                anon_patient_name=anon_patient_id,  # No Anon name implementation yet, uses ID for now
                phi_patient_id=pid,
                phi_patient_name=pname,
                date_offset=anon_date_delta,
                phi_study_date=study_date,
                anon_accession=anon_acc_cache.setdefault(accession, self.get_anon_acc_no(accession)),
                phi_accession=accession,
                anon_study_uid=self.get_anon_uid(study_uid) or "",
                phi_study_uid=study_uid,
                num_series=num_series,
                num_instances=num_instances,
            )
            for pid, pname, study_uid, study_date, anon_date_delta, accession, _, num_series, num_instances in phi_records
        ]

    # ✅ Changed, ✅ Tested
    def capture_phi(self, source: str, ds: Dataset, date_delta: int) -> None:
        """
        Capture PHI (Protected Health Information) from a dataset,
        updating the database instead of using in-memory lookups.

        Args:
            source (str): The source of the dataset.
            ds (Dataset): The dataset containing the PHI.
            date_delta (int): The anonymization date offset.

        Raises:
            ValueError: If required UIDs are missing.
        """
        # Ensure required UIDs exist
        req_uids = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]
        if not all(hasattr(ds, uid) for uid in req_uids):
            raise ValueError(f"Dataset missing UIDs: {req_uids}")

        with self.get_session() as session:
            # Get Patient PHI information
            phi_ptid = ds.PatientID.strip() if hasattr(ds, "PatientID") else ""

            # Check if PHI exists
            phi: PHI = session.query(PHI).filter_by(patient_id=phi_ptid).first()

            if phi is None:
                # NEW Patient: Generate Anon Patient ID
                max_patient_id = session.query(func.max(PHI.phi_pk)).scalar() or 0
                new_anon_patient_id = f"{self._site_id}-{str(max_patient_id).zfill(len(str(self.MAX_PATIENTS - 1)))}"

                phi = PHI(
                    patient_id=phi_ptid,
                    anon_patient_id=new_anon_patient_id,
                    patient_name=str(ds.get("PatientName", "")),
                    sex=ds.get("PatientSex"),
                    dob=ds.get("PatientBirthDate"),
                    ethnic_group=ds.get("EthnicGroup"),
                )
                session.add(phi)
                session.commit()  # This creates the private key and updates the phi object with the pk

            # Track whether a new study was just created
            new_study_created = False

            # Check if Study exists
            study = session.query(Study).filter_by(study_uid=ds.StudyInstanceUID).first()

            if study is None:
                # NEW Study:
                study = self.new_study_from_dataset(phi, ds, source, date_delta, session)
                phi.studies.append(study)  # type: ignore
                session.commit()  # Commit the new study and relationship
                new_study_created = True  # Mark that we just created a study (which also creates a series)

            # Check if Series exists
            series = session.query(Series).filter_by(series_uid=ds.SeriesInstanceUID).first()

            if series is None:
                # NEW Series in Study
                series = Series(
                    series_uid=ds.SeriesInstanceUID,
                    series_desc=ds.get("SeriesDescription"),
                    modality=ds.get("Modality"),
                    instance_count=1,  # Start at 1 for new series
                    study_uid=study.study_uid,
                )
                session.add(series)
                session.commit()  # Commit the new series

            elif not new_study_created:
                # EXISTING Series: Increment Instance Count ONLY if the study was NOT just created
                series.instance_count += 1  # type: ignore
                session.commit()  # Commit the incremented instance count

            # Assign new anonymized UID for instance
            anon_uid = f"{self._uid_prefix}.{self.get_next_anon_uid()}"
            session.add(UID(phi_uid=ds.SOPInstanceUID, anon_uid=anon_uid))
            session.commit()  # Commit the new UID mapping



    # ✅ Changed, ✅ Tested
    def remove_phi(self, anon_pt_id: str, anon_study_uid: str) -> bool:
        """
        Remove PHI data for a given anonymized patient ID and study UID.

        If the patient does not have any more studies after removing the study, the patient is removed.

        Args:
            anon_pt_id (str): The anonymized patient ID.
            anon_study_uid (str): The anonymized study UID.

        Returns:
            bool: True if the PHI data was removed successfully, False otherwise.
        """
        with self.get_session() as session:
            # Find the PHI record for the anonymized patient ID
            phi = session.query(PHI).filter(PHI.anon_patient_id == anon_pt_id).first()
            if not phi:
                logger.error(f"Anon PatientID={anon_pt_id} not found in database")
                return False

            # Find the corresponding study using the anon_study_uid
            study = session.query(Study).filter(Study.study_uid == anon_study_uid).first()
            if not study:
                logger.error(f"Anon StudyUID={anon_study_uid} not found in database")
                return False

            # Remove all series linked to the study
            session.query(Series).filter(Series.study_uid == anon_study_uid).delete()

            # Remove the study
            session.delete(study)

            # Check if the patient has any other studies left
            remaining_studies = session.query(Study).filter(Study.phi_pk == phi.phi_pk).count()

            # Remove the patient if they have no more studies
            if remaining_studies == 0:
                session.delete(phi)

            session.commit()
            return True

    # ✅ Changed, ⭕ needs testing
    def process_java_phi_studies(self, java_studies: List[JavaAnonymizerExportedStudy]) -> None:
        """
        Process Java PHI studies and store PHI in the AnonymizerModelSQL.

        Args:
            java_studies (List[JavaAnonymizerExportedStudy]): List of Java PHI studies.

        Returns:
            None
        """
        logger.info(f"Processing {len(java_studies)} Java PHI Studies")

        with self.get_session() as session:
            for java_study in java_studies:
                # Store anonymized UIDs
                self.set_anon_uid(java_study.PHI_StudyInstanceUID, java_study.ANON_StudyInstanceUID)

                # Check if PHI entry for this patient already exists
                phi_entry = session.query(PHI).filter_by(patient_id=java_study.PHI_PatientID).first()

                if not phi_entry:
                    # If PHI doesn't exist, create a new entry
                    phi_entry = PHI(
                        patient_id=java_study.PHI_PatientID,
                        anon_patient_id=java_study.ANON_PatientID,
                        patient_name=java_study.PHI_PatientName,
                    )
                    session.add(phi_entry)

                # Check if Study already exists (avoid duplicates)
                study_entry = session.query(Study).filter_by(study_uid=java_study.PHI_StudyInstanceUID).first()

                if not study_entry:
                    # Create new study linked to PHI
                    study_entry = Study(
                        study_uid=java_study.PHI_StudyInstanceUID,
                        patient_id=java_study.PHI_PatientID,  # FK linking to PHI
                        study_date=java_study.PHI_StudyDate,
                        anon_date_delta=int(java_study.DateOffset),
                        accession_number=java_study.PHI_Accession,
                        study_desc="?",  # Placeholder as per original logic
                        source="Java Index File",
                    )
                    session.add(study_entry)

            session.commit()  # Commit changes after all iterations

    # Patients

    # ✅ Changed, ✅ Tested
    def get_anon_patient_id(self, phi_patient_id: str) -> str | None:
        """
        Retrieves the anonymized patient ID for a given PHI patient ID.
        Returns None if not found.
        """
        with self.get_session() as session:
            record = session.query(PHI).filter_by(patient_id=phi_patient_id).first()
            return str(record.anon_patient_id) if record is not None and record.anon_patient_id is not None else None

    # ✅ Changed, ✅ Tested
    def get_patient_id_count(self) -> int:
        """
        Get the number of patients in the PHI table.
        """
        with self.get_session() as session:
            return session.query(func.count(PHI.patient_id)).scalar() or 0

    # ✅ Changed, ✅ Tested
    def set_anon_patient_id(self, phi_patient_id: str, anon_patient_id: str) -> None:
        """
        Updates the anonymized patient ID for an existing PHI record.
        Raises an error if the PHI record does not exist.
        """
        with self.get_session() as session:
            existing_entry = session.query(PHI).filter_by(patient_id=phi_patient_id).first()

            if existing_entry:
                session.query(PHI).filter_by(patient_id=phi_patient_id).update({"anon_patient_id": anon_patient_id})
                logger.info(f"Updated anonymized patient ID for {phi_patient_id} -> {anon_patient_id}")
                session.commit()
            else:
                logger.error(f"Cannot set anon_patient_id: No PHI record found for patient_id {phi_patient_id}")
                raise ValueError(f"No PHI record found for patient_id {phi_patient_id}")

    # UID

    # ✅ Changed, ✅ Tested
    def get_anon_uid(self, phi_uid: str) -> str | None:
        """
        Retrieves the anonymized UID for a given PHI UID.
        Returns None if not found.
        """
        with self.get_session() as session:
            record = session.query(UID).filter_by(phi_uid=phi_uid).first()
            return str(record.anon_uid) if record is not None and record.anon_uid is not None else None

    # ✅ Changed, ✅ Tested
    def uid_received(self, phi_uid: str) -> bool:
        """
        Checks if a given PHI UID exists in the database.
        """
        with self.get_session() as session:
            return session.query(UID).filter_by(phi_uid=phi_uid).first() is not None

    # ✅ Changed, ✅ Tested
    def remove_uid(self, phi_uid: str) -> None:
        """
        Deletes the corresponding phi_uid from the UID table.
        """
        with self.get_session() as session:
            deleted_rows = session.query(UID).filter_by(phi_uid=phi_uid).delete()
            if deleted_rows:
                logger.info(f"Deleted UID record for phi_uid: {phi_uid}")
            session.commit()

    # ✅ Changed, ✅ Tested
    def remove_uid_inverse(self, anon_uid: str) -> None:
        """
        Deletes the UID record where the anonymized UID matches.
        """
        with self.get_session() as session:
            deleted_rows = session.query(UID).filter_by(anon_uid=anon_uid).delete()
            if deleted_rows:
                logger.info(f"Deleted UID record for anon_uid: {anon_uid}")
            session.commit()

    # ✅ Changed, ✅ Tested
    def get_next_anon_uid(self, session: Optional[Session] = None) -> int:
        """
        Returns the largest number in the UID mappings in the database.
        Uses the provided session if available, otherwise creates a new session.
        """
        if session is None:
            with self.get_session() as session:
                return session.query(func.max(UID.uid_pk)).scalar() or 0
        else:
            return session.query(func.max(UID.uid_pk)).scalar() or 0

    # ✅ Changed, ✅ Tested
    def set_anon_uid(self, phi_uid: str, anon_uid: str) -> None:
        """
        Adds or updates a UID mapping in the database.
        """
        with self.get_session() as session:
            existing_entry = session.query(UID).filter_by(phi_uid=phi_uid).first()

            if existing_entry:
                session.query(UID).filter_by(phi_uid=phi_uid).update({"anon_uid": anon_uid})
                logger.info(f"Updated UID mapping: {phi_uid} -> {anon_uid}")
            else:
                new_entry = UID(phi_uid=phi_uid, anon_uid=anon_uid)
                session.add(new_entry)
                logger.info(f"Inserted new UID mapping: {phi_uid} -> {anon_uid}")

            session.commit()

    # # ✅ Changed, ✅ Tested
    # def get_uid_count(self) -> int:
    #     """
    #     Returns the number of UID mappings in the database.
    #     Uses conditional locking to prevent deadlocks.
    #     """
    #     acquired_lock = self._lock.acquire(blocking=False)  # Try to acquire the lock non-blocking
    #     try:
    #         return self._session.query(func.count(UID.uid_pk)).scalar() or 0
    #     finally:
    #         if acquired_lock:
    #             self._lock.release()  # Release lock only if we acquired it

    # Tags

    # ✅Added, ✅ Tested
    def load_tag_keep(self):
        """
        Loads all entries from the TagKeep table into the _tag_keep dictionary.
        """
        self._tag_keep = {}  # Reset dictionary

        with self.get_session() as session:
            tag_records = session.query(TagKeep).all()

            for record in tag_records:
                self._tag_keep[str(record.tag)] = str(record.operation)

    # Accession

    # ✅ Changed, ✅ Tested
    def get_anon_acc_no(self, phi_acc_no: str) -> str | None:
        """
        Retrieves the anonymized accession number for a given PHI accession number.
        Returns None if not found.
        """
        with self.get_session() as session:
            record = session.query(Study).filter_by(accession_number=phi_acc_no).first()
            return (
                str(record.anon_accession_number)
                if record is not None and record.anon_accession_number is not None
                else None
            )

    # ✅ Changed, ✅ Tested
    def get_next_anon_acc_no(self, phi_acc_no: str, session: Optional[Session] = None) -> str:
        """
        Retrieves the next available anonymized accession number.
        Uses the provided session if available, otherwise creates a new session.
        """
        if session is None:
            with self.get_session() as session:
                next_anon_acc_no = (session.query(func.max(Study.anon_accession_number_count)).scalar() or 0) + 1
                return str(next_anon_acc_no)
        else:
            next_anon_acc_no = (session.query(func.max(Study.anon_accession_number_count)).scalar() or 0) + 1
            return str(next_anon_acc_no)

    # ✅ Changed, ✅ Tested
    def get_acc_no_count(self) -> int:
        """
        Returns the highest anon_accession_number_count from the Study table.
        """
        with self.get_session() as session:
            return session.query(func.max(Study.anon_accession_number_count)).scalar() or 0

    # ✅ Added, ✅ Tested
    def set_anon_acc_no(self, study_uid: str, anon_accession: str, session: Optional[Session] = None) -> None:
        """
        Sets the anonymized accession number for a given study by its study UID.

        Args:
            study_uid (str): The study UID.
            anon_accession (str): The new anonymized accession number.
            session (Optional[Session]): The optional session object. If not provided, a new session is created.

        Raises:
            ValueError: If no study with the provided study UID is found.
        """
        if session is None:
            with self.get_session() as session:
                study = session.query(Study).filter_by(study_uid=study_uid).first()

                if not study:
                    raise ValueError(f"Study with study UID {study_uid} not found.")

                session.query(Study).filter_by(study_uid=study_uid).update({"anon_accession_number": anon_accession})
                session.commit()
        else:
            study = session.query(Study).filter_by(study_uid=study_uid).first()

            if not study:
                raise ValueError(f"Study with study UID {study_uid} not found.")

            session.query(Study).filter_by(study_uid=study_uid).update({"anon_accession_number": anon_accession})
            session.commit()

    # Instances

    # ✅ Changed, ✅ Tested
    def get_stored_instance_count(self, ptid: str, study_uid: str) -> int:
        """
        Retrieves the number of stored instances for a given patient ID and study UID.
        """
        with self.get_session() as session:
            # Get the PHI record for the patient
            phi_entry = session.query(PHI.phi_pk).filter_by(patient_id=ptid).scalar()
            if not phi_entry:
                return 0

            # Ensure the study exists for this patient
            study_exists = session.query(Study.study_uid).filter_by(study_uid=study_uid, phi_pk=phi_entry).scalar()
            if not study_exists:
                return 0

            # Sum all instance counts from related Series
            return session.query(func.sum(Series.instance_count)).filter_by(study_uid=study_uid).scalar() or 0

    # ✅ Changed, ✅ Tested
    def get_pending_instance_count(self, ptid: str, study_uid: str, target_count: int) -> int:
        """
        Returns the difference between stored instances and target_count for a given study.
        Also ensures study.target_instance_count is set.
        """
        with self.get_session() as session:
            # Get PHI primary key
            phi_pk = session.query(PHI.phi_pk).filter_by(patient_id=ptid).scalar()
            if not phi_pk:
                return target_count

            # Get Study entry
            study = session.query(Study).filter_by(study_uid=study_uid, phi_pk=phi_pk).first()
            if not study:
                return target_count

            # Ensure target_instance_count is set
            if study.target_instance_count == 0:  # type: ignore
                session.query(Study).filter_by(study_uid=study_uid, phi_pk=phi_pk).update(
                    {"target_instance_count": target_count}
                )
                session.commit()

            # Get stored instance count
            stored_instance_count = (
                session.query(func.sum(Series.instance_count)).filter_by(study_uid=study_uid).scalar() or 0
            )

            return max(0, target_count - stored_instance_count)

    # Series

    # ✅ Changed, ✅ Tested
    def series_complete(self, ptid: str, study_uid: str, series_uid: str, target_count: int) -> bool:
        """
        Check if a series is complete by comparing stored instances to the target count.
        """
        with self.get_session() as session:
            series = session.query(Series.instance_count).filter_by(series_uid=series_uid, study_uid=study_uid).scalar()

            return bool(series and series >= target_count)

    # Study

    # ✅ Changed, ⭕ needs testing
    def study_imported(self, ptid: str, study_uid: str) -> bool:
        """
        Checks if a study has already been imported by comparing stored instance count to target.
        """
        with self.get_session() as session:
            study = session.query(Study).filter_by(study_uid=study_uid, patient_id=ptid).first()

            if not study or study.target_instance_count.value == 0:  # Ensure the target count is set
                return False

            # Sum all stored instances across series in the study
            stored_instance_count = (
                session.query(func.sum(Series.instance_count)).filter_by(study_uid=study_uid).scalar() or 0
            )

            return stored_instance_count >= study.target_instance_count.value

    # ✅ Changed, ✅ Tested
    def new_study_from_dataset(self, phi: PHI, ds: Dataset, source: str, date_delta: int, session) -> Study:
        """
        Creates a new Study record from the dataset, ensuring anon_accession_number is correctly assigned.
        """
        next_anon_acc_no_count = (session.query(func.max(Study.anon_accession_number_count)).scalar() or 0) + 1

        new_study = Study(
            study_uid=ds.get("StudyInstanceUID"),
            study_date=ds.get("StudyDate"),
            phi_pk=phi.phi_pk,
            anon_date_delta=date_delta,
            accession_number=ds.get("AccessionNumber"),
            anon_accession_number_count=next_anon_acc_no_count,
            anon_accession_number=str(next_anon_acc_no_count),  # Store as string
            study_desc=ds.get("StudyDescription"),
            source=source,
        )

        # Check if SeriesInstanceUID exists and add it if necessary
        if hasattr(ds, "SeriesInstanceUID"):
            new_series = Series(
                series_uid=ds.get("SeriesInstanceUID"),
                series_desc=ds.get("SeriesDescription"),
                modality=ds.get("Modality"),
                instance_count=1,  # Start at 1 for new series
                study_uid=new_study.study_uid
            )
            new_study.series.append(new_series)

        session.add(new_study)
        session.commit()

        return new_study


    # Quarantined

    # ✅ No changes needed, ✅ Tested
    def increment_quarantined(self):
        self._quarantined += 1


# """
# This module contains the AnonymizerModel class, which is responsible for storing PHI (Protected Health Information)
# and anonymization lookups. It also includes data classes for Series, Study, and PHI, as well as a Totals namedtuple.
# """

# import logging
# import pickle
# import shutil
# import threading
# import xml.etree.ElementTree as ET
# from collections import namedtuple
# from dataclasses import dataclass, field, fields
# from pathlib import Path
# from pprint import pformat
# from typing import ClassVar, Dict, List, Tuple

# from bidict import bidict
# from pydicom import Dataset

# from anonymizer.model.project import DICOMNode
# from anonymizer.utils.storage import JavaAnonymizerExportedStudy

# logger = logging.getLogger(__name__)


# @dataclass
# class Series:
#     series_uid: str
#     series_desc: str
#     modality: str
#     instance_count: int


# @dataclass
# class Study:
#     source: DICOMNode | str
#     study_uid: str
#     study_date: str
#     anon_date_delta: int
#     accession_number: str
#     study_desc: str
#     series: List[Series]  # TODO: make dictionary with key = series_uid
#     target_instance_count: int = 0
#     # TODO: if data curation needs expand:
#     # weight: str | None = None
#     # bmi: str | None = None
#     # size: str | None = None
#     # smoker: str | None = None
#     # medical_alerts: str | None = None
#     # allergies: str | None = None
#     # reason_for_visit: str | None = None
#     # admitting_diagnoses: str | None = None
#     # history: str | None = None
#     # additional_history: str | None = None
#     # comments: str | None = None


# @dataclass
# class PHI:
#     patient_name: str = ""
#     patient_id: str = ""
#     sex: str | None = None
#     dob: str | None = None
#     ethnic_group: str | None = None
#     studies: List[Study] = field(default_factory=list)  # TODO: make dictionary with key = study_uid


# @dataclass
# class PHI_IndexRecord:
#     anon_patient_id: str
#     anon_patient_name: str
#     phi_patient_name: str
#     phi_patient_id: str
#     date_offset: int
#     phi_study_date: str
#     anon_accession: str
#     phi_accession: str
#     anon_study_uid: str
#     phi_study_uid: str
#     num_series: int
#     num_instances: int

#     field_titles: ClassVar[Dict[str, str]] = {
#         "anon_patient_id": "ANON-PatientID",
#         "anon_patient_name": "ANON-PatientName",
#         "phi_patient_name": "PHI-PatientName",
#         "phi_patient_id": "PHI-PatientID",
#         "date_offset": "DateOffset",
#         "phi_study_date": "PHI-StudyDate",
#         "anon_accession": "ANON-AccNo",
#         "phi_accession": "PHI-AccNo",
#         "anon_study_uid": "ANON-StudyUID",
#         "phi_study_uid": "PHI-StudyUID",
#         "num_series": "Series",
#         "num_instances": "Instances",
#     }

#     @classmethod
#     def get_field_titles(cls) -> list:
#         return [cls.field_titles.get(field.name) for field in fields(cls)]

#     def flatten(self) -> Tuple:
#         return tuple(getattr(self, field.name) for field in fields(self))

#     @classmethod
#     def get_field_names(cls) -> list:
#         return [field.name for field in fields(cls)]


# Totals = namedtuple("Totals", ["patients", "studies", "series", "instances", "quarantined"])


# class AnonymizerModel:
#     """
#     The Anonymizer data model class to store PHI (Protected Health Information) and anonymization lookups.
#     """

#     # Model Version Control
#     MODEL_VERSION = 2
#     MAX_PATIENTS = 1000000  # 1 million patients

#     _lock = threading.Lock()

#     def __init__(self, site_id: str, uid_root: str, script_path: Path):
#         """
#         Initializes an instance of the AnonymizerModel class.

#         Args:
#             site_id (str): The site ID.
#             uid_root (str): The UID root.
#             script_path (Path): The path to the script.

#         Attributes:
#             _version (int): The model version.
#             _site_id (str): The site ID.
#             _uid_root (str): The UID root.
#             _uid_prefix (str): The UID prefix.
#             default_anon_pt_id (str): The default anonymized patient ID.
#             _patient_id_lookup (dict): A dictionary to store patient ID lookups.
#             _uid_lookup (dict): A dictionary to store UID lookups.
#             _acc_no_lookup (dict): A dictionary to store accession number lookups.
#             _phi_lookup (dict): A dictionary to store PHI lookups.
#             _script_path (Path): The path to the script.
#             _tag_keep (dict): A dictionary to store DICOM tag operations.
#             _patients (int): The number of patients.
#             _studies (int): The number of studies.
#             _series (int): The number of series.
#             _instances (int): The number of instances.
#             _quarantined (int): The number of instances quarantined. [V2]
#         """
#         self._version = AnonymizerModel.MODEL_VERSION  # figure out how to manage data version with sqlalchamy
#         self._site_id = site_id
#         self._uid_root = uid_root
#         self._script_path = script_path

#         self._uid_prefix = f"{self._uid_root}.{self._site_id}"
#         self.default_anon_pt_id: str = site_id + "-" + "".zfill(len(str(self.MAX_PATIENTS)) - 1)

#         # Initialise Lookup Tables:
#         self._patient_id_lookup: Dict[str, str] = {}
#         self._uid_lookup: bidict[str, str] = bidict()
#         self._acc_no_lookup: Dict[str, str] = {}
#         self._phi_lookup: Dict[str, PHI] = {}
#         self._tag_keep: Dict[str, str] = {}  # {dicom tag : anonymizer operation}

#         self._patients = 0
#         self._studies = 0
#         self._series = 0
#         self._instances = 0
#         self._quarantined = 0  # [V2]

#         self.clear_lookups()  # initialises default patient_id_lookup and phi_lookup
#         self.load_script(script_path)

#     def save(self, filepath: Path) -> bool:
#         with self._lock:
#             try:
#                 serialized_data = pickle.dumps(self, protocol=pickle.HIGHEST_PROTOCOL)
#                 with open(filepath, "wb") as pkl_file:
#                     pkl_file.write(serialized_data)
#                 shutil.copy2(
#                     filepath, filepath.with_suffix(filepath.suffix + ".bak")
#                 )  # backup <filepath>.pkl to <filepath>.pkl.bak
#                 logger.debug(f"Anonymizer Model saved to: {filepath}")
#                 return True
#             except Exception as e:
#                 logger.error(f"Fatal Error saving AnonymizerModel, error: {e}")
#                 return False

#     def get_class_name(self) -> str:
#         return self.__class__.__name__

#     def __repr__(self) -> str:
#         filtered_dict = {
#             key: len(value) if isinstance(value, (dict, set)) else value for key, value in (self.__dict__.items())
#         }
#         return f"{self.get_class_name()}\n({pformat(filtered_dict)})"

#     def load_script(self, script_path: Path):
#         """
#         Load and parse an anonymize script file.

#         Args:
#             script_path (Path): The path to the script file.

#         Raises:
#             FileNotFoundError: If the script file is not found.
#             ET.ParseError: If there is an error parsing the script file.
#             Exception: If there is any other generic exception.

#         Returns:
#             None
#         """
#         logger.info(f"Load script file: {script_path} to create AnonymizerModel._tag_keep")
#         try:
#             # Open and parse the XML script file
#             root = ET.parse(script_path).getroot()

#             # Extract 'e' tags into _tag_keep dictionary
#             # IGNORE "en" = "T" or "F" - Java UX checkbox
#             # Tags with no operation or specified operation (which can be @remove) are added to tag_keep dictionary
#             # ALL unspecified tags are removed
#             for e in root.findall("e"):
#                 tag = str(e.attrib.get("t"))
#                 operation = str(e.text) if e.text is not None else ""
#                 if "@remove" not in operation:
#                     self._tag_keep[tag] = operation

#             # Handle:
#             # <r en="T" t="curves">Remove curves</r>
#             # <r en="T" t="overlays">Remove overlays</r>
#             # <r en="T" t="privategroups">Remove private groups</r> # pydicom.remove_private_tags()
#             # <r en="F" t="unspecifiedelements">Remove unchecked elements</r> # ignore check/unchecked en="T/F"

#             filtered_tag_keep = {k: v for k, v in self._tag_keep.items() if v != ""}
#             logger.info(f"_tag_keep has {len(self._tag_keep)} entries with {len(filtered_tag_keep)} operations")
#             logger.info(f"_tag_keep operations:\n{pformat(filtered_tag_keep)}")
#             return

#         except FileNotFoundError:
#             logger.error(f"{script_path} not found")
#             raise

#         except ET.ParseError:
#             logger.error(f"Error parsing the script file {script_path}. Ensure it is valid XML.")
#             raise

#         except Exception as e:
#             # Catch other generic exceptions and print the error message
#             logger.error(f"Error Parsing script file {script_path}: {str(e)}")
#             raise

#     def clear_lookups(self):
#         """
#         Clears all the lookup dictionaries used for anonymization.
#         """
#         with self._lock:
#             self._patient_id_lookup.clear()
#             self._patient_id_lookup[""] = self.default_anon_pt_id  # Default Anonymized PatientID
#             self._uid_lookup.clear()
#             self._acc_no_lookup.clear()
#             self._phi_lookup.clear()
#             self._phi_lookup[self.default_anon_pt_id] = PHI()  # Default PHI for Anonymized PatientID

#     def get_totals(self) -> Totals:
#         return Totals(
#             self._patients,
#             self._studies,
#             self._series,
#             self._instances,
#             self._quarantined,
#         )

#     def get_phi(self, anon_patient_id: str) -> PHI | None:
#         with self._lock:
#             return self._phi_lookup.get(anon_patient_id, None)

#     def get_phi_name(self, anon_patient_id: str) -> str | None:
#         with self._lock:
#             phi = self._phi_lookup.get(anon_patient_id, None)
#             if phi is None:
#                 return None
#             else:
#                 return phi.patient_name

#     def set_phi(self, anon_patient_id: str, phi: PHI):
#         with self._lock:
#             self._phi_lookup[anon_patient_id] = phi

#     def increment_quarantined(self):
#         self._quarantined += 1

#     def get_anon_patient_id(self, phi_patient_id: str) -> str | None:
#         return self._patient_id_lookup.get(phi_patient_id)

#     def get_next_anon_patient_id(self, phi_patient_id: str) -> str:
#         with self._lock:
#             anon_patient_id = (
#                 f"{self._site_id}-{str(len(self._patient_id_lookup)).zfill(len(str(self.MAX_PATIENTS - 1)))}"
#             )
#             self._patient_id_lookup[phi_patient_id] = anon_patient_id
#             return anon_patient_id

#     def get_patient_id_count(self) -> int:
#         return len(self._patient_id_lookup)

#     def set_anon_patient_id(self, phi_patient_id: str, anon_patient_id: str):
#         with self._lock:
#             self._patient_id_lookup[phi_patient_id] = anon_patient_id

#     def uid_received(self, phi_uid: str) -> bool:
#         return phi_uid in self._uid_lookup

#     def remove_uid(self, phi_uid: str):
#         with self._lock:
#             if phi_uid in self._uid_lookup:
#                 del self._uid_lookup[phi_uid]

#     def remove_uid_inverse(self, anon_uid: str):
#         with self._lock:
#             if anon_uid in self._uid_lookup.inverse:
#                 del self._uid_lookup.inverse[anon_uid]

#     def get_anon_uid(self, phi_uid: str) -> str | None:
#         return self._uid_lookup.get(phi_uid, None)

#     def get_uid_count(self) -> int:
#         return len(self._uid_lookup)

#     def set_anon_uid(self, phi_uid: str, anon_uid: str):
#         with self._lock:
#             self._uid_lookup[phi_uid] = anon_uid

#     def get_next_anon_uid(self, phi_uid: str) -> str:
#         with self._lock:
#             anon_uid = self._uid_prefix + f".{self.get_uid_count() + 1}"
#             self._uid_lookup[phi_uid] = anon_uid
#             return anon_uid

#     def get_anon_acc_no(self, phi_acc_no: str) -> str | None:
#         return self._acc_no_lookup.get(phi_acc_no)

#     def set_anon_acc_no(self, phi_acc_no: str, anon_acc_no: str):
#         with self._lock:
#             self._acc_no_lookup[phi_acc_no] = anon_acc_no

#     def get_next_anon_acc_no(self, phi_acc_no: str) -> str:
#         with self._lock:
#             anon_acc_no = len(self._acc_no_lookup) + 1
#             # TODO: include PHI PatientID with phi_acc_no for uniqueness
#             self._acc_no_lookup[phi_acc_no] = str(anon_acc_no)
#             return str(anon_acc_no)

#     def get_acc_no_count(self) -> int:
#         return len(self._acc_no_lookup)

#     def get_stored_instance_count(self, ptid: str, study_uid: str) -> int:
#         """
#         Retrieves the number of stored instances for a given patient ID and study UID.

#         Args:
#             ptid (str): PHI PatientID.
#             study_uid (str): PHI StudyUID.

#         Returns:
#             int: The number of stored instances.

#         """
#         with self._lock:
#             anon_patient_id = self._patient_id_lookup.get(ptid, None)
#             if anon_patient_id is None:
#                 return 0
#             phi = self._phi_lookup.get(anon_patient_id, None)
#             if phi is None:
#                 return 0
#             for study in phi.studies:
#                 if study.study_uid == study_uid:
#                     return sum(series.instance_count for series in study.series)
#             return 0

#     def get_pending_instance_count(self, ptid: str, study_uid: str, target_count: int) -> int:
#         """
#         This will return difference between stored instances and target_count for a given patient ID & study UID
#         When first called for a study it also sets the study.target_instance_count (for future imported state detection)

#         Args:
#             ptid (str): The patient ID.
#             study_uid (str): The study UID.
#             target_count (int): The target count.

#         Returns:
#             int: The pending instance count.
#         """
#         anon_patient_id = self._patient_id_lookup.get(ptid, None)
#         if anon_patient_id is None:
#             return target_count
#         phi = self._phi_lookup.get(anon_patient_id, None)
#         if phi is None:
#             return target_count
#         for study in phi.studies:
#             if study.study_uid == study_uid:
#                 with self._lock:
#                     study.target_instance_count = target_count
#                     return target_count - sum(series.instance_count for series in study.series)
#         return target_count

#     def series_complete(self, ptid: str, study_uid: str, series_uid: str, target_count: int) -> bool:
#         """
#         Check if a series is complete based on the given parameters.

#         Args:
#             ptid (str): The patient ID.
#             study_uid (str): The study UID.
#             series_uid (str): The series UID.
#             target_count (int): The target instance count.

#         Returns:
#             bool: True if the series is complete, False otherwise.
#         """
#         anon_patient_id = self._patient_id_lookup.get(ptid, None)
#         if anon_patient_id is None:
#             return False
#         phi = self._phi_lookup.get(anon_patient_id, None)
#         if phi is None:
#             return False
#         for study in phi.studies:
#             if study.study_uid == study_uid:
#                 for series in study.series:
#                     if series.series_uid == series_uid:
#                         return series.instance_count >= target_count
#                 return False
#         return False

#     def get_phi_index(self) -> List[PHI_IndexRecord] | None:
#         if self.get_patient_id_count() == 0:
#             return None

#         phi_index = []
#         for anon_pt_id in self._phi_lookup:
#             phi: PHI = self._phi_lookup[anon_pt_id]
#             for study in phi.studies:
#                 phi_index_record = PHI_IndexRecord(
#                     anon_patient_id=anon_pt_id,
#                     anon_patient_name=anon_pt_id,
#                     phi_patient_id=anon_pt_id,
#                     phi_patient_name=phi.patient_name,
#                     date_offset=study.anon_date_delta,
#                     phi_study_date=study.study_date,
#                     # TODO: Handle missing accession numbers
#                     anon_accession=self._acc_no_lookup[study.accession_number],
#                     phi_accession=study.accession_number,
#                     anon_study_uid=self._uid_lookup[study.study_uid],
#                     phi_study_uid=study.study_uid,
#                     num_series=len(study.series),
#                     num_instances=sum([s.instance_count for s in study.series]),
#                 )
#                 phi_index.append(phi_index_record)
#         return phi_index

#     # Used by QueryRetrieveView to prevent study re-import
#     def study_imported(self, ptid: str, study_uid: str) -> bool:
#         with self._lock:
#             anon_patient_id = self._patient_id_lookup.get(ptid, None)
#             if anon_patient_id is None:
#                 return False
#             phi = self._phi_lookup.get(anon_patient_id, None)
#             if phi is None:
#                 return False
#             for study in phi.studies:
#                 if study.study_uid == study_uid:
#                     if study.target_instance_count == 0:  # Not set by ProjectController import process yet
#                         return False
#                     return sum(series.instance_count for series in study.series) >= study.target_instance_count
#             return False

#     # Helper function for capture_phi
#     def new_study_from_dataset(self, ds: Dataset, source: DICOMNode | str, date_delta: int) -> Study:
#         return Study(
#             study_uid=ds.get("StudyInstanceUID"),
#             study_date=ds.get("StudyDate"),
#             anon_date_delta=date_delta,
#             accession_number=ds.get("AccessionNumber"),
#             study_desc=ds.get("StudyDescription"),
#             source=source,
#             series=[
#                 Series(
#                     series_uid=ds.get("SeriesInstanceUID"),
#                     series_desc=ds.get("SeriesDescription"),
#                     modality=ds.get("Modality"),
#                     instance_count=1,
#                 )
#             ],
#         )

#     def capture_phi(self, source: str, ds: Dataset, date_delta: int) -> None:
#         """
#         Capture PHI (Protected Health Information) from a dataset,
#         Update the UID & PHI lookups and the dataset statistics (patients,studies,series,instances)

#         Args:
#             source (str): The source of the dataset.
#             ds (Dataset): The dataset containing the PHI.
#             date_delta (int): The time difference in days.

#         Raises following Critical Errors:
#             1. ValueError:  If any of StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID are not present in dataset
#             2. LookupError: If the PHI PatientID is not found in the patient_id_lookup or phi_lookup.
#             3. LookupError: If the existing patient with Anon PatientID is not found in phi_lookup.
#             4. LookupError: If the existing study is not found in phi_lookup.
#             5. LookupError: If the existing series is not found in the study.

#         Returns:
#             None
#         """
#         with self._lock:
#             # ds must have attributes: StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID
#             req_uids = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]
#             if not all(hasattr(ds, uid) for uid in req_uids):
#                 msg = f"Critical Error 1: Dataset missing primary UIDs: {req_uids}"
#                 logger.error(msg)
#                 raise ValueError(msg)

#             # If PHI PatientID is missing in dataset, as per DICOM Standard, pydicom should return "", handle missing attribute
#             # Missing or blank corresponds to AnonymizerModel.DEFAULT_ANON_PATIENT_ID ("000000") initialised in AnonymizerModel.clear_lookups()
#             phi_ptid = ds.PatientID.strip() if hasattr(ds, "PatientID") else ""
#             anon_patient_id: str | None = self._patient_id_lookup.get(phi_ptid, None)
#             next_uid_ndx = self.get_uid_count() + 1
#             anon_study_uid = self._uid_lookup.get(ds.StudyInstanceUID)

#             if anon_study_uid is None:
#                 # NEW Study:
#                 if anon_patient_id is None:
#                     # NEW patient
#                     new_anon_patient_id = (
#                         f"{self._site_id}-{str(len(self._patient_id_lookup)).zfill(len(str(self.MAX_PATIENTS - 1)))}"
#                     )
#                     phi = PHI(
#                         patient_name=ds.get("PatientName"),
#                         patient_id=phi_ptid,
#                         sex=ds.get("PatientSex"),
#                         dob=ds.get("PatientBirthDate"),
#                         ethnic_group=ds.get("EthnicGroup"),
#                         studies=[],
#                     )
#                     self._phi_lookup[new_anon_patient_id] = phi
#                     self._patient_id_lookup[phi_ptid] = new_anon_patient_id
#                     self._patients += 1

#                 else:  # Existing patient now with more than one study
#                     phi: PHI | None = self._phi_lookup.get(anon_patient_id, None)

#                     if phi is None:
#                         msg = f"Critical Error 2: Existing patient, Anon PatientID={anon_patient_id} not found in phi_lookup"
#                         logger.error(msg)
#                         raise LookupError(msg)

#                 # ADD new study,series,instance to PHI:
#                 phi.studies.append(self.new_study_from_dataset(ds, source, date_delta))
#                 for uid in req_uids:
#                     anon_uid = self._uid_prefix + f".{next_uid_ndx}"
#                     self._uid_lookup[getattr(ds, uid)] = anon_uid
#                     next_uid_ndx += 1

#                 self._studies += 1
#                 self._series += 1
#                 self._instances += 1

#             else:
#                 # Existing Study
#                 # Assume Existing Patient and PHI already captured
#                 # If so, update series and instance counts from new instance:
#                 if anon_patient_id is None:
#                     # TODO: Different PatientID for SAME Study detected:
#                     # Look through PHI lookup for this study to determine which PatientID has already been associated with it
#                     msg = f"Critical Error 3: Existing study Anon StudyUID={anon_study_uid}, incoming file has different PHI PatientID"
#                     logger.critical(msg)
#                     raise LookupError(msg)

#                 phi: PHI | None = self._phi_lookup.get(anon_patient_id, None)

#                 if phi is None:
#                     msg = f"Critial Error 4: Existing Anon PatientID={anon_patient_id} not found in phi_lookup"
#                     logger.critical(msg)
#                     raise LookupError(msg)

#                 # Find study in PHI:
#                 if phi.studies is not None:
#                     study = next(
#                         (study for study in phi.studies if study.study_uid == ds.StudyInstanceUID),
#                         None,
#                     )
#                 else:
#                     study = None

#                 if study is None:
#                     msg = (
#                         f"Critical Error 5: Existing study for Anon PatientID={anon_patient_id} not found in phi_lookup"
#                     )
#                     logger.error(msg)
#                     raise LookupError(msg)

#                 # Find series in study:
#                 if study.series is not None:
#                     series: Series | None = next(
#                         (series for series in study.series if series.series_uid == ds.SeriesInstanceUID),
#                         None,
#                     )
#                 else:
#                     series = None

#                 if series is None:
#                     # NEW Series in exsiting Study:
#                     study.series.append(
#                         Series(
#                             ds.get("SeriesInstanceUID"),
#                             ds.get("SeriesDescription"),
#                             ds.get("Modality"),
#                             1,
#                         )
#                     )
#                     for uid in req_uids[1:]:  # Skip StudyInstanceUID
#                         anon_uid = self._uid_prefix + f".{next_uid_ndx}"
#                         self._uid_lookup[getattr(ds, uid)] = anon_uid
#                         next_uid_ndx += 1

#                     self._series += 1

#                 else:
#                     # NEW Instance in existing Series:
#                     series.instance_count += 1
#                     anon_uid = self._uid_prefix + f".{next_uid_ndx}"
#                     self._uid_lookup[ds.SOPInstanceUID] = anon_uid

#                 self._instances += 1

#     def remove_phi(self, anon_pt_id: str, anon_study_uid: str) -> bool:
#         """
#         Remove PHI data for a given Anonymizer patient ID and study UID.

#         If the patient does not have anymore studies after removing the study, the patient is removed from the both patient_id_lookup and phi_lookup.

#         Args:
#             anon_pt_id (str): The anonymized patient ID.
#             anon_study_uid (str): The anonymized study UID.

#         Returns:
#             bool: True if the PHI data was removed successfully, False otherwise.
#         """
#         with self._lock:
#             phi: PHI | None = self._phi_lookup.get(anon_pt_id, None)
#             if phi is None:
#                 logger.error(f"Anon PatientID={anon_pt_id} not found in phi_lookup")
#                 return False
#             phi_study_uid = self._uid_lookup.inverse.get(anon_study_uid, None)
#             if phi_study_uid is None:
#                 logger.error(f"Anon StudyUID={anon_study_uid} not found in uid_lookup")
#                 return False
#             if not phi.studies:
#                 logger.error(f"No studies in PHI.studies for Anon PatientID={anon_pt_id}")
#                 return False

#             match = None
#             for study in phi.studies:
#                 if study.study_uid == phi_study_uid:
#                     match = study
#                     break

#             if match is None:
#                 logger.error(f"Anon StudyUID={anon_study_uid} not found in PHI.studies for Anon PatientID={anon_pt_id}")
#                 return False

#             # Remove the accession number from _acc_no_lookup:
#             if study.accession_number in self._acc_no_lookup:
#                 del self._acc_no_lookup[study.accession_number]

#             # Remove the series_uids of this study from the uid_lookup:
#             # Note: instance uids are removed by controller via directory names
#             # Note: uids generated for other uid fields as per script will not be removed from uid_lookup
#             for series in match.series:
#                 if series.series_uid in self._uid_lookup:
#                     del self._uid_lookup[series.series_uid]
#                 self._instances -= series.instance_count
#                 self._series -= 1

#             # Remove the study_uid from the uid_lookup:
#             if phi_study_uid in self._uid_lookup:
#                 del self._uid_lookup[phi_study_uid]

#             # Remove the matched study from phi.studies list:
#             phi.studies.remove(match)

#             self._studies -= 1

#             # Remove the patient if no more studies:
#             if not phi.studies:
#                 del self._phi_lookup[anon_pt_id]
#                 del self._patient_id_lookup[phi.patient_id]
#                 self._patients -= 1

#             return True

#     def process_java_phi_studies(self, java_studies: List[JavaAnonymizerExportedStudy]):
#         """
#         Process Java PHI studies and store PHI in the AnonymizerModel.

#         Args:
#             java_studies (List[JavaAnonymizerExportedStudy]): List of Java PHI studies.

#         Returns:
#             None
#         """
#         logger.info(f"Processing {len(java_studies)} Java PHI Studies")

#         for java_study in java_studies:
#             self.set_anon_acc_no(java_study.PHI_Accession, java_study.ANON_Accession)
#             self.set_anon_uid(java_study.PHI_StudyInstanceUID, java_study.ANON_StudyInstanceUID)

#             new_study = Study(
#                 study_date=java_study.PHI_StudyDate,
#                 anon_date_delta=int(java_study.DateOffset),
#                 accession_number=java_study.PHI_Accession,
#                 study_uid=java_study.PHI_StudyInstanceUID,
#                 study_desc="?",
#                 source="Java Index File",
#                 series=[],
#             )

#             phi = self._phi_lookup.get(java_study.ANON_PatientID, None)
#             if phi is None:
#                 new_phi = PHI(
#                     patient_name=java_study.PHI_PatientName,
#                     patient_id=java_study.PHI_PatientID,
#                     studies=[new_study],
#                 )
#                 self.set_anon_patient_id(java_study.PHI_PatientID, java_study.ANON_PatientID)
#                 self.set_phi(java_study.ANON_PatientID, new_phi)
#             else:
#                 phi.studies.append(new_study)
