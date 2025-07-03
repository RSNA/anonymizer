"""
This module contains the AnonymizerModel class, which is responsible for storing PHI (Protected Health Information)
and anonymization lookups. It also includes SQLAlchemy ORM classes for Series, Study, and PHI, as well as NamedTuple class for Totals.
"""

import hashlib
import logging
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, fields
from functools import wraps
from pathlib import Path
from pprint import pformat
from typing import ClassVar, NamedTuple

from pydicom import Dataset
from sqlalchemy import ForeignKey, Integer, String, create_engine, delete, func, select
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    Session,
    joinedload,
    mapped_column,
    relationship,
    scoped_session,
    selectinload,
    sessionmaker,
)

from anonymizer.utils.storage import JavaAnonymizerExportedStudy

logger = logging.getLogger(__name__)


class Base(MappedAsDataclass, DeclarativeBase):
    pass


class Instance(Base):
    __tablename__ = "instances"
    sop_instance_uid: Mapped[str] = mapped_column(String, primary_key=True)
    anon_sop_instance_uid: Mapped[str] = mapped_column(String, unique=True, index=True)
    series_uid: Mapped[str] = mapped_column(String, ForeignKey("series.series_uid"))
    series: Mapped["Series"] = relationship(back_populates="instances", init=False)


class Series(Base):
    __tablename__ = "series"

    series_uid: Mapped[str] = mapped_column(String, primary_key=True)
    anon_series_uid: Mapped[str] = mapped_column(String, unique=True, index=True)
    study_uid: Mapped[str] = mapped_column(String, ForeignKey("studies.study_uid"))
    study: Mapped["Study"] = relationship(back_populates="series", init=False)
    modality: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, default=None)

    instances: Mapped[list["Instance"]] = relationship(
        back_populates="series", cascade="all, delete-orphan", init=False
    )


class Study(Base):
    __tablename__ = "studies"

    study_uid: Mapped[str] = mapped_column(String, primary_key=True)
    anon_study_uid: Mapped[str] = mapped_column(String, unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("phi.patient_id"))
    patient: Mapped["PHI"] = relationship(back_populates="studies", init=False)
    source: Mapped[str] = mapped_column(String)
    study_date: Mapped[str] = mapped_column(String)
    anon_date_delta: Mapped[int] = mapped_column(Integer)
    accession_number: Mapped[str | None] = mapped_column(String, index=True)
    anon_accession_number: Mapped[str | None] = mapped_column(String, index=True)
    description: Mapped[str | None] = mapped_column(String, default=None)
    target_instance_count: Mapped[int] = mapped_column(Integer, default=0)

    series: Mapped[list[Series]] = relationship(back_populates="study", cascade="all, delete-orphan", init=False)


class PHI(Base):
    __tablename__ = "phi"

    patient_id: Mapped[str] = mapped_column(String, primary_key=True)
    anon_patient_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    patient_name: Mapped[str | None] = mapped_column(String, default=None)
    sex: Mapped[str | None] = mapped_column(String, default=None)
    dob: Mapped[str | None] = mapped_column(String, default=None)
    ethnic_group: Mapped[str | None] = mapped_column(String, default=None)

    studies: Mapped[list[Study] | None] = relationship(
        back_populates="patient", cascade="all, delete-orphan", init=False
    )


# Used to map all PHI DICOM UIDs to anonymized UIDs
class UID(Base):
    __tablename__ = "UID_map"

    mapping_pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, init=False)
    anon_uid: Mapped[str] = mapped_column(String, unique=True, index=True)
    phi_uid: Mapped[str] = mapped_column(String, unique=True, index=True)


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

    field_titles: ClassVar[dict[str, str]] = {
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

    def flatten(self) -> tuple:
        return tuple(getattr(self, field.name) for field in fields(self))

    @classmethod
    def get_field_names(cls) -> list:
        return [field.name for field in fields(cls)]


class Totals(NamedTuple):
    patients: int
    studies: int
    series: int
    instances: int


def use_session(is_read_only_operation: bool = False):
    """
    Decorator for AnonymizerModel methods to apply the context manager
    and ensure they run within a managed, thread-safe SQLAlchemy session context.
    """

    def decorator(wrapped_method):
        @wraps(wrapped_method)
        def wrapper(self: "AnonymizerModel", *args, **kwargs):
            # The get_session context manager will get the session from the
            # thread-safe factory and ensure it's closed/removed after use.
            with self._get_session(read_only=is_read_only_operation):
                # The wrapped method can now safely access self.session,
                # which will provide the correct session for its thread.
                return wrapped_method(self, *args, **kwargs)

        return wrapper

    return decorator


class MissingSessionError(RuntimeError):
    def __init__(self, message="Critical Error: No session provided or available."):
        super().__init__(message)


class AnonymizerModel:
    """
    The Anonymizer data model class to store PHI (Protected Health Information) with anonymized key lookups.
    """

    # Model Version Control
    MODEL_VERSION = 2
    MAX_PATIENTS = 1000000  # 1 million patients
    # The primary key value for the PHI record representing studies with no/empty PatientID
    DEFAULT_PHI_PATIENT_ID_PK_VALUE: ClassVar[str] = ""  # "" is used as the primary key for the default PHI record
    DEFAULT_PHI_STUDY_DATE = "19000101"

    def __init__(self, site_id: str, uid_root: str, script_path: Path, db_url: str, db_echo: bool = False):
        """
        Initializes an instance of the AnonymizerModelSQL class.

        Args:
            site_id (str): The site ID.
            uid_root (str): The UID root.
            script_path (Path): The path to the anonymization script.
            db_url (str): The database URL which can be a file path (eg. SQLite) or a connection string (eg. PostgreSQL).
        Raises:
            ValueError: If the site_id or uid_root is empty.
            FileNotFoundError: If the script file does not exist.
            Exception: general exception.
        """
        self._version = AnonymizerModel.MODEL_VERSION
        if not site_id:
            raise ValueError("site_id cannot be empty.")
        if not uid_root:
            raise ValueError("uid_root cannot be empty.")
        if not script_path.exists():
            raise FileNotFoundError(f"Script file {script_path} does not exist.")
        if not db_url:
            raise ValueError("db_url cannot be empty.")
        self._site_id = site_id
        self._uid_root = uid_root.strip()
        self._script_path = script_path
        self._db_url = db_url
        self._uid_prefix = f"{self._uid_root}.{self._site_id}"
        # Default anon_patient_id for the default PHI record
        self.default_anon_pt_id: str = self._format_anon_patient_id(0)
        self._tag_keep: dict[str, str] = {}
        # Create the deterministic, project-specific salt for accession_number hash:
        salt_string = f"anonymizer::{self._site_id}::{self._uid_prefix}"
        self._accession_salt = salt_string.encode("utf-8")

        # Establish Database connection
        self.engine = create_engine(db_url, echo=db_echo, future=True)  # TODO: see dbengine_logging for logging config

        # Construct Thread Local Scoped Session Factory
        self.session_factory = scoped_session(sessionmaker(bind=self.engine))

        # Create tables IFF they don't exist
        Base.metadata.create_all(self.engine)

        # Default PHI record: (patient_id=DEFAULT_PHI_PATIENT_ID_PK_VALUE, anon_patient_id = site_id + "-000000")
        self._add_default_PHI()
        self._load_script(script_path)

    def _get_class_name(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        model_summary = {
            "version": self._version,
            "site_id": self._site_id,
            "uid_root": self._uid_root,
            "db_url": self._db_url,
            "script_path": str(self._script_path),
            # "totals": self.get_totals(),
        }

        return f"{self._get_class_name()}\n({pformat(model_summary)})"

    @property
    def session(self) -> Session:
        """
        Returns the thread-local session from the scoped session factory.
        """
        return self.session_factory()

    # Database Session Manager
    @contextmanager
    def _get_session(self, read_only: bool = False):
        """Provides a scoped SQLAlchemy self.session."""
        session = self.session_factory()
        logger.debug(f"Session {id(session)} opened (read_only={read_only}).")
        try:
            yield session
            if not read_only:  # Only commit if not read_only
                logger.debug(f"Committing session {id(session)}.")
                session.commit()
        except Exception:
            logger.exception(f"Exception in session {id(session)}, rolling back.")
            session.rollback()
            raise
        finally:
            logger.debug(f"Closing session {id(session)}.")
            session.close()

    def _format_anon_patient_id(self, phi_index: int) -> str:
        """
        Formats the anonymized patient ID using the site_id and a zero-padded based on max patients index.
        """
        return f"{self._site_id}-{str(phi_index).zfill(len(str(self.MAX_PATIENTS)) - 1)}"

    @use_session()
    def _add_default_PHI(self):
        """
        Ensures a default PHI record (patient_id NULL, default anon_pt_id) exists in the PHI table.
        """
        default_phi = self.session.get(PHI, self.DEFAULT_PHI_PATIENT_ID_PK_VALUE)

        if default_phi:
            logger.info(
                f"Default PHI record with patient_id={self.DEFAULT_PHI_PATIENT_ID_PK_VALUE}, anon_id:{default_phi.anon_patient_id} already exists"
            )
            # Ensure its anon_patient_id is what we expect for the default
            if default_phi.anon_patient_id != self.default_anon_pt_id:
                logger.warning(
                    f"Default PHI record patient_id={self.DEFAULT_PHI_PATIENT_ID_PK_VALUE} has an unexpected anon_id: "
                    f"{default_phi.anon_patient_id} Updating to:{self.default_anon_pt_id}"
                )
                default_phi.anon_patient_id = self.default_anon_pt_id
            return
        else:
            logger.info(
                f"Adding default PHI record with PK '{self.DEFAULT_PHI_PATIENT_ID_PK_VALUE}' "
                f"and anon_id '{self.default_anon_pt_id}' to the database."
            )
            new_default_phi = PHI(
                patient_id=self.DEFAULT_PHI_PATIENT_ID_PK_VALUE,
                anon_patient_id=self.default_anon_pt_id,
                # Other PHI fields like patient_name, sex, dob will use their MappedAsDataclass defaults (None)
            )
            self.session.add(new_default_phi)
            # Commit will be handled by @use_session on successful exit of wrapper

    def _load_script(self, script_path: Path):
        """
        Load and parse an anonymize script file to populate the _tag_keep dictionary.
        This method reads an XML file that defines which DICOM tags to keep and their associated operations.
        The XML file should have a structure where each 'e' element represents a tag to keep,
        with the tag name as an attribute 't' and the operation as the text content of the element.
        The operations can include instructions like "@remove" to indicate that the tag should be removed,
        or simply be left empty to indicate that the tag should be kept without modification.
        Refer to AnonymizerController._anonymize_element to see which operations are available and how they are applied.

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

            # Extract 'e' tags into _tag_keep dictionary
            # IGNORE "en" = "T" or "F" - Java UX checkbox
            # Tags with no operation or specified operation (which can be @remove) are added to tag_keep dictionary
            # ALL unspecified tags are removed
            for e in root.findall("e"):
                tag = str(e.attrib.get("t"))
                operation = str(e.text) if e.text is not None else ""
                if "@remove" not in operation:
                    self._tag_keep[tag] = operation

            # TODO: Handle (and TCIA required date handling, id lookups, sequences?, private tags):
            # <r en="T" t="curves">Remove curves</r>
            # <r en="T" t="overlays">Remove overlays</r>
            # <r en="T" t="privategroups">Remove private groups</r> # pydicom.remove_private_tags() * currently removed by default

            filtered_tag_keep = {k: v for k, v in self._tag_keep.items() if v != ""}
            logger.info(f"_tag_keep has {len(self._tag_keep)} entries with {len(filtered_tag_keep)} operations")
            logger.info(f"_tag_keep operations:\n{pformat(filtered_tag_keep)}")
            return

        except FileNotFoundError:
            logger.error(f"{script_path} not found")
            raise

        except ET.ParseError:
            logger.error(f"Error parsing script file {script_path}. Ensure it is valid XML.")
            raise

        except Exception as e:
            # Catch other generic exceptions and log the error message
            logger.error(f"Error Parsing script file {script_path}: {str(e)}")
            raise

    @use_session(is_read_only_operation=True)
    def get_totals(self) -> Totals:
        return Totals(
            patients=self.session.execute(select(func.count()).select_from(PHI)).scalar_one()
            - 1,  # don't include default patient
            studies=self.session.execute(select(func.count()).select_from(Study)).scalar_one(),
            series=self.session.execute(select(func.count()).select_from(Series)).scalar_one(),
            instances=self.session.execute(select(func.count()).select_from(Instance)).scalar_one(),
        )

    @use_session(is_read_only_operation=True)
    def get_phi_by_anon_patient_id(self, anon_patient_id: str) -> PHI | None:
        """
        Fetch PHI record from the database using the anonymized patient ID.
        """
        stmt = (
            select(PHI)
            .where(PHI.anon_patient_id == anon_patient_id)
            .options(selectinload(PHI.studies).selectinload(Study.series).selectinload(Series.instances))
        )
        return self.session.execute(stmt).scalar_one_or_none()

    @use_session(is_read_only_operation=True)
    def get_phi_by_phi_patient_id(self, phi_patient_id: str) -> PHI | None:
        """
        Fetch PHI record from the database using the PHI patient ID.
        """
        stmt = (
            select(PHI)
            .where(PHI.patient_id == phi_patient_id)
            .options(selectinload(PHI.studies).selectinload(Study.series).selectinload(Series.instances))
        )
        return self.session.execute(stmt).scalar_one_or_none()

    @use_session(is_read_only_operation=True)
    def get_phi_name_by_anon_patient_id(self, anon_patient_id: str) -> str | None:
        """
        Fetch the patient's name from PHI table based on the anonymized patient ID.
        """
        stmt = select(PHI).where(PHI.anon_patient_id == anon_patient_id)
        phi = self.session.execute(stmt).scalar_one_or_none()
        return phi.patient_name if phi else None

    @use_session(is_read_only_operation=True)
    def get_phi_index(self) -> list[PHI_IndexRecord] | None:
        """
        Retrieves fully populated PHI objects (with their studies and series)
        using SQLAlchemy ORM eager loading and formats them into PHI_IndexRecord.
        """
        phi_index_records: list[PHI_IndexRecord] = []

        # Eagerly load PHI.studies, and for each Study, eagerly load its Series.
        stmt = select(PHI).options(selectinload(PHI.studies).selectinload(Study.series).selectinload(Series.instances))

        # Execute the query:
        # .scalars() gets the PHI objects directly.
        # .all() fetches all results.
        all_phi_instances = self.session.execute(stmt).scalars().all()

        if not all_phi_instances:
            return None

        for phi in all_phi_instances:
            if phi.studies is None:
                continue

            for study in phi.studies:
                num_series = len(study.series)
                num_instances = sum(len(s.instances) for s in study.series if s.instances is not None)

                phi_index_record = PHI_IndexRecord(
                    anon_patient_id=phi.anon_patient_id,
                    anon_patient_name=phi.anon_patient_id,
                    phi_patient_id=phi.patient_id,
                    phi_patient_name=phi.patient_name if phi.patient_name else "",
                    date_offset=study.anon_date_delta,
                    phi_study_date=study.study_date,
                    anon_accession=str(study.anon_accession_number),
                    phi_accession=study.accession_number if study.accession_number else "",
                    anon_study_uid=study.anon_study_uid,
                    phi_study_uid=study.study_uid,
                    num_series=num_series,
                    num_instances=num_instances,
                )
                phi_index_records.append(phi_index_record)

        return phi_index_records if phi_index_records else None

    @use_session(is_read_only_operation=True)
    def get_anon_patient_id(self, phi_patient_id: str) -> str | None:
        """
        Retrieves the anonymized patient ID for a given PHI patient ID.
        Returns None if not found.
        """
        stmt = select(PHI.anon_patient_id).where(PHI.patient_id == phi_patient_id)
        return self.session.execute(stmt).scalar_one_or_none()

    @use_session(is_read_only_operation=True)
    def get_patient_id_count(self) -> int:
        """
        Get the number of patients in the PHI table.
        """
        return self.session.execute(select(func.count()).select_from(PHI)).scalar_one()

    @use_session(is_read_only_operation=True)
    def get_anon_uid(self, phi_uid: str) -> str | None:
        """
        Retrieves the anonymized UID for a given phi UID.
        Returns None if not found.
        """
        stmt = select(UID.anon_uid).where(UID.phi_uid == phi_uid)
        return self.session.execute(stmt).scalar_one_or_none()

    def _create_anon_uid(self, phi_uid: str) -> str:
        """
        Generates a new anonymized UID based on the UID prefix and the next mapping primary key.
        This is used internally to create a new UID mapping.
        """
        new_mapping = UID(phi_uid=phi_uid, anon_uid="placeholder")
        self.session.add(new_mapping)
        self.session.flush()  # Send the INSERT to the DB and populates new_mapping.mapping_pk
        new_anon_uid = f"{self._uid_prefix}.{new_mapping.mapping_pk}"
        new_mapping.anon_uid = new_anon_uid  # Marks the object for UPDATE on final commit
        return new_anon_uid

    @use_session()
    def get_or_create_anon_uid(self, phi_uid: str) -> str:
        """
        Searches UID map for via phi_uid returns corresponding anon_uid if found,
        otherwise creates a new UID record with a new anon_uid.
        """
        stmt = select(UID.anon_uid).where(UID.phi_uid == phi_uid)
        anon_uid: str | None = self.session.execute(stmt).scalar_one_or_none()

        if anon_uid:
            return anon_uid
        else:
            return self._create_anon_uid(phi_uid)

    @use_session(is_read_only_operation=True)
    def uid_received(self, phi_uid: str) -> bool:
        """
        Checks if a given PHI UID exists in the database.
        """
        stmt = select(UID.phi_uid).where(UID.phi_uid == phi_uid)
        return self.session.execute(select(stmt.exists())).scalar_one()

    @use_session(is_read_only_operation=True)
    def instance_received(self, sop_instance_uid: str) -> bool:
        return self.session.get(Instance, sop_instance_uid) is not None

    @use_session()
    def remove_uid(self, phi_uid: str) -> None:
        """
        Deletes the corresponding phi_uid from the UID table.
        """
        stmt = delete(UID).where(UID.phi_uid == phi_uid)
        result = self.session.execute(stmt)
        if result.rowcount > 0:
            logger.info(f"Deleted UID record for phi_uid: {phi_uid}")

    @use_session()
    def remove_uid_inverse(self, anon_uid: str) -> None:
        """
        Deletes the UID record where the anonymized UID matches.
        """
        stmt = delete(UID).where(UID.anon_uid == anon_uid)
        result = self.session.execute(stmt)
        if result.rowcount > 0:
            logger.info(f"Deleted UID record for anon_uid: {anon_uid}")

    @use_session(is_read_only_operation=True)
    def get_anon_acc_no(self, phi_acc_no: str) -> str | None:
        stmt = select(Study.anon_accession_number).where(Study.accession_number == phi_acc_no)
        return self.session.execute(stmt).scalar_one_or_none()

    @use_session(is_read_only_operation=True)
    def get_stored_instance_count(self, study_uid: str) -> int:
        """
        Retrieves the number of stored instances for a given study UID.
        """
        stmt = (
            select(Study)
            .where(Study.study_uid == study_uid)
            .options(selectinload(Study.series).selectinload(Series.instances))
        )
        study: Study | None = self.session.execute(stmt).unique().scalar_one_or_none()
        if not study:  # first instance of study has not arrived yet
            return 0

        return sum(len(series.instances) for series in study.series)

    @use_session()
    def get_pending_instance_count(self, study_uid: str, target_count: int) -> int:
        """
        This will return difference between stored instances and target_count for a given patient ID & study UID
        When first called for a study it also sets the study.target_instance_count (for future imported state detection)

        Args:
            ptid (str): The patient ID.
            study_uid (str): The study UID.
            target_count (int): The target count.

        Returns:
            int: The pending instance count.
        """
        stmt = (
            select(Study)
            .where(Study.study_uid == study_uid)
            .options(selectinload(Study.series).selectinload(Series.instances))
        )
        study: Study | None = self.session.execute(stmt).unique().scalar_one_or_none()
        if not study:  # first instance of study has not arrived yet
            return target_count
        else:
            study.target_instance_count = target_count
            return target_count - sum(len(series.instances) for series in study.series)

    @use_session(is_read_only_operation=True)
    def series_complete(self, series_uid: str, target_count: int) -> bool:
        """
        Check if a series is complete based on the given parameters.

        Args:
            series_uid (str): The series UID.
            target_count (int): The target instance count.

        Returns:
            bool: True if the series is complete, False otherwise.
        """
        series = self.session.get(Series, series_uid)
        return bool(series and len(series.instances) >= target_count)

    @use_session(is_read_only_operation=True)
    def study_imported(self, study_uid: str) -> bool:
        """
        Compares Study.target_instance_count to sum of Series.instance_count for all series in the Study specified by study_uid
        Used by QueryRetrieveView to prevent study re-import

        Returns False if target_instance_count is not set (0) or if no series exist in the study.
        """
        stmt = (
            select(Study)
            .where(Study.study_uid == study_uid)
            .options(selectinload(Study.series).selectinload(Series.instances))
        )
        study: Study | None = self.session.execute(stmt).unique().scalar_one_or_none()

        if not study or study.target_instance_count == 0:  # Not set by ProjectController import process yet
            return False

        return sum(len(series.instances) for series in study.series) >= study.target_instance_count

    # --- Helper methods for capture_phi ---
    # These helpers will be called by capture_phi and use the session provided by capture_phi's decorator.
    # They do not need their own @use_session decorator if only called by capture_phi.
    def _hash_accession_number(self, original_accession: str) -> str:
        """
        Generates a secure, 16-character hexadecimal hash for an accession number,
        formatted for readability.
        """
        accession_bytes = str(original_accession or "").encode("utf-8")

        hasher = hashlib.sha256()
        hasher.update(self._accession_salt)
        hasher.update(accession_bytes)

        # Take the first 16 characters of the full 64-character hex digest
        hex_digest_16_chars = hasher.hexdigest()[:16]
        # Format the hash as 8-4-4 (UUID-like format)
        formatted_hash = f"{hex_digest_16_chars[:8]}-{hex_digest_16_chars[8:12]}-{hex_digest_16_chars[12:]}"

        return formatted_hash

    def _get_or_create_phi(self, ds: Dataset) -> PHI:
        # If PHI PatientID is missing in dataset, as per DICOM Standard, pydicom should return "", handle missing attribute
        # Missing or blank corresponds to AnonymizerModel.DEFAULT_ANON_PATIENT_ID ("000000") initialised in AnonymizerModel.add_default_PHI()
        phi_ptid = str(ds.PatientID).strip() if hasattr(ds, "PatientID") else ""

        phi: PHI | None = self.session.get(PHI, phi_ptid)
        if phi:
            logger.debug(f"Found existing PHI record for patient_id: {phi_ptid}")
            return phi

        logger.info(f"Creating PHI record for patient_id: {phi_ptid}")
        # Generate a NEW anon_patient_id based on the site_id and the current patient count:
        phi_count = self.session.execute(select(func.count()).select_from(PHI)).scalar_one()
        anon_ptid = self._format_anon_patient_id(phi_index=phi_count)

        new_phi: PHI = PHI(
            patient_id=phi_ptid,
            anon_patient_id=anon_ptid,
            patient_name=str(ds.get("PatientName")) if hasattr(ds, "PatientName") else None,
            sex=str(ds.get("PatientSex")) if hasattr(ds, "PatientSex") else None,
            dob=str(ds.get("PatientBirthDate")) if hasattr(ds, "PatientBirthDate") else None,
            ethnic_group=str(ds.get("EthnicGroup")) if hasattr(ds, "EthnicGroup") else None,
        )
        self.session.add(new_phi)
        return new_phi

    def _get_or_create_study(self, ds: Dataset, parent_phi: PHI, date_delta: int, source_name: str) -> Study:
        study_uid = str(ds.StudyInstanceUID)  # PK of Study
        study: Study | None = self.session.get(Study, study_uid)

        if study:
            logger.debug(f"Found existing Study record for PK '{study_uid}'.")
            if study.patient_id == parent_phi.patient_id:
                return study
            else:
                # If the study exists but is linked to a different patient_id, raise an error
                msg = (
                    f"IntegrityError: StudyUID '{study_uid}' exists but is linked to "
                    f"PHI.patient_id '{study.patient_id}', while current DICOM "
                    f"implies PHI.patient_id '{parent_phi.patient_id}'."
                )
                logger.error(msg)
                raise ValueError(msg)  # Let get_session handle rollback

        logger.info(f"Study record for PK '{study_uid}' not found. Creating new study...")

        # Process AccessionNumber:
        phi_acc_no: str | None = str(ds.AccessionNumber).strip() if hasattr(ds, "AccessionNumber") else None

        # If phi dataset does not have an AccessionNumber or it is "" set anon_accession_number to None else use hash:
        anon_acc_no = None if phi_acc_no is None or phi_acc_no == "" else self._hash_accession_number(phi_acc_no)

        logger.debug(f"Creating new Study record with phi_acc_no:{phi_acc_no} and anon_acc_no:{anon_acc_no}")
        new_study: Study = Study(
            study_uid=study_uid,
            anon_study_uid=self._create_anon_uid(study_uid),  # Generate a new anonymized StudyUID
            patient_id=parent_phi.patient_id,  # Set the FK to PHI's PK
            source=source_name,
            study_date=str(ds.get("StudyDate", self.DEFAULT_PHI_STUDY_DATE)),  # Default to 19000101 if not present
            anon_date_delta=date_delta,
            accession_number=phi_acc_no,
            anon_accession_number=anon_acc_no,
            description=str(ds.get("StudyDescription")) if hasattr(ds, "StudyDescription") else None,
        )
        self.session.add(new_study)
        return new_study

    def _get_or_create_series(self, ds: Dataset, parent_study_record: Study) -> Series:
        series_uid: str = str(ds.SeriesInstanceUID)  # PK of Series
        series: Series | None = self.session.get(Series, series_uid)

        if series:
            logger.debug(f"Found existing Series record for PK '{series_uid}'.")
            # Integrity Check: StudyUID mismatch with existing Series
            if series.study_uid == parent_study_record.study_uid:
                return series
            else:
                msg = (
                    f"IntegrityError: SeriesUID '{series_uid}' exists but is linked to "
                    f"Study.study_uid '{series.study_uid}', while current DICOM "
                    f"implies Study.study_uid '{parent_study_record.study_uid}'."
                )
                logger.error(msg)
                raise ValueError(msg)

        logger.info(f"Series record for PK '{series_uid}' not found. Creating new Series...")
        new_series: Series = Series(
            series_uid=series_uid,
            anon_series_uid=self._create_anon_uid(series_uid),  # Generate a new anonymized SeriesUID
            study_uid=parent_study_record.study_uid,  # Set the FK to Study's PK
            modality=str(ds.get("Modality")) if hasattr(ds, "Modality") else None,
            description=str(ds.get("SeriesDescription")) if hasattr(ds, "SeriesDescription") else None,
        )
        self.session.add(new_series)
        return new_series

    def _get_or_create_instance(self, ds: Dataset, parent_series_record: Series) -> Instance:
        sop_instance_uid = str(ds.SOPInstanceUID)
        instance: Instance | None = self.session.get(Instance, sop_instance_uid)

        if instance:
            logger.debug(f"Found existing Instance record for PK '{sop_instance_uid}'.")
            # An instance should never move between series.
            if instance.series_uid != parent_series_record.series_uid:
                msg = (
                    f"IntegrityError: SOPInstanceUID '{sop_instance_uid}' exists but is linked to "
                    f"SeriesUID '{instance.series_uid}', while current DICOM implies "
                    f"SeriesUID '{parent_series_record.series_uid}'."
                )
                logger.error(msg)
                raise ValueError(msg)
            else:
                return instance

        logger.debug(f"Instance record for PK '{sop_instance_uid}' not found. Creating new Instance...")

        new_instance: Instance = Instance(
            sop_instance_uid=sop_instance_uid,
            anon_sop_instance_uid=self._create_anon_uid(sop_instance_uid),  # Generate a new anonymized SOPInstanceUID
            series_uid=parent_series_record.series_uid,
        )

        self.session.add(new_instance)
        return new_instance

    @use_session()
    def capture_phi(self, source: str, ds: Dataset, date_delta: int) -> tuple[str, str, str | None]:
        """
        Capture PHI (Protected Health Information) from a DICOM dataset

        Args:
            source (str): The source of the dataset.
            ds (Dataset): The dataset containing the PHI.
            date_delta (int): The anonymization date offset.

        Returns:
            tuple[str, str, int]: A tuple containing the PHI patient ID, anonymized patient ID, and anonymized accession number.

        Raises:
            ValueError: If core DICOM UIDs are missing in dataset
        """
        # ds must have attributes: StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID
        primary_uids = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]
        if not all(hasattr(ds, uid) for uid in primary_uids):
            msg = f"Critical Error 1: Dataset missing primary UIDs: {primary_uids}"
            logger.error(msg)
            raise ValueError(msg)

        phi = self._get_or_create_phi(ds)
        study = self._get_or_create_study(ds, phi, date_delta, source)
        series = self._get_or_create_series(ds, study)
        self._get_or_create_instance(ds, series)

        return phi.patient_id, phi.anon_patient_id, study.anon_accession_number

    @use_session()
    def remove_phi(self, anon_pt_id: str, anon_study_uid: str) -> bool:
        """
        Removes a Study and its children (Series, Instances) from the database,
        and returns the list of associated anonymized filenames for disk cleanup.

        If the Study was the last one for a Patient (PHI), the PHI record is also removed.
        All corresponding UID mappings in the generic UID_map are cleaned up.

        Args:
            session (Session): The active SQLAlchemy session (injected by decorator).
            anon_pt_id (str): The anonymized patient ID.
            anon_study_uid (str): The anonymized study UID.

        Returns:
            bool: True if the operation was successful, False if not found.
        """
        logger.info(f"remove_phi called for anon_pt_id={anon_pt_id}, anon_study_uid={anon_study_uid}")

        # 1. Find the original Study UID from the provided anonymized one
        phi_study_uid = self.session.execute(
            select(UID.phi_uid).where(UID.anon_uid == anon_study_uid)
        ).scalar_one_or_none()

        if not phi_study_uid:
            logger.error(f"Anon StudyUID='{anon_study_uid}' not found in UID map.")
            return False

        # 2. Fetch the Study to be deleted and its full object tree (PHI, Series, Instances)
        stmt = (
            select(Study)
            .where(Study.study_uid == phi_study_uid)
            .options(
                joinedload(Study.patient),  # Use joinedload for the to-one parent (efficient)
                selectinload(Study.series).selectinload(Series.instances),  # Eager load the full to-many tree
            )
        )
        study_to_delete = self.session.execute(stmt).scalar_one_or_none()

        if not study_to_delete:
            logger.error(f"Study with original UID='{phi_study_uid}' (from anon UID '{anon_study_uid}') not found.")
            return False

        # 3. Perform integrity check: Does this study belong to the expected anonymized patient?
        parent_phi = study_to_delete.patient  # Access the eagerly loaded parent PHI
        if not parent_phi or parent_phi.anon_patient_id != anon_pt_id:
            logger.error(f"Integrity error: Study '{phi_study_uid}' does not belong to anon_pt_id '{anon_pt_id}'.")
            return False

        # 4. Delete the Study or the parent PHI.
        #    SQLAlchemy's cascade="all, delete-orphan" will handle deleting all children
        #    (Study -> Series -> Instances).
        if parent_phi.studies and len(parent_phi.studies) == 1:
            # This is the last study. Deleting the PHI will cascade delete everything.
            logger.info(f"Deleteing last study for PHI '{parent_phi.patient_id}'. Removing PHI record.")
            self.session.delete(parent_phi)
        else:
            # Not the last study, just delete this one.
            logger.info(f"Removing Study '{study_to_delete.study_uid}'.")
            self.session.delete(study_to_delete)

        return True

    @use_session()  # The decorator manages the session and a single transaction for the whole batch
    def process_java_phi_studies(self, java_studies: list[JavaAnonymizerExportedStudy]):
        """
        Process a list of JavaAnonymizerExportedStudy objects and persist them
        using the SQLAlchemy ORM. The entire operation is one database transaction.

        Args:
            session (Session): The active SQLAlchemy session (injected by the decorator).
            java_studies (List[JavaAnonymizerExportedStudy]): List of studies to process.
        """
        logger.info(f"Processing {len(java_studies)} Java PHI Studies within a single transaction.")

        for java_study in java_studies:
            # --- Step 1: Get or Create the PHI Record ---
            get_phi_stmt = select(PHI).where(PHI.anon_patient_id == java_study.ANON_PatientID)
            phi_record = self.session.execute(get_phi_stmt).scalar_one_or_none()

            if not phi_record:
                # If the PHI record doesn't exist, create it.
                logger.debug(f"Creating new PHI for anon_patient_id '{java_study.ANON_PatientID}'.")
                phi_record = PHI(
                    patient_id=java_study.PHI_PatientID,
                    anon_patient_id=java_study.ANON_PatientID,
                    patient_name=java_study.PHI_PatientName,
                    # Other PHI fields like sex, dob, etc., will use their defaults (None).
                )
                self.session.add(phi_record)
            else:
                logger.debug(f"Found existing PHI for anon_patient_id '{java_study.ANON_PatientID}'.")

            # --- Step 2: Get or Create the Study Record ---
            # Find the Study by its original UID (its primary key)
            study_record = self.session.get(Study, java_study.PHI_StudyInstanceUID)

            if not study_record:
                # Study doesn't exist, so create it and link it to the PHI record
                logger.debug(f"Creating new Study for study_uid '{java_study.PHI_StudyInstanceUID}'.")

                study_record = Study(
                    study_uid=java_study.PHI_StudyInstanceUID,
                    anon_study_uid=java_study.ANON_StudyInstanceUID,
                    patient_id=phi_record.patient_id,
                    anon_accession_number=java_study.ANON_Accession,
                    accession_number=java_study.PHI_Accession,
                    study_date=java_study.PHI_StudyDate,
                    anon_date_delta=int(java_study.DateOffset),
                    description="Imported from Java Index",
                    source="Java Index File",
                )
                if phi_record.studies is None:
                    phi_record.studies = []
                phi_record.studies.append(study_record)
                self.session.add(study_record)
            else:
                logger.debug(f"Study '{java_study.PHI_StudyInstanceUID}' already exists. Verifying integrity.")
                # Integrity check: If the study exists, does it belong to the correct patient?
                if study_record.patient_id != phi_record.patient_id:
                    raise ValueError(
                        f"Study {study_record.study_uid} exists but belongs to a different patient "
                        f"({study_record.patient_id}) than implied by the import "
                        f"({phi_record.patient_id})."
                    )

        logger.info("Finished processing Java PHI studies. Committing transaction.")
