from ast import Set
import os
import logging
from pprint import pformat
from typing import Dict, Tuple, List
from dataclasses import dataclass, field
from pathlib import Path
from pynetdicom._globals import ALL_TRANSFER_SYNTAXES, DEFAULT_TRANSFER_SYNTAXES
from utils.translate import _

logger = logging.getLogger(__name__)


# Controller Custom Error classes:
class DICOMRuntimeError(Exception):
    pass


@dataclass
class DICOMNode:
    ip: str
    port: int
    aet: str
    local: bool


@dataclass
class Study:
    study_date: str
    accession_number: str
    study_uid: str
    source: DICOMNode | str


@dataclass
class PHI:
    patient_name: str
    patient_id: str
    studies: List[Study]


def default_project_filename() -> str:
    return "ProjectModel.pkl"


def default_storage_dir() -> Path:
    return Path(os.path.expanduser("~"), "ANONYMIZER_STORE")


def default_local_server() -> DICOMNode:
    return DICOMNode("127.0.0.1", 1045, _("ANONYMIZER"), True)


def default_remote_scps() -> Dict[str, DICOMNode]:
    return {
        "QUERY": DICOMNode("127.0.0.1", 104, "QUERYAE", False),
        "EXPORT": DICOMNode("127.0.0.1", 104, "EXPORTAE", False),
    }


def default_storage_classes() -> List[str]:
    return [
        "1.2.840.10008.5.1.4.1.1.1",  # "Computed Radiography Image Storage"
        "1.2.840.10008.5.1.4.1.1.1.1",  # "Digital X-Ray Image Storage - For Presentation"
        "1.2.840.10008.5.1.4.1.1.1.1.1",  # "Digital X-Ray Image Storage - For Processing"
        "1.2.840.10008.5.1.4.1.1.2",  # "Computed Tomography Image Storage"
        "1.2.840.10008.5.1.4.1.1.4",  # "Magnetic Resonance Image Storage"
    ]


def default_transfer_syntaxes() -> List[str]:
    return DEFAULT_TRANSFER_SYNTAXES  # change to ALL_TRANSFER_SYNTAXES to support compression


@dataclass
class ProjectModel:
    site_id: str = _("9999")
    project_name: str = _("PROJECT")
    trial_name: str = _("TRIAL")
    uid_root: str = "1.2.826.0.1.3680043.10.188"
    storage_dir: Path = field(default_factory=default_storage_dir)
    storage_classes: List[str] = field(default_factory=default_storage_classes)

    scu: DICOMNode = field(default_factory=default_local_server)
    scp: DICOMNode = field(default_factory=default_local_server)
    remote_scps: Dict[str, DICOMNode] = field(default_factory=default_remote_scps)
    network_timeout: int = 5  # seconds
    anonymizer_script_path: Path = Path("assets/scripts/default-anonymizer.script")

    # TODO: provide UX to manage the allowed storage classes and supported transfer syntaxes, *FIXED FOR MVP*
    _TRANSFER_SYNTAXES: List[str] = field(default_factory=default_transfer_syntaxes)

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}\n({pformat(self.__dict__)})"

    def abridged_storage_dir(self) -> str:
        return f".../{self.storage_dir.parts[-2]}/{self.storage_dir.parts[-1]}"
