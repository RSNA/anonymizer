import logging
from typing import Dict, Tuple, List
from dataclasses import dataclass
from pathlib import Path
from pynetdicom._globals import ALL_TRANSFER_SYNTAXES, DEFAULT_TRANSFER_SYNTAXES
from utils.translate import _
import model.config as config


logger = logging.getLogger(__name__)


# Controller Custom Error classes:
class DICOMRuntimeError(Exception):
    pass


@dataclass
class DICOMNode:
    ip: str
    port: int
    aet: str
    scp: bool


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


class ProjectModel:
    pickle_filename = "ProjectModel.pkl"
    default_anonymizer_script_path = Path("assets/scripts/default-anonymizer.script")
    # TODO: provide UX to manage the allowed storage classes and supported transfer syntaxes, *FIXED FOR MVP*
    _TRANSFER_SYNTAXES = DEFAULT_TRANSFER_SYNTAXES  # change to ALL_TRANSFER_SYNTAXES to support compression
    _RADIOLOGY_STORAGE_CLASSES = {
        "Computed Radiography Image Storage": "1.2.840.10008.5.1.4.1.1.1",
        "Computed Tomography Image Storage": "1.2.840.10008.5.1.4.1.1.2",
        # "Enhanced CT Image Storage": "1.2.840.10008.5.1.4.1.1.2.1",
        "Digital X-Ray Image Storage - For Presentation": "1.2.840.10008.5.1.4.1.1.1.1",
        "Digital X-Ray Image Storage - For Processing": "1.2.840.10008.5.1.4.1.1.1.1.1",
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

    def __init__(
        self,
        siteid: str,
        projectname: str,
        trialname: str,
        uidroot: str,
        storage_dir: Path,
        scu: DICOMNode,
        scp: DICOMNode,
        remote_scps: Dict[str, DICOMNode],
        network_timeout: int,
        anonymizer_script_path: Path = default_anonymizer_script_path,
    ):
        # Check if any string parameter is empty (zero-length)
        if not all(
            param.strip() for param in (siteid, projectname, trialname, uidroot)
        ):
            raise ValueError("String parameters must not be empty")

        # Check if storage_dir is a valid directory
        if not storage_dir or not storage_dir.is_dir():
            raise ValueError("storage_dir must be a valid directory")

        # Check if anonymizer_script_path is a valid Path and exists
        if (
            not anonymizer_script_path
            or not isinstance(anonymizer_script_path, Path)
            or not anonymizer_script_path.exists()
        ):
            raise ValueError("anonymizer_script_path must be a valid Path that exists")

        # Check if network_timeout is a positive integer
        if not isinstance(network_timeout, int) or network_timeout <= 0:
            raise ValueError("network_timeout must be a positive integer")

        self.siteid = siteid
        self.projectname = projectname
        self.trialname = trialname
        self.uidroot = uidroot
        self.storage_dir = storage_dir
        self.scu = scu
        self.scp = scp
        self.remote_scps = remote_scps
        self.network_timeout = network_timeout
        self.anonymizer_script_path = anonymizer_script_path

    def __str__(self):
        return f"{self.siteid}-{self.projectname}-{self.trialname}"

    def __repr__(self):
        return f"{self.siteid}-{self.projectname}-{self.trialname}"

    def __hash__(self):
        return hash(self.__dict__)
