from typing import Dict, Tuple, List
from pathlib import Path
import logging
from pprint import pformat
import xml.etree.ElementTree as ET
from .project import PHI
from utils.translate import _

logger = logging.getLogger(__name__)

ANONYMIZER_MODEL_VERSION = 1


class AnonymizerModel:
    PICKLE_FILENAME = "AnonymizerModel.pkl"

    def __init__(self, script_path: Path):
        self._version = ANONYMIZER_MODEL_VERSION
        # Dynamic attributes:
        self._patient_id_lookup: Dict[str, str] = {}
        self._uid_lookup: Dict[str, str] = {}
        self._acc_no_lookup: Dict[str, str] = {}
        self._phi_lookup: Dict[str, PHI] = {}
        self._script_path = script_path
        self._tag_keep: Dict[str, str] = {}  # DICOM Tag: Operation
        self.load_script(script_path)
        self.dummy: str = "dummyA"

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        # Exclude the '_tag_keep' attribute from the dictionary
        filtered_dict = {
            key: len(value) if isinstance(value, dict) else value
            for key, value in (self.__dict__.items())
            # if key != "_tag_keep"
        }
        return f"{class_name}\n({pformat(filtered_dict)})"

    def load_script(self, script_path: Path):
        # Parse the anonymize script and create a dict of tags to keep: self._tag_keep["tag"] = "operation"
        # The anonymization function indicated by the script operation will be used to transform source dataset
        # Open and parse the XML script file
        try:
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
        self._patient_id_lookup.clear()
        self._uid_lookup.clear()
        self._acc_no_lookup.clear()
        self._phi_lookup.clear()

    def get_phi(self, anon_patient_id: str) -> PHI | None:
        if anon_patient_id not in self._phi_lookup:
            return None
        return self._phi_lookup[anon_patient_id]

    def get_phi_name(self, anon_pt_id: str) -> str | None:
        if anon_pt_id not in self._phi_lookup:
            return None
        return self._phi_lookup[anon_pt_id].patient_name

    def set_phi(self, anon_patient_id: str, phi: PHI):
        self._phi_lookup[anon_patient_id] = phi

    def get_anon_patient_id(self, phi_patient_id: str) -> str | None:
        if phi_patient_id not in self._patient_id_lookup:
            return None
        return self._patient_id_lookup[phi_patient_id]

    def get_patient_id_count(self) -> int:
        return len(self._patient_id_lookup)

    def set_anon_patient_id(self, phi_patient_id: str, anon_patient_id: str):
        self._patient_id_lookup[phi_patient_id] = anon_patient_id

    def uid_received(self, phi_uid: str) -> bool:
        return phi_uid in self._uid_lookup

    def remove_uid(self, phi_uid: str):
        if phi_uid in self._uid_lookup:
            del self._uid_lookup[phi_uid]

    def get_anon_uid(self, phi_uid: str) -> str | None:
        if phi_uid not in self._uid_lookup:
            return None
        return self._uid_lookup[phi_uid]

    def get_uid_count(self) -> int:
        return len(self._uid_lookup)

    def set_anon_uid(self, phi_uid: str, anon_uid: str):
        self._uid_lookup[phi_uid] = anon_uid

    def get_anon_acc_no(self, phi_acc_no: str) -> str | None:
        if phi_acc_no not in self._acc_no_lookup:
            return None
        return self._acc_no_lookup[phi_acc_no]

    def get_acc_no_count(self) -> int:
        return len(self._acc_no_lookup)

    def set_anon_acc_no(self, phi_acc_no: str, anon_acc_no: str):
        self._acc_no_lookup[phi_acc_no] = anon_acc_no
