from typing import List
from collections import namedtuple
from pathlib import Path
import logging
import threading
import pickle
from dataclasses import dataclass, field
from pprint import pformat
import xml.etree.ElementTree as ET
from pydicom import Dataset
from .project import DICOMNode
from utils.translate import _
from utils.storage import JavaAnonymizerExportedStudy

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
    series: List[Series]
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
    studies: List[Study] = field(default_factory=list)


Totals = namedtuple("Totals", ["patients", "studies", "series", "instances"])


class AnonymizerModel:
    """
    The Anonymizer data model class to store PHI (Protected Health Information) and anonymization lookups.
    """

    # Model Version Control
    MODEL_VERSION = 1
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
        """
        self._version = AnonymizerModel.MODEL_VERSION
        self._site_id = site_id
        self._uid_root = uid_root
        self._script_path = script_path

        self._uid_prefix = f"{self._uid_root}.{self._site_id}"
        self.default_anon_pt_id: str = site_id + "-" + "".zfill(len(str(self.MAX_PATIENTS)) - 1)

        self._patient_id_lookup = {}
        self._uid_lookup = {}
        self._acc_no_lookup = {}
        self._phi_lookup = {}
        self._tag_keep = {}

        self._patients = 0
        self._studies = 0
        self._series = 0
        self._instances = 0

        self.clear_lookups()  # initialises default patient_id_lookup and phi_lookup
        self.load_script(script_path)

    def save(self, filepath: Path) -> bool:
        with self._lock:
            try:
                with open(filepath, "wb") as pkl_file:
                    pickle.dump(self, pkl_file)
                logger.debug(f"Anonymizer Model saved to: {filepath}")
                return True
            except Exception as e:
                logger.error(f"Fatal Error saving AnonymizerModel, error: {e}")
                return False

    def get_class_name(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        filtered_dict = {
            key: len(value) if isinstance(value, dict) or isinstance(value, set) else value
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
        try:
            # Open and parse the XML script file
            root = ET.parse(script_path).getroot()

            # Extract 'e' tags into _tag_keep dictionary
            for e in root.findall("e"):
                tag = str(e.attrib.get("t"))
                operation = str(e.text) if e.text is not None else ""
                if "@remove" not in operation:
                    self._tag_keep[tag] = operation

            # Handle:
            # <k en="F" t="0018">Keep group 0018</k>
            # <k en="F" t="0020">Keep group 0020</k>
            # <k en="F" t="0028">Keep group 0028</k>
            # <r en="T" t="curves">Remove curves</r>
            # <r en="T" t="overlays">Remove overlays</r>
            # <r en="T" t="privategroups">Remove private groups</r>
            # <r en="F" t="unspecifiedelements">Remove unchecked elements</r>

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
        return Totals(self._patients, self._studies, self._series, self._instances)

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

    def get_anon_patient_id(self, phi_patient_id: str) -> str | None:
        return self._patient_id_lookup.get(phi_patient_id)

    def get_next_anon_patient_id(self, phi_patient_id: str) -> str:
        with self._lock:
            anon_patient_id = (
                f"{self._site_id}-{str(len(self._patient_id_lookup)).zfill(len(str(self.MAX_PATIENTS - 1)))}"
            )
            self._patient_id_lookup[phi_patient_id] = anon_patient_id
            return anon_patient_id

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

    def get_anon_uid(self, phi_uid: str) -> str | None:
        return self._uid_lookup.get(phi_uid, None)

    def get_uid_count(self) -> int:
        return len(self._uid_lookup)

    def set_anon_uid(self, phi_uid: str, anon_uid: str):
        with self._lock:
            self._uid_lookup[phi_uid] = anon_uid

    def get_next_anon_uid(self, phi_uid: str) -> str:
        with self._lock:
            anon_uid = self._uid_prefix + f".{self.get_uid_count() + 1}"
            self._uid_lookup[phi_uid] = anon_uid
            return anon_uid

    def get_anon_acc_no(self, phi_acc_no: str) -> str | None:
        return self._acc_no_lookup.get(phi_acc_no)

    def set_anon_acc_no(self, phi_acc_no: str, anon_acc_no: str):
        with self._lock:
            self._acc_no_lookup[phi_acc_no] = anon_acc_no

    def get_next_anon_acc_no(self, phi_acc_no: str) -> str:
        with self._lock:
            anon_acc_no = len(self._acc_no_lookup) + 1
            # TODO: include PHI PatientID with phi_acc_no for uniqueness
            self._acc_no_lookup[phi_acc_no] = str(anon_acc_no)
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

    def capture_phi(self, source: str, ds: Dataset, date_delta: int) -> None:
        """
        Capture PHI (Protected Health Information) from a dataset and update the PHI lookup.

        Args:
            source (str): The source of the dataset.
            ds (Dataset): The dataset containing the PHI.
            date_delta (int): The time difference in days.

        Raises:
            LookupError: If the PHI PatientID is not found in the patient_id_lookup or phi_lookup.
            LookupError: If the existing patient with Anon PatientID is not found in phi_lookup.
            LookupError: If the existing study is not found in phi_lookup.
            LookupError: If the existing series is not found in the study.

        Returns:
            None
        """
        with self._lock:
            # ds must have attributes: StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID
            req_uids = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]
            if not all(hasattr(ds, uid) for uid in req_uids):
                logger.critical(f"Critical Error dataset missing primary UIDs: {req_uids}")
                return
            # If PHI PatientID is missing in dataset, as per DICOM Standard, pydicom should return "", handle missing attribute
            # Missing or blank corresponds to AnonymizerModel.DEFAULT_ANON_PATIENT_ID ("000000") initialised in AnonymizerModel.clear_lookups()
            phi_ptid = ds.PatientID.strip() if hasattr(ds, "PatientID") else ""
            anon_patient_id = self._patient_id_lookup.get(phi_ptid, None)
            phi = self._phi_lookup.get(anon_patient_id, None)
            next_uid_ndx = self.get_uid_count() + 1

            if self._uid_lookup.get(ds.StudyInstanceUID) == None:
                # NEW Study:
                if anon_patient_id == None:
                    # NEW patient
                    new_anon_patient_id = (
                        f"{self._site_id}-{str(len(self._patient_id_lookup)).zfill(len(str(self.MAX_PATIENTS - 1)))}"
                    )
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
                    if phi == None:
                        msg = f"Existing patient, Anon PatientID={anon_patient_id} not found in phi_lookup"
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
                # Existing Study & Patient, PHI already captured, update series and instance counts from new instance:
                if anon_patient_id is None:
                    msg = f"Critical error PHI PatientID={phi_ptid} not found in patient_id_lookup"
                    logger.critical(msg)
                    raise LookupError(msg)

                if phi == None:
                    msg = f"Critial error Existing Anon PatientID={anon_patient_id} not found in phi_lookup"
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

                if study == None:
                    msg = f"Existing study {ds.StudyInstanceUID} not found in phi_lookup"
                    logger.error(msg)
                    raise LookupError(msg)

                # Find series in study:
                if study.series is not None:
                    series: Series = next(
                        (series for series in study.series if series.series_uid == ds.SeriesInstanceUID),
                        None,
                    )
                else:
                    series = None

                if series == None:
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
