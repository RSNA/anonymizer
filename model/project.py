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
        "QUERY": DICOMNode("127.0.0.1", 11112, "MDEDEV", False),
        "EXPORT": DICOMNode("127.0.0.1", 11112, "MDEDEV", False),
    }


def default_transfer_syntaxes() -> List[str]:
    return DEFAULT_TRANSFER_SYNTAXES  # change to ALL_TRANSFER_SYNTAXES to support compression


def default_radiology_storage_classes() -> Dict[str, str]:
    return {
        "Computed Radiography Image Storage": "1.2.840.10008.5.1.4.1.1.1",
        "Digital X-Ray Image Storage - For Presentation": "1.2.840.10008.5.1.4.1.1.1.1",
        "Digital X-Ray Image Storage - For Processing": "1.2.840.10008.5.1.4.1.1.1.1.1",
        "Computed Tomography Image Storage": "1.2.840.10008.5.1.4.1.1.2",
        # "Enhanced CT Image Storage": "1.2.840.10008.5.1.4.1.1.2.1",
        # "Digital Mammography X-Ray Image Storage For Presentation": "1.2.840.10008.5.1.4.1.1.1.2",
        # "Digital Mammography X-Ray Image Storage For Processing": "1.2.840.10008.5.1.4.1.1.1.2.1",
        # "Digital Intra Oral X-Ray Image Storage For Presentation": "1.2.840.10008.5.1.4.1.1.1.3",
        # "Digital Intra Oral X-Ray Image Storage For Processing": "1.2.840.10008.5.1.4.1.1.1.3.1",
        "Magnetic Resonance Image Storage": "1.2.840.10008.5.1.4.1.1.4",
        # "Enhanced MR Image Storage": "1.2.840.10008.5.1.4.1.1.4.1",
        # "Positron Emission Tomography Image Storage": "1.2.840.10008.5.1.4.1.1.128",
        # "Enhanced PET Image Storage": "1.2.840.10008.5.1.4.1.1.130",
        # "Ultrasound Image Storage": "1.2.840.10008.5.1.4.1.1.6.1",
        # "Mammography CAD SR Storage": "1.2.840.10008.5.1.4.1.1.88.50",
        # "BreastTomosynthesisImageStorage": "1.2.840.10008.5.1.4.1.1.13.1.3",
    }


@dataclass
class ProjectModel:
    site_id: str = _("9999")
    project_name: str = _("PROJECT")
    trial_name: str = _("TRIAL")
    uid_root: str = "1.2.826.0.1.3680043.10.188"
    storage_dir: Path = field(default_factory=default_storage_dir)
    scu: DICOMNode = field(default_factory=default_local_server)
    scp: DICOMNode = field(default_factory=default_local_server)
    remote_scps: Dict[str, DICOMNode] = field(default_factory=default_remote_scps)
    network_timeout: int = 3  # seconds
    anonymizer_script_path: Path = Path("assets/scripts/default-anonymizer.script")

    # TODO: provide UX to manage the allowed storage classes and supported transfer syntaxes, *FIXED FOR MVP*
    _TRANSFER_SYNTAXES: List[str] = field(default_factory=default_transfer_syntaxes)
    _RADIOLOGY_STORAGE_CLASSES: Dict[str, str] = field(
        default_factory=default_radiology_storage_classes
    )

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}\n({pformat(self.__dict__)})"
