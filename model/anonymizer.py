from typing import Dict, List
from pathlib import Path
import logging
import threading
from dataclasses import dataclass, field
from pprint import pformat
import xml.etree.ElementTree as ET
from .project import DICOMNode
from utils.translate import _

logger = logging.getLogger(__name__)


class ThreadSafeDict:
    def __init__(self):
        self._dict = {}
        self._lock = threading.Lock()

    def __getitem__(self, key):
        with self._lock:
            return self._dict[key]

    def __setitem__(self, key, value):
        with self._lock:
            self._dict[key] = value

    def __delitem__(self, key):
        with self._lock:
            del self._dict[key]

    def __contains__(self, key):
        with self._lock:
            return key in self._dict

    def __len__(self):
        with self._lock:
            return len(self._dict)

    def items(self):
        with self._lock:
            return list(self._dict.items())

    def keys(self):
        with self._lock:
            return list(self._dict.keys())

    def clear(self):
        with self._lock:
            self._dict.clear()


class ThreadSafeSet:
    def __init__(self):
        self._set = set()
        self._lock = threading.Lock()

    def add(self, item):
        with self._lock:
            self._set.add(item)

    def remove(self, item):
        with self._lock:
            self._set.remove(item)

    def __contains__(self, item):
        with self._lock:
            return item in self._set

    def __len__(self):
        with self._lock:
            return len(self._set)


@dataclass
class Series:
    series_uid: str
    series_desc: str
    modality: str
    instances: int


@dataclass
class Study:
    study_date: str
    anon_date_delta: int
    accession_number: str
    study_uid: str
    study_desc: str
    source: DICOMNode | str
    series: List[Series]


@dataclass
class PHI:
    patient_name: str = ""
    patient_id: str = ""
    sex: str = "U"
    dob: str | None = None
    ethnic_group: str | None = None
    # TODO: move phi below to Study, even sex could change
    weight: str | None = None
    bmi: str | None = None
    size: str | None = None
    smoker: str | None = None
    medical_alerts: str | None = None
    allergies: str | None = None
    reason_for_visit: str | None = None
    admitting_diagnoses: str | None = None
    history: str | None = None
    additional_history: str | None = None
    comments: str | None = None
    studies: List[Study] = field(default_factory=list)


class AnonymizerModel:
    # Model Version Control
    MODEL_VERSION = 1
    # When PHI PatientID is missing allocate to Anonymized PatientID: 000000
    DEFAULT_ANON_PATIENT_ID_SUFFIX = "-000000"

    _lock = threading.Lock()

    def __init__(self, site_id: str, script_path: Path):
        self._version = AnonymizerModel.MODEL_VERSION
        self.default_anon_pt_id: str = site_id + self.DEFAULT_ANON_PATIENT_ID_SUFFIX

        # Dynamic attributes:
        self._patient_id_lookup = {}
        self._uid_lookup = {}
        self._acc_no_lookup = {}
        self._phi_lookup = {}
        self._study_imported = set()
        self.clear_lookups()
        self._script_path = script_path
        self._tag_keep = {}  # DICOM Tag: Operation
        self.load_script(script_path)

    def get_class_name(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        filtered_dict = {
            key: len(value) if isinstance(value, dict) or isinstance(value, set) else value
            for key, value in (self.__dict__.items())
        }
        return f"{self.get_class_name()}\n({pformat(filtered_dict)})"

    def load_script(self, script_path: Path):
        # Parse the anonymize script and create a dict of tags to keep: self._tag_keep["tag"] = "operation"
        # The anonymization function indicated by the script operation will be used to transform source dataset
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
        with self._lock:
            self._patient_id_lookup.clear()
            self._patient_id_lookup[""] = self.default_anon_pt_id  # Default Anonymized PatientID
            self._uid_lookup.clear()
            self._acc_no_lookup.clear()
            self._phi_lookup.clear()
            self._phi_lookup[self.default_anon_pt_id] = PHI()  # Default PHI for Anonymized PatientID
            self._study_imported.clear()

    def get_phi(self, anon_patient_id: str) -> PHI | None:
        with self._lock:
            if anon_patient_id not in self._phi_lookup:
                return None
            return self._phi_lookup[anon_patient_id]

    def get_phi_name(self, anon_pt_id: str) -> str | None:
        with self._lock:
            if anon_pt_id not in self._phi_lookup:
                return None
            return self._phi_lookup[anon_pt_id].patient_name

    def set_phi(self, anon_patient_id: str, phi: PHI):
        with self._lock:
            self._phi_lookup[anon_patient_id] = phi

    def get_study_imported(self, study_uid: str) -> bool:
        return study_uid in self._study_imported

    def set_study_imported(self, study_uid: str):
        self._study_imported.add(study_uid)

    def get_anon_patient_id(self, phi_patient_id: str) -> str | None:
        with self._lock:
            if phi_patient_id not in self._patient_id_lookup:
                return None
            return self._patient_id_lookup[phi_patient_id]

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
        with self._lock:
            if phi_uid not in self._uid_lookup:
                return None
            return self._uid_lookup[phi_uid]

    def get_uid_count(self) -> int:
        return len(self._uid_lookup)

    def set_anon_uid(self, phi_uid: str, anon_uid: str):
        with self._lock:
            self._uid_lookup[phi_uid] = anon_uid

    def get_anon_acc_no(self, phi_acc_no: str) -> str | None:
        with self._lock:
            if phi_acc_no not in self._acc_no_lookup:
                return None
            return self._acc_no_lookup[phi_acc_no]

    def set_anon_acc_no(self, phi_acc_no: str, anon_acc_no: str):
        with self._lock:
            self._acc_no_lookup[phi_acc_no] = anon_acc_no

    def get_acc_no_count(self) -> int:
        return len(self._acc_no_lookup)
