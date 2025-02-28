"""
This module contains the AnonymizerModel class, which is responsible for storing PHI (Protected Health Information)
and anonymization lookups. It also includes data classes for Series, Study, and PHI, as well as a Totals namedtuple.
"""

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
from sqlalchemy.orm import declarative_base, relationship, scoped_session, sessionmaker

from anonymizer.model.project import DICOMNode
from anonymizer.utils.storage import JavaAnonymizerExportedStudy

logger = logging.getLogger(__name__)
Base = declarative_base()


class Series(Base):
    __tablename__ = "Series"

    series_uid = Column(String, primary_key=True)
    series_desc = Column(String, nullable=True)
    modality = Column(String)
    instance_count = Column(Integer)
    study_uid = Column(String, ForeignKey("Study.study_uid"))


class Study(Base):
    __tablename__ = "Study"  # What the table name in the db is called, links the class to the table

    study_uid = Column(String, primary_key=True)  # unique, non-nullable, required, PK
    patient_id = Column(
        String, ForeignKey("PHI.patient_id"), nullable=False
    )  # the ID of the patient assosiated with the study cant have a study without a patient, FK

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

    patient_id = Column(String, primary_key=True)
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

class AnonymizerModelSQL:
    """
    The Anonymizer data model class to store PHI (Protected Health Information) and anonymization lookups.
    """

    # Model Version Control
    MODEL_VERSION = 2
    MAX_PATIENTS = 1000000  # 1 million patients

    _lock = threading.Lock()

    # ✅ Changed
    def __init__(self, site_id: str, uid_root: str, script_path: Path, db_url: str = "sqlite:///anonymizer.db"):
        """
        Initializes an instance of the AnonymizerModelSQL class.

        Args:
            site_id (str): The site ID.
            uid_root (str): The UID root.
            script_path (Path): The path to the script.
            db_url (str): The database URL (default: SQLite file `anonymizer.db`).

        Attributes:
            _session: SQLAlchemy session for database operations.
        """

        self._version = AnonymizerModelSQL.MODEL_VERSION
        self._site_id = site_id
        self._uid_root = uid_root
        self._script_path = script_path

        self._uid_prefix = f"{self._uid_root}.{self._site_id}"
        self.default_anon_pt_id: str = site_id + "-" + "".zfill(len(str(self.MAX_PATIENTS)) - 1)

        # Database connection
        self.engine = create_engine(db_url, echo=False)  # Set echo=True for debugging
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        Base.metadata.create_all(self.engine)  # Create tables if they don't exist
        self._session = self.Session()

        # Initilise quarintied totals
        self._quarantined = 0  # TODO: Implement quarantined tracking, send it quantined directory to count

        # if there is no default patient id in the table create it
        #   default_phi = PHI(patient_id=self.default_anon_pt_id)
        #   self._session.add(default_phi)

        # self.clear_lookups()  # Initializes default patient_id_lookup and phi_lookup
        self.load_script(script_path)




    @property
    def tag_keep(self) -> Set[str]:
        """Fetch all kept tags from the database as a set for fast lookup."""
        with self._lock:
            tags = self._session.query(TagKeep.tag).all()
            return {tag[0] for tag in tags}  # Convert list of tuples to a set

    def is_tag_kept(self, tag: str) -> bool:
        """Check if a tag should be kept (replaces _tag_keep lookup)."""
        return tag in self.tag_keep

    def get_tag_operation(self, tag: str) -> str:
        """Retrieve the operation for a given tag from the database, or return an empty string if not found."""
        with self._lock:
            result = self._session.query(TagKeep.operation).filter_by(tag=tag).first()
            return result[0] if result else ""  # Return empty string if tag not found



    # Model functions

    # ✅Added, ⭕ needs testing
    # after model is deleted in tests try see if any open sessions exist
    def __del__(self):
        """Ensure the database session is closed properly when the instance is deleted."""
        try:
            self._session.close()
        except Exception as e:
            print(f"Error closing session: {e}")

    # ✅ Changed, ✅ Tested
    def get_class_name(self) -> str:
        return self.__class__.__name__

    # ✅ Changed, ✅ Tested
    def __repr__(self) -> str:
        """Returns a summary of the model"""
        try:
            with self._lock:  # Ensuring thread safety if needed
                # Query database for current record counts
                num_patients = self._session.query(PHI).count()
                num_studies = self._session.query(Study).count()
                num_series = self._session.query(Series).count()
                num_instances = self._session.query(func.sum(Study.target_instance_count)).scalar() or 0

                # Build a representation dictionary
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

        except Exception as e:
            self._session.rollback()  # Rollback to maintain DB consistency
            return f"{self.get_class_name()}(Error fetching DB info: {e})"

    # ✅ Changed, ✅ Tested
    def get_totals(self) -> Totals:
        with self._lock:
            return Totals(
                self._session.query(PHI).count(),
                self._session.query(Study).count(),
                self._session.query(Series).count(),
                self._session.query(func.sum(Study.target_instance_count)).scalar() or 0,
                self._quarantined,  # Still uses in-memory `_quarantined`
            )

    # ✅ Changed, ✅ Tested
    def save(self) -> bool:
        """
        Commits the current state of the database session to persist all changes.

        Returns:
            bool: True if the commit was successful, False otherwise.
        """
        with self._lock:
            try:
                self._session.commit()
                logger.debug("Anonymizer Model changes committed to the database.")
                return True
            except Exception as e:
                self._session.rollback()  # Rollback in case of failure
                logger.error(f"Fatal Error saving AnonymizerModel to the database, error: {e}")
                return False

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
        try:
            # Open and parse the XML script file
            root = ET.parse(script_path).getroot()

            # Iterate through 'e' tags and store in the database
            for e in root.findall("e"):
                tag = str(e.attrib.get("t"))
                operation = str(e.text) if e.text is not None else ""

                if "@remove" not in operation:
                    # Check if the tag already exists in the database
                    existing_entry = self._session.query(TagKeep).filter_by(tag=tag).first()

                    if existing_entry:
                        # Fetch the current operation value explicitly (to compare as a string)
                        current_operation = self._session.query(TagKeep.operation).filter_by(tag=tag).scalar()

                        # If the operation has changed, update the value in the database
                        if current_operation != operation:
                            self._session.query(TagKeep).filter_by(tag=tag).update({"operation": operation})
                            logger.info(f"Updated operation for tag: {tag}")
                    else:
                        # If the tag doesn't exist, add a new entry
                        new_entry = TagKeep(tag=tag, operation=operation)
                        self._session.add(new_entry)
                        logger.info(f"Added new tag: {tag} with operation: {operation}")

            # Commit the changes to the database
            self._session.commit()

            logger.info(f"Loaded {len(root.findall('e'))} tags into _tag_keep database table.")

        except FileNotFoundError:
            logger.error(f"{script_path} not found")
            raise

        except ET.ParseError:
            logger.error(f"Error parsing the script file {script_path}. Ensure it is valid XML.")
            raise

        except Exception as e:
            # Catch other generic exceptions and print the error message
            logger.error(f"Error Parsing script file {script_path}: {str(e)}")
            self._session.rollback()
            raise

    # PHI

    # ✅ Changed, ✅ Tested
    def get_phi(self, anon_patient_id: str) -> PHI | None:
        """
        Fetch PHI record from the database using the anonymized patient ID.
        """
        with self._lock:
            try:
                phi_record = self._session.query(PHI).filter_by(patient_id=anon_patient_id).first()
                return phi_record
            except SQLAlchemyError as e:
                self._session.rollback()  # Rollback on error
                logger.error(f"Database error fetching PHI: {e}")  # Log the error
                return None  # Or raise the exception if you want it propagated
            except Exception as e:  # Catch other potential exceptions
                self._session.rollback()
                logger.error(f"An unexpected error occurred: {e}")
                return None

    # ✅ Changed, ✅ Tested
    def get_phi_name(self, anon_patient_id: str) -> str | None:
        """
        Fetch the patient's name from PHI table based on the anonymized patient ID.
        """
        with self._lock:
            phi = self._session.query(PHI).filter_by(patient_id=anon_patient_id).first()
            if phi:
                return str(phi.patient_name) if phi.patient_name else None  # type: ignore #TODO deal with the problem cuaing the usage of the error ignore
            return None

    # ✅ Changed, ✅ Tested
    def set_phi(self, anon_patient_id: str, phi: PHI):
        """
        Insert or update PHI record in the database.
        """
        with self._lock:
            existing_phi = self._session.query(PHI).filter_by(patient_id=anon_patient_id).first()

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
                self._session.add(new_phi)

            self._session.commit()

    # ✅ Changed, ⭕ needs testing
    def get_phi_index(self) -> List[PHI_IndexRecord] | None:
        """
        Reformats PHI data into a format usable by the index.

        Fetches all PHI index records from the database and constructs PHI_IndexRecord objects.

        Returns:
            List[PHI_IndexRecord]: A list of PHI_IndexRecord instances.
        """
        with self._lock:
            # Fetch all necessary data in a single query
            phi_records = (
                self._session.query(
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
                .join(Study, PHI.patient_id == Study.patient_id)
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

            # If no records, return an empty list
            if not phi_records:
                return None

            phi_index = []
            anon_uid_cache = {}
            anon_acc_cache = {}

            for record in phi_records:
                (
                    phi_patient_id,
                    phi_patient_name,
                    phi_study_uid,
                    phi_study_date,
                    anon_date_delta,
                    phi_accession,
                    anon_accession,
                    num_series,
                    num_instances,
                ) = record

                # Fetch anonymized values using cached lookups
                if phi_patient_id not in anon_uid_cache:
                    anon_uid_cache[phi_patient_id] = self.get_anon_patient_id(phi_patient_id)

                if phi_accession not in anon_acc_cache:
                    anon_acc_cache[phi_accession] = self.get_anon_acc_no(phi_accession)

                anon_patient_id = anon_uid_cache[phi_patient_id]
                anon_accession = anon_acc_cache[phi_accession]
                anon_study_uid = self.get_anon_uid(phi_study_uid)

                phi_index.append(
                    PHI_IndexRecord(
                        anon_patient_id=anon_patient_id,
                        anon_patient_name=anon_patient_id,  # No Anon name implmentation yet, uses ID for now
                        phi_patient_id=phi_patient_id,
                        phi_patient_name=phi_patient_name,
                        date_offset=anon_date_delta,
                        phi_study_date=phi_study_date,
                        anon_accession=anon_accession,
                        phi_accession=phi_accession,
                        anon_study_uid=anon_study_uid if anon_study_uid is not None else "",
                        phi_study_uid=phi_study_uid,
                        num_series=num_series,
                        num_instances=num_instances,
                    )
                )

            return phi_index

    # ✅ Changed, ⭕ needs testing
    def capture_phi(self, source: str, ds: Dataset, date_delta: int) -> None:
        """
        Capture PHI (Protected Health Information) from a dataset,
        updating the database instead of using in-memory lookup tables.
        """
        with self._lock:
            # Ensure required UIDs exist
            req_uids = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]
            if not all(hasattr(ds, uid) for uid in req_uids):
                msg = f"Critical Error: Dataset missing primary UIDs: {req_uids}"
                logger.error(msg)
                raise ValueError(msg)

            phi_ptid = ds.PatientID.strip() if hasattr(ds, "PatientID") else ""
            phi_name = ds.PatientName if ds.PatientName else ""

            # Check if patient exists
            phi = self._session.query(PHI).filter_by(patient_id=phi_ptid).first()
            if not phi:
                # Create new patient
                if isinstance(phi_name, PersonName):
                    phi_name = str(phi_name) # Convert PersonName to a simple string if its a PersonName type

                new_anon_patient_id = (
                    f"{self._site_id}-{str(self._session.query(PHI).count()).zfill(len(str(self.MAX_PATIENTS - 1)))}"
                )
                phi = PHI(
                    patient_id=phi_ptid,
                    anon_patient_id=new_anon_patient_id,
                    patient_name=phi_name,
                    sex=ds.get("PatientSex"),
                    dob=ds.get("PatientBirthDate"),
                    ethnic_group=ds.get("EthnicGroup"),
                )
                self._session.add(phi)
                self._session.commit()
            
            # Check if study exists
            study = self._session.query(Study).filter_by(study_uid=ds.StudyInstanceUID).first()
            if not study:
                # Create new study using helper function
                study = self.new_study_from_dataset(ds, source, date_delta)
                phi.studies.append(study)  # Link study to patient
                self._session.commit()
            
            # Check if series exists
            series = self._session.query(Series).filter_by(series_uid=ds.SeriesInstanceUID).first()
            if not series:
                # New series in existing study
                series = Series(
                    series_uid=ds.get("SeriesInstanceUID"),
                    series_desc=ds.get("SeriesDescription"),
                    modality=ds.get("Modality"),
                    instance_count=1,
                    study_uid=study.study_uid,
                )
                self._session.add(series)
                self._session.commit()
            else:
                # New instance in existing series
                self._session.query(Series).filter_by(series_uid=ds.SeriesInstanceUID).update({"instance_count": Series.instance_count + 1})
                self._session.commit()
            
            # Store anonymized UIDs
            for uid in req_uids:
                if not self._session.query(UID).filter_by(phi_uid=getattr(ds, uid)).first():
                    anon_uid = f"{self._uid_prefix}.{self.get_uid_count() + 1}"
                    self._session.add(UID(phi_uid=getattr(ds, uid), anon_uid=anon_uid))
            
            self._session.commit()

    # ✅ Changed, ⭕ needs testing
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
        with self._lock:
            session = self._session

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

            session.query(Series).filter(Series.study_uid == anon_study_uid).delete()

            # Remove study from database
            session.delete(study)

            # Check if the patient has any other studies left
            remaining_studies = session.query(Study).filter(Study.patient_id == phi.patient_id).count()

            # Remove the patient if they have no more studies
            if remaining_studies == 0:
                session.delete(phi)

            # Commit changes
            session.commit()

            # Update counters
            # self._studies -= 1
            # self._series -= num_series
            # self._instances -= num_instances

            # if remaining_studies == 0:
            #     self._patients -= 1

            return True

    # ❌ Not changed yet, need to use the database not the lookup
    def process_java_phi_studies(self, java_studies: List[JavaAnonymizerExportedStudy]):
        """
        Process Java PHI studies and store PHI in the AnonymizerModel.

        Args:
            java_studies (List[JavaAnonymizerExportedStudy]): List of Java PHI studies.

        Returns:
            None
        """
        logger.info(f"Processing {len(java_studies)} Java PHI Studies")

        for java_study in java_studies:
            # self.set_anon_acc_no(java_study.PHI_Accession, java_study.ANON_Accession)
            self.set_anon_uid(java_study.PHI_StudyInstanceUID, java_study.ANON_StudyInstanceUID)

            new_study = Study(
                study_date=java_study.PHI_StudyDate,
                anon_date_delta=int(java_study.DateOffset),
                accession_number=java_study.PHI_Accession,
                study_uid=java_study.PHI_StudyInstanceUID,
                # anon_accession_number = anon_accession_number_count + 1
                study_desc="?",
                source="Java Index File",
                series=[],
            )

            phi = self._phi_lookup.get(java_study.ANON_PatientID, None)
            if phi is None:
                new_phi = PHI(
                    patient_name=java_study.PHI_PatientName,
                    patient_id=java_study.PHI_PatientID,
                    studies=[new_study],
                )
                self.set_anon_patient_id(java_study.PHI_PatientID, java_study.ANON_PatientID)
                self.set_phi(java_study.ANON_PatientID, new_phi)
            else:
                phi.studies.append(new_study)

    # Patients

    # ✅ Changed, ✅ Tested
    def set_anon_patient_id(self, phi_patient_id: str, anon_patient_id: str):
        """
        Updates the anonymized patient ID for an existing PHI record.
        Raises an error if the PHI record does not exist.
        """
        with self._lock:
            existing_entry = self._session.query(PHI).filter_by(patient_id=phi_patient_id).first()

            if existing_entry:
                self._session.query(PHI).filter_by(patient_id=phi_patient_id).update(
                    {"anon_patient_id": anon_patient_id}
                )
                logger.info(f"Updated anonymized patient ID for {phi_patient_id} -> {anon_patient_id}")
                self._session.commit()
            else:
                logger.error(f"Cannot set anon_patient_id: No PHI record found for patient_id {phi_patient_id}")
                raise ValueError(f"No PHI record found for patient_id {phi_patient_id}")

    # ✅ Changed, ✅ Tested
    def get_anon_patient_id(self, phi_patient_id: str) -> str | None:
        """
        Retrieves the anonymized patient ID for a given PHI patient ID.
        Returns None if not found.
        """
        with self._lock:
            record = self._session.query(PHI).filter_by(patient_id=phi_patient_id).first()
            if record:
                return str(record.anon_patient_id) if record.anon_patient_id else None  # type: ignore #TODO deal with the problem cuaing the usage of the error ignore
            return None

    # ✅ Changed, ✅ Tested
    def get_patient_id_count(self) -> int:
        """
        Get the number of patients in the PHI table
        """
        with self._lock:
            return self._session.query(func.count(PHI.patient_id)).scalar() or 0

    # UID

    # ✅ Changed, ✅ Tested
    def get_anon_uid(self, phi_uid: str) -> str | None:
        """
        Retrieves the anonymized UID for a given PHI UID.
        Returns None if not found.
        """
        with self._lock:
            record = self._session.query(UID).filter_by(phi_uid=phi_uid).first()
            if record:
                return (
                    str(record.anon_uid) if str(record.anon_uid) else None
                )  # TODO make sure converting to string does not change the none
            return None

    # ✅ Changed, ✅ Tested
    def uid_received(self, phi_uid: str) -> bool:
        """
        Checks if a given PHI UID exists in the database.
        """
        with self._lock:
            return self._session.query(UID).filter_by(phi_uid=phi_uid).first() is not None

    # ✅ Changed, ✅ Tested
    def remove_uid(self, phi_uid: str):
        """
        Deletes the corresponding phi_uid from the UID table.
        """
        with self._lock:
            deleted_rows = self._session.query(UID).filter_by(phi_uid=phi_uid).delete()
            if deleted_rows:
                logger.info(f"Deleted UID record for phi_uid: {phi_uid}")
            self._session.commit()

    # ✅ Changed, ✅ Tested
    def remove_uid_inverse(self, anon_uid: str):
        """
        Deletes the UID record where the anonymized UID matches.
        """
        with self._lock:
            deleted_rows = self._session.query(UID).filter_by(anon_uid=anon_uid).delete()
            if deleted_rows:
                logger.info(f"Deleted UID record for anon_uid: {anon_uid}")
            self._session.commit()

    # ✅ Changed, ✅ Tested
    def get_uid_count(self) -> int:
        """
        Returns the number of UID mappings in the database.
        """
        with self._lock:
            return self._session.query(func.count(UID.uid_pk)).scalar() or 0

    # ✅ Changed, ✅ Tested
    def set_anon_uid(self, phi_uid: str, anon_uid: str):
        """
        Adds or updates a UID mapping in the database.
        """
        with self._lock:
            existing_entry = self._session.query(UID).filter_by(phi_uid=phi_uid).first()

            if existing_entry:
                self._session.query(UID).filter_by(phi_uid=phi_uid).update({"anon_uid": anon_uid})
                logger.info(f"Updated UID mapping: {phi_uid} -> {anon_uid}")
            else:
                new_entry = UID(phi_uid=phi_uid, anon_uid=anon_uid)
                self._session.add(new_entry)
                logger.info(f"Inserted new UID mapping: {phi_uid} -> {anon_uid}")

            self._session.commit()

    # ✅ Changed, ✅ Tested
    def get_next_anon_uid(self, phi_uid: str) -> str:
        """
        Generates and stores a new anonymized UID using the last UID + 1.
        """
        with self._lock:
            # Get the highest UID primary key
            last_uid_pk = self._session.query(func.max(UID.uid_pk)).scalar() or 0
            new_uid_pk = last_uid_pk + 1

            # Generate anonymized UID
            anon_uid = f"{self._uid_prefix}.{new_uid_pk}"

            # Insert new record
            new_entry = UID(phi_uid=phi_uid, anon_uid=anon_uid)
            self._session.add(new_entry)
            self._session.commit()

            logger.info(f"Generated new anon UID: {anon_uid} for PHI UID: {phi_uid}")
            return anon_uid

        # Accession

    # Accession

    # ✅ Changed, ✅ Tested
    def get_anon_acc_no(self, phi_acc_no: str) -> str | None:
        """
        Retrieves the anonymized accession number for a given PHI accession number.
        Returns None if not found.
        """
        with self._lock:
            record = self._session.query(Study).filter_by(accession_number=phi_acc_no).first()
            if record:
                return str(record.anon_accession_number) if record.anon_accession_number else None  # type: ignore
            return None

    # ✅ Changed, ✅ Tested
    def get_next_anon_acc_no(self, phi_acc_no: str) -> str:
        with self._lock:
            # Retrieve the highest existing anon_accession_number_count from the Study table
            next_anon_acc_no = (self._session.query(func.max(Study.anon_accession_number_count))
                                .scalar() or 0) + 1

            return str(next_anon_acc_no)

    # ✅ Changed, ✅ Tested
    def get_acc_no_count(self) -> int:
        """
        Returns the highest anon_accession_number_count from the Study table.
        """
        with self._lock:
            return self._session.query(func.max(Study.anon_accession_number_count)).scalar() or 0

    # ✅ Added, ✅ Tested
    def set_anon_acc_no(self, study_uid: str, anon_accession: str) -> None:
        """
        Sets the anonymized accession number for a given study by its study UID.

        Args:
            study_uid (str): The study UID.
            anon_accession (str): The new anonymized accession number.

        Raises:
            ValueError: If no study with the provided study UID is found.
        """
        with self._lock:
            # Look up the study by study_uid
            study = self._session.query(Study).filter_by(study_uid=study_uid).first()

            if not study:
                raise ValueError(f"Study with study UID {study_uid} not found.")

            # Update the anonymized accession number
            study.anon_accession = anon_accession

            # Commit the changes to the database
            self._session.commit()

    # Instances

    # ✅ Changed, ✅ Tested
    def get_stored_instance_count(self, ptid: str, study_uid: str) -> int:
        """
        Retrieves the number of stored instances for a given patient ID and study UID.
        """
        with self._lock:
            # Get the PHI record for the patient
            phi_entry = self._session.query(PHI).filter_by(patient_id=ptid).first()
            if not phi_entry:
                return 0

            # Get the Study entry for the given study UID
            study_entry = self._session.query(Study).filter_by(study_uid=study_uid, patient_id=ptid).first()
            if not study_entry:
                return 0

            # Sum all instance counts from related Series
            total_instances = (
                self._session.query(func.sum(Series.instance_count)).filter_by(study_uid=study_uid).scalar() or 0
            )
            return total_instances

    # ✅ Changed, ✅ Tested
    def get_pending_instance_count(self, ptid: str, study_uid: str, target_count: int) -> int:
        """
        Returns the difference between stored instances and target_count for a given study.
        Also ensures study.target_instance_count is set.
        """
        with self._lock:
            study = self._session.query(Study).filter_by(study_uid=study_uid, patient_id=ptid).first()
            if not study:
                return target_count  # No study found, assume all instances are pending

            # Update target_instance_count if it's not set
            if study.target_instance_count == 0:  # type: ignore
                self._session.query(Study).filter_by(study_uid=study_uid, patient_id=ptid).update(
                    {"target_instance_count": target_count}
                )
                self._session.commit()

            # Get total stored instance count
            stored_instance_count = (
                self._session.query(func.sum(Series.instance_count)).filter_by(study_uid=study_uid).scalar() or 0
            )

            return max(0, target_count - stored_instance_count)  # Ensure non-negative

    # Series

    # ✅ Changed, ✅ Tested
    def series_complete(self, ptid: str, study_uid: str, series_uid: str, target_count: int) -> bool:
        """
        Check if a series is complete by comparing stored instances to the target count.
        """
        with self._lock:
            # Get the Series record
            series = self._session.query(Series).filter_by(series_uid=series_uid, study_uid=study_uid).first()

            # If series does not exist, it cannot be complete
            if not series:
                return False

            return series.instance_count >= target_count  # type: ignore

    # Study

    # ✅ Changed, ⭕ needs testing
    def study_imported(self, ptid: str, study_uid: str) -> bool:
        """
        Checks if a study has already been imported by comparing stored instance count to target.

        Used by QueryRetrieveView to prevent study re-import
        """
        with self._lock:
            # Fetch the Study record
            study = self._session.query(Study).filter_by(study_uid=study_uid, patient_id=ptid).first()
            if not study or study.target_instance_count.value == 0:
                return False  # Not imported yet or target count not set

            # Sum all stored instances across series in the study
            stored_instance_count = (
                self._session.query(func.sum(Series.instance_count)).filter_by(study_uid=study_uid).scalar() or 0
            )

            return stored_instance_count >= study.target_instance_count.value

    # ✅ Changed, ✅ Tested
    def new_study_from_dataset(self, ds: Dataset, source: DICOMNode | str, date_delta: int) -> Study:
        """
        Creates a new Study record from the dataset, ensuring anon_accession_number is correctly assigned.

        Retrieves the highest anon_accession_number_count from the database and increments it for the new study.
        """
        with self._lock:
            # Retrieve the next anon_accession_number_count from the DB
            next_anon_acc_no_count = (self._session.query(func.max(Study.anon_accession_number_count))
                                    .scalar() or 0) + 1

            new_study = Study(
                study_uid=ds.get("StudyInstanceUID"),
                study_date=ds.get("StudyDate"),
                patient_id=ds.get("PatientID"),
                anon_date_delta=date_delta,
                accession_number=ds.get("AccessionNumber"),
                anon_accession_number_count=next_anon_acc_no_count,  # Use incremented value
                anon_accession_number=str(next_anon_acc_no_count),  # Ensure it's a string for consistency
                study_desc=ds.get("StudyDescription"),
                source=source,
                series=[
                    Series(
                        series_uid=ds.get("SeriesInstanceUID"),
                        series_desc=ds.get("SeriesDescription"),
                        modality=ds.get("Modality"),
                        instance_count=1,
                    )
                ],
            )

            # Commit the study to the database so anon_accession_number_count is reserved
            self._session.add(new_study)
            self._session.commit()

            return new_study

    # Quarantined

    # ✅ No changes needed, ✅ Tested
    def increment_quarantined(self):
        self._quarantined += 1
