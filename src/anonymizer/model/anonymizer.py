"""
This module contains the AnonymizerModel class, which is responsible for storing PHI (Protected Health Information)
and anonymization lookups. It also includes data classes for Series, Study, and PHI, as well as a Totals namedtuple.
"""

import logging
import pickle
import shutil
import threading
import xml.etree.ElementTree as ET
from collections import OrderedDict, namedtuple
from dataclasses import dataclass, field, fields
from pathlib import Path
from pprint import pformat
from typing import ClassVar, Dict, List, Tuple

from bidict import OrderedBidict
from pydicom import Dataset

from anonymizer.model.project import DICOMNode
from anonymizer.utils.storage import JavaAnonymizerExportedStudy

logger = logging.getLogger(__name__)


@dataclass
class Series:
    series_uid: str
    series_desc: str
    modality: str
    instance_count: int


@dataclass
class Study:
    source: DICOMNode | str
    study_uid: str
    study_date: str
    anon_date_delta: int
    accession_number: str
    study_desc: str
    series: List[Series]  # TODO: make dictionary with key = series_uid
    target_instance_count: int = 0
    # TODO: if data curation needs expand:
    # weight: str | None = None
    # bmi: str | None = None
    # size: str | None = None
    # smoker: str | None = None
    # medical_alerts: str | None = None
    # allergies: str | None = None
    # reason_for_visit: str | None = None
    # admitting_diagnoses: str | None = None
    # history: str | None = None
    # additional_history: str | None = None
    # comments: str | None = None


@dataclass
class PHI:
    patient_name: str = ""
    patient_id: str = ""
    sex: str | None = None
    dob: str | None = None
    ethnic_group: str | None = None
    studies: List[Study] = field(default_factory=list)  # TODO: make dictionary with key = study_uid


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


Totals = namedtuple("Totals", ["patients", "studies", "series", "instances", "quarantined"])


class AnonymizerModel:
    """
    The Anonymizer data model class to store PHI (Protected Health Information) and anonymization lookups.
    """

    # Model Version Control
    MODEL_VERSION = 2
    MAX_PATIENTS = 1000000  # 1 million patients

    _lock = threading.Lock()

    def __init__(self, site_id: str, uid_root: str, script_path: Path):
        """
        Initializes an instance of the AnonymizerModel class.

        Args:
            site_id (str): The site ID.
            uid_root (str): The UID root.
            script_path (Path): The path to the script.

        Attributes:
            _version (int): The model version.
            _site_id (str): The site ID.
            _uid_root (str): The UID root.
            _uid_prefix (str): The UID prefix.
            default_anon_pt_id (str): The default anonymized patient ID.
            _patient_id_lookup (dict): A dictionary to store patient ID lookups.
            _uid_lookup (dict): A dictionary to store UID lookups.
            _acc_no_lookup (dict): A dictionary to store accession number lookups.
            _phi_lookup (dict): A dictionary to store PHI lookups.
            _script_path (Path): The path to the script.
            _tag_keep (dict): A dictionary to store DICOM tag operations.
            _patients (int): The number of patients.
            _studies (int): The number of studies.
            _series (int): The number of series.
            _instances (int): The number of instances.
            _quarantined (int): The number of instances quarantined. [V2]
        """
        self._version = AnonymizerModel.MODEL_VERSION
        self._site_id = site_id
        self._uid_root = uid_root
        self._script_path = script_path

        self._uid_prefix = f"{self._uid_root}.{self._site_id}"
        self.default_anon_pt_id: str = site_id + "-" + "".zfill(len(str(self.MAX_PATIENTS)) - 1)

        # Initialise Lookup Tables:
        self._patient_id_lookup: OrderedDict[str, str] = OrderedDict()
        self._uid_lookup: OrderedBidict[str, str] = OrderedBidict()
        self._acc_no_lookup: OrderedDict[str, str] = OrderedDict()
        self._phi_lookup: Dict[str, PHI] = {}
        self._tag_keep: Dict[str, str] = {}  # {dicom tag : anonymizer operation}

        self._patients = 0
        self._studies = 0
        self._series = 0
        self._instances = 0
        self._quarantined = 0  # [V2]

        self.clear_lookups()  # initialises default patient_id_lookup and phi_lookup
        self.load_script(script_path)

    def save(self, filepath: Path) -> bool:
        with self._lock:
            try:
                serialized_data = pickle.dumps(self, protocol=pickle.HIGHEST_PROTOCOL)
                with open(filepath, "wb") as pkl_file:
                    pkl_file.write(serialized_data)
                shutil.copy2(
                    filepath, filepath.with_suffix(filepath.suffix + ".bak")
                )  # backup <filepath>.pkl to <filepath>.pkl.bak
                logger.debug(f"Anonymizer Model saved to: {filepath}")
                return True
            except Exception as e:
                logger.error(f"Fatal Error saving AnonymizerModel, error: {e}")
                return False

    def get_class_name(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        filtered_dict = {
            key: len(value) if isinstance(value, (OrderedDict, OrderedBidict, Dict, set)) else value
            for key, value in (self.__dict__.items())
        }
        return f"{self.get_class_name()}\n({pformat(filtered_dict)})"

    def load_script(self, script_path: Path):
        """
        Load and parse an anonymize script file.

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

            # Handle:
            # <r en="T" t="curves">Remove curves</r>
            # <r en="T" t="overlays">Remove overlays</r>
            # <r en="T" t="privategroups">Remove private groups</r> # pydicom.remove_private_tags()
            # <r en="F" t="unspecifiedelements">Remove unchecked elements</r> # ignore check/unchecked en="T/F"

            filtered_tag_keep = {k: v for k, v in self._tag_keep.items() if v != ""}
            logger.info(f"_tag_keep has {len(self._tag_keep)} entries with {len(filtered_tag_keep)} operations")
            logger.info(f"_tag_keep operations:\n{pformat(filtered_tag_keep)}")
            return

        except FileNotFoundError:
            logger.error(f"{script_path} not found")
            raise

        except ET.ParseError:
            logger.error(f"Error parsing the script file {script_path}. Ensure it is valid XML.")
            raise

        except Exception as e:
            # Catch other generic exceptions and print the error message
            logger.error(f"Error Parsing script file {script_path}: {str(e)}")
            raise

    def clear_lookups(self):
        """
        Clears all the lookup dictionaries used for anonymization.
        """
        with self._lock:
            self._patient_id_lookup.clear()
            self._patient_id_lookup[""] = self.default_anon_pt_id  # Default Anonymized PatientID
            self._uid_lookup.clear()
            self._acc_no_lookup.clear()
            self._phi_lookup.clear()
            self._phi_lookup[self.default_anon_pt_id] = PHI()  # Default PHI for Anonymized PatientID

    def get_totals(self) -> Totals:
        return Totals(
            self._patients,
            self._studies,
            self._series,
            self._instances,
            self._quarantined,
        )

    def get_phi(self, anon_patient_id: str) -> PHI | None:
        with self._lock:
            return self._phi_lookup.get(anon_patient_id, None)

    def get_phi_name(self, anon_patient_id: str) -> str | None:
        with self._lock:
            phi = self._phi_lookup.get(anon_patient_id, None)
            if phi is None:
                return None
            else:
                return phi.patient_name

    def set_phi(self, anon_patient_id: str, phi: PHI):
        with self._lock:
            self._phi_lookup[anon_patient_id] = phi

    def increment_quarantined(self):
        self._quarantined += 1

    def get_anon_patient_id(self, phi_patient_id: str) -> str | None:
        return self._patient_id_lookup.get(phi_patient_id)

    # def get_next_anon_patient_id(self, phi_patient_id: str) -> str:
    #     with self._lock:
    #         anon_patient_id = (
    #             f"{self._site_id}-{str(len(self._patient_id_lookup)).zfill(len(str(self.MAX_PATIENTS - 1)))}"
    #         )
    #         self._patient_id_lookup[phi_patient_id] = anon_patient_id
    #         return anon_patient_id

    def get_patient_id_count(self) -> int:
        return len(self._patient_id_lookup)

    def set_anon_patient_id(self, phi_patient_id: str, anon_patient_id: str):
        with self._lock:
            self._patient_id_lookup[phi_patient_id] = anon_patient_id

    def uid_received(self, phi_uid: str) -> bool:
        return phi_uid in self._uid_lookup

    def remove_uid(self, phi_uid: str):
        with self._lock:
            if phi_uid in self._uid_lookup:
                del self._uid_lookup[phi_uid]

    def remove_uid_inverse(self, anon_uid: str):
        with self._lock:
            if anon_uid in self._uid_lookup.inverse:
                del self._uid_lookup.inverse[anon_uid]

    def get_anon_uid(self, phi_uid: str) -> str | None:
        return self._uid_lookup.get(phi_uid, None)

    def set_anon_uid(self, phi_uid: str, anon_uid: str):
        with self._lock:
            self._uid_lookup[phi_uid] = anon_uid

    def get_next_uid_ndx(self) -> int:
        if len(self._uid_lookup) == 0:
            return 1
        # Get last entered value in _uid_lookup:
        last_value: str = ""
        for key in self._uid_lookup.__reversed__():
            last_value = self._uid_lookup[key]
            break
        # Extract last digit and increment:
        ndx = int(last_value.split(".")[-1]) + 1
        return ndx

    def get_next_anon_uid(self, phi_uid: str) -> str:
        with self._lock:
            anon_uid = self._uid_prefix + f".{self.get_next_uid_ndx()}"
            self._uid_lookup[phi_uid] = anon_uid
            return anon_uid

    def get_anon_acc_no(self, phi_acc_no: str) -> str | None:
        return self._acc_no_lookup.get(phi_acc_no)

    def set_anon_acc_no(self, phi_acc_no: str, anon_acc_no: str):
        with self._lock:
            self._acc_no_lookup[phi_acc_no] = anon_acc_no

    def get_next_anon_acc_no(self, phi_acc_no: str) -> str:
        # TODO: include PHI PatientID with phi_acc_no for uniqueness
        with self._lock:
            last_value: str = ""
            if len(self._acc_no_lookup) == 0:
                anon_acc_no = "1"
            else:
                # Get last entered value in _acc_no_lookup:
                for key in self._acc_no_lookup.__reversed__():
                    last_value = self._acc_no_lookup[key]
                    break
                anon_acc_no = str(int(last_value) + 1)
            self._acc_no_lookup[phi_acc_no] = anon_acc_no
            return anon_acc_no

    def get_acc_no_count(self) -> int:
        return len(self._acc_no_lookup)

    def get_stored_instance_count(self, ptid: str, study_uid: str) -> int:
        """
        Retrieves the number of stored instances for a given patient ID and study UID.

        Args:
            ptid (str): PHI PatientID.
            study_uid (str): PHI StudyUID.

        Returns:
            int: The number of stored instances.

        """
        with self._lock:
            anon_patient_id = self._patient_id_lookup.get(ptid, None)
            if anon_patient_id is None:
                return 0
            phi = self._phi_lookup.get(anon_patient_id, None)
            if phi is None:
                return 0
            for study in phi.studies:
                if study.study_uid == study_uid:
                    return sum(series.instance_count for series in study.series)
            return 0

    def get_pending_instance_count(self, ptid: str, study_uid: str, target_count: int) -> int:
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
        anon_patient_id = self._patient_id_lookup.get(ptid, None)
        if anon_patient_id is None:
            return target_count
        phi = self._phi_lookup.get(anon_patient_id, None)
        if phi is None:
            return target_count
        for study in phi.studies:
            if study.study_uid == study_uid:
                with self._lock:
                    study.target_instance_count = target_count
                    return target_count - sum(series.instance_count for series in study.series)
        return target_count

    def series_complete(self, ptid: str, study_uid: str, series_uid: str, target_count: int) -> bool:
        """
        Check if a series is complete based on the given parameters.

        Args:
            ptid (str): The patient ID.
            study_uid (str): The study UID.
            series_uid (str): The series UID.
            target_count (int): The target instance count.

        Returns:
            bool: True if the series is complete, False otherwise.
        """
        anon_patient_id = self._patient_id_lookup.get(ptid, None)
        if anon_patient_id is None:
            return False
        phi = self._phi_lookup.get(anon_patient_id, None)
        if phi is None:
            return False
        for study in phi.studies:
            if study.study_uid == study_uid:
                for series in study.series:
                    if series.series_uid == series_uid:
                        return series.instance_count >= target_count
                return False
        return False

    def get_phi_index(self) -> List[PHI_IndexRecord] | None:
        if self.get_patient_id_count() == 0:
            return None

        phi_index = []
        for anon_pt_id in self._phi_lookup:
            phi: PHI = self._phi_lookup[anon_pt_id]
            for study in phi.studies:
                phi_index_record = PHI_IndexRecord(
                    anon_patient_id=anon_pt_id,
                    anon_patient_name=anon_pt_id,
                    phi_patient_id=phi.patient_id,
                    phi_patient_name=phi.patient_name,
                    date_offset=study.anon_date_delta,
                    phi_study_date=study.study_date,
                    # TODO: Handle missing accession numbers
                    anon_accession=self._acc_no_lookup.get(study.accession_number, "?"),
                    phi_accession=study.accession_number,
                    anon_study_uid=self._uid_lookup[study.study_uid],
                    phi_study_uid=study.study_uid,
                    num_series=len(study.series),
                    num_instances=sum([s.instance_count for s in study.series]),
                )
                phi_index.append(phi_index_record)
        return phi_index

    # Used by QueryRetrieveView to prevent study re-import
    def study_imported(self, ptid: str, study_uid: str) -> bool:
        with self._lock:
            anon_patient_id = self._patient_id_lookup.get(ptid, None)
            if anon_patient_id is None:
                return False
            phi = self._phi_lookup.get(anon_patient_id, None)
            if phi is None:
                return False
            for study in phi.studies:
                if study.study_uid == study_uid:
                    if study.target_instance_count == 0:  # Not set by ProjectController import process yet
                        return False
                    return sum(series.instance_count for series in study.series) >= study.target_instance_count
            return False

    # Helper function for capture_phi
    def new_study_from_dataset(self, ds: Dataset, source: DICOMNode | str, date_delta: int) -> Study:
        return Study(
            study_uid=ds.get("StudyInstanceUID"),
            study_date=ds.get("StudyDate"),
            anon_date_delta=date_delta,
            accession_number=ds.get("AccessionNumber"),
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

    def next_ptid(self, last_ptid: str) -> str:
        """Increments the numeric part of a key with format xxxxxx-nnnnnn.

        Args:
            key: The key to increment.

        Returns:
            The incremented key.
        """
        prefix, numeric_part = last_ptid.split("-")
        numeric_part = str(int(numeric_part) + 1).zfill(6)  # Increment and pad with zeros
        return f"{prefix}-{numeric_part}"

    def capture_phi(self, source: str, ds: Dataset, date_delta: int) -> None:
        """
        Capture PHI (Protected Health Information) from a dataset,
        Update the UID & PHI lookups and the dataset statistics (patients,studies,series,instances)

        Args:
            source (str): The source of the dataset.
            ds (Dataset): The dataset containing the PHI.
            date_delta (int): The time difference in days.

        Raises following Critical Errors:
            1. ValueError:  If any of StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID are not present in dataset
            2. LookupError: If the PHI PatientID is not found in the patient_id_lookup or phi_lookup.
            3. LookupError: If the existing patient with Anon PatientID is not found in phi_lookup.
            4. LookupError: If the existing study is not found in phi_lookup.
            5. LookupError: If the existing series is not found in the study.

        Returns:
            None
        """
        with self._lock:
            # ds must have attributes: StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID
            req_uids = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]
            if not all(hasattr(ds, uid) for uid in req_uids):
                msg = f"Critical Error 1: Dataset missing primary UIDs: {req_uids}"
                logger.error(msg)
                raise ValueError(msg)

            # If PHI PatientID is missing in dataset, as per DICOM Standard, pydicom should return "", handle missing attribute
            # Missing or blank corresponds to AnonymizerModel.DEFAULT_ANON_PATIENT_ID ("000000") initialised in AnonymizerModel.clear_lookups()
            phi_ptid = ds.PatientID.strip() if hasattr(ds, "PatientID") else ""
            anon_patient_id: str | None = self._patient_id_lookup.get(phi_ptid, None)
            next_uid_ndx = self.get_next_uid_ndx()
            anon_study_uid = self._uid_lookup.get(ds.StudyInstanceUID)

            if anon_study_uid is None:
                # NEW Study:
                if anon_patient_id is None:
                    # NEW patient
                    # Get last patient_id in _patient_id_lookup
                    last_pt_id = ""
                    for key in self._patient_id_lookup.__reversed__():
                        last_pt_id = self._patient_id_lookup[key]
                        break
                    # Get next sequential patient_id for the new patient: (this method handles deletions from _patient_id_lookup without recycling ids)
                    new_anon_patient_id = self.next_ptid(last_pt_id)
                    phi = PHI(
                        patient_name=ds.get("PatientName"),
                        patient_id=phi_ptid,
                        sex=ds.get("PatientSex"),
                        dob=ds.get("PatientBirthDate"),
                        ethnic_group=ds.get("EthnicGroup"),
                        studies=[],
                    )
                    self._phi_lookup[new_anon_patient_id] = phi
                    self._patient_id_lookup[phi_ptid] = new_anon_patient_id
                    self._patients += 1

                else:  # Existing patient now with more than one study
                    phi: PHI | None = self._phi_lookup.get(anon_patient_id, None)

                    if phi is None:
                        msg = f"Critical Error 2: Existing patient, Anon PatientID={anon_patient_id} not found in phi_lookup"
                        logger.error(msg)
                        raise LookupError(msg)

                # ADD new study,series,instance to PHI:
                phi.studies.append(self.new_study_from_dataset(ds, source, date_delta))
                for uid in req_uids:
                    anon_uid = self._uid_prefix + f".{next_uid_ndx}"
                    self._uid_lookup[getattr(ds, uid)] = anon_uid
                    next_uid_ndx += 1

                self._studies += 1
                self._series += 1
                self._instances += 1

            else:
                # Existing Study
                # Assume Existing Patient and PHI already captured
                # If so, update series and instance counts from new instance:
                if anon_patient_id is None:
                    # TODO: Different PatientID for SAME Study detected:
                    # Look through PHI lookup for this study to determine which PatientID has already been associated with it
                    msg = f"Critical Error 3: Existing study Anon StudyUID={anon_study_uid}, incoming file has different PHI PatientID"
                    logger.critical(msg)
                    raise LookupError(msg)

                phi: PHI | None = self._phi_lookup.get(anon_patient_id, None)

                if phi is None:
                    msg = f"Critial Error 4: Existing Anon PatientID={anon_patient_id} not found in phi_lookup"
                    logger.critical(msg)
                    raise LookupError(msg)

                # Find study in PHI:
                if phi.studies is not None:
                    study = next(
                        (study for study in phi.studies if study.study_uid == ds.StudyInstanceUID),
                        None,
                    )
                else:
                    study = None

                if study is None:
                    msg = (
                        f"Critical Error 5: Existing study for Anon PatientID={anon_patient_id} not found in phi_lookup"
                    )
                    logger.error(msg)
                    raise LookupError(msg)

                # Find series in study:
                if study.series is not None:
                    series: Series | None = next(
                        (series for series in study.series if series.series_uid == ds.SeriesInstanceUID),
                        None,
                    )
                else:
                    series = None

                if series is None:
                    # NEW Series in exsiting Study:
                    study.series.append(
                        Series(
                            ds.get("SeriesInstanceUID"),
                            ds.get("SeriesDescription"),
                            ds.get("Modality"),
                            1,
                        )
                    )
                    for uid in req_uids[1:]:  # Skip StudyInstanceUID
                        anon_uid = self._uid_prefix + f".{next_uid_ndx}"
                        self._uid_lookup[getattr(ds, uid)] = anon_uid
                        next_uid_ndx += 1

                    self._series += 1

                else:
                    # NEW Instance in existing Series:
                    series.instance_count += 1
                    anon_uid = self._uid_prefix + f".{next_uid_ndx}"
                    self._uid_lookup[ds.SOPInstanceUID] = anon_uid

                self._instances += 1

    def remove_phi(self, anon_pt_id: str, anon_study_uid: str) -> bool:
        """
        Remove PHI data for a given Anonymized patient ID and study UID.

        If the patient does not have anymore studies after removing the study, the patient is removed from the both patient_id_lookup and phi_lookup.

        Args:
            anon_pt_id (str): The anonymized patient ID.
            anon_study_uid (str): The anonymized study UID.

        Returns:
            bool: True if the PHI data was removed successfully, False otherwise.
        """
        logger.info(f"remove_phi anon_pt_id={anon_pt_id}, anon_study_uid={anon_study_uid}")

        with self._lock:
            phi: PHI | None = self._phi_lookup.get(anon_pt_id, None)
            if phi is None:
                logger.error(f"Anon PatientID={anon_pt_id} not found in phi_lookup")
                return False
            phi_study_uid = self._uid_lookup.inverse.get(anon_study_uid, None)
            if phi_study_uid is None:
                logger.error(f"Anon StudyUID={anon_study_uid} not found in uid_lookup")
                return False
            if not phi.studies:
                logger.error(f"No studies in PHI.studies for Anon PatientID={anon_pt_id}")
                return False

            match = None
            for study in phi.studies:
                if study.study_uid == phi_study_uid:
                    match = study
                    break

            if match is None:
                logger.error(f"Anon StudyUID={anon_study_uid} not found in PHI.studies for Anon PatientID={anon_pt_id}")
                return False

            # Remove the accession number of the matched study from _acc_no_lookup:
            # To delete acc no, Need to ensure the phi acc_no is not in ANY other phi study (can't be assumed to be unique)
            # if match.accession_number in self._acc_no_lookup:
            #         del self._acc_no_lookup[match.accession_number]

            # Remove the series_uids of this study from the uid_lookup:
            # Note: instance uids are removed by controller via directory names
            # Note: uids generated for other uid fields as per script will not be removed from uid_lookup
            for series in match.series:
                if series.series_uid in self._uid_lookup:
                    del self._uid_lookup[series.series_uid]
                self._instances -= series.instance_count
                self._series -= 1

            # Remove the study_uid from the uid_lookup:
            if phi_study_uid in self._uid_lookup:
                del self._uid_lookup[phi_study_uid]

            # Remove the matched study from phi.studies list:
            phi.studies.remove(match)

            self._studies -= 1

            # Remove the patient if no more studies:
            if not phi.studies:
                del self._phi_lookup[anon_pt_id]
                del self._patient_id_lookup[phi.patient_id]
                self._patients -= 1

            return True

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
            self.set_anon_acc_no(java_study.PHI_Accession, java_study.ANON_Accession)
            self.set_anon_uid(java_study.PHI_StudyInstanceUID, java_study.ANON_StudyInstanceUID)

            new_study = Study(
                study_date=java_study.PHI_StudyDate,
                anon_date_delta=int(java_study.DateOffset),
                accession_number=java_study.PHI_Accession,
                study_uid=java_study.PHI_StudyInstanceUID,
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
