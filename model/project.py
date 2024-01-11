import os
import uuid
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
class NetworkTimeouts:
    tcp_connection: float  # max time to wait for tcp connection to be established
    acse: float  # max time to wait for association messages
    dimse: float  # max time to wait for DIMSE messages
    network: float  # max time to wait for network messages


@dataclass
class Study:
    study_date: str
    anon_date_delta: int
    accession_number: str
    study_uid: str
    source: DICOMNode | str


@dataclass
class PHI:
    patient_name: str
    patient_id: str
    studies: List[Study]


@dataclass
class AWSCognito:
    region_name: str
    client_id: str
    s3_bucket: str
    s3_prefix: str
    username: str
    password: str


@dataclass
class ProjectModel:
    @staticmethod
    def default_site_id() -> str:
        # Automatically Generate 12 hexadecimal character Unique Site ID based UUID Version 4
        # UUID version 4 generates 32 hexadecimal character UUIDs based on random or pseudo-random numbers
        site_id = str(uuid.uuid4()).replace("-", "")[:12].upper()

        # Convert the UUID to a string with hyphens
        site_id_str = str(site_id)

        # Split the string into 3 sets of 4 characters
        uid_12_chars = "-".join([site_id_str[:4], site_id_str[4:8], site_id_str[8:12]])

        return uid_12_chars

    @staticmethod
    def default_project_filename() -> str:
        return "ProjectModel.pkl"

    @staticmethod
    def default_storage_dir() -> Path:
        return Path(os.path.expanduser("~"), "ANONYMIZER_STORE")

    @staticmethod
    def default_local_server() -> DICOMNode:
        return DICOMNode("127.0.0.1", 1045, _("ANONYMIZER"), True)

    @staticmethod
    def default_remote_scps() -> Dict[str, DICOMNode]:
        return {
            "QUERY": DICOMNode("127.0.0.1", 11112, "QUERYAE", False),
            "EXPORT": DICOMNode("127.0.0.1", 11112, "EXPORTAE", False),
        }

    @staticmethod
    def default_aws_cognito() -> AWSCognito:
        # Identity Pool ID: 1:3c616c9d-58f0-4c89-a412-ea8cf259039a
        # User Pool ID: us-east-1_cFn3IKLqG
        return AWSCognito(
            region_name="us-east-1",
            client_id="fgnijvmig42ruvn37mte1p9au",
            s3_bucket="amplify-datauploader-prodmi-stagingbucketeec2e4de-x4qrvyzen65z",
            s3_prefix="private",
            username="anonymizer2",
            password="Anonymizer2!",
        )

    @staticmethod
    def default_storage_classes() -> List[str]:
        return [
            "1.2.840.10008.5.1.4.1.1.1",  # "Computed Radiography Image Storage"
            "1.2.840.10008.5.1.4.1.1.1.1",  # "Digital X-Ray Image Storage - For Presentation"
            "1.2.840.10008.5.1.4.1.1.1.1.1",  # "Digital X-Ray Image Storage - For Processing"
            "1.2.840.10008.5.1.4.1.1.2",  # "Computed Tomography Image Storage"
            "1.2.840.10008.5.1.4.1.1.4",  # "Magnetic Resonance Image Storage"
        ]

    @staticmethod
    def default_transfer_syntaxes() -> List[str]:
        return DEFAULT_TRANSFER_SYNTAXES

    @staticmethod
    def default_timeouts() -> NetworkTimeouts:
        return NetworkTimeouts(5, 30, 30, 60)

    site_id: str = field(default_factory=default_site_id)
    project_name: str = _("PROJECT")
    trial_name: str = _("TRIAL")
    uid_root: str = "1.2.826.0.1.3680043.10.188"
    storage_dir: Path = field(default_factory=default_storage_dir)
    storage_classes: List[str] = field(default_factory=default_storage_classes)
    transfer_syntaxes: List[str] = field(default_factory=default_transfer_syntaxes)

    scu: DICOMNode = field(default_factory=default_local_server)
    scp: DICOMNode = field(default_factory=default_local_server)
    remote_scps: Dict[str, DICOMNode] = field(default_factory=default_remote_scps)
    export_to_AWS: bool = False
    aws_cognito: AWSCognito = field(default_factory=default_aws_cognito)
    network_timeouts: NetworkTimeouts = field(default_factory=default_timeouts)
    anonymizer_script_path: Path = Path("assets/scripts/default-anonymizer.script")

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}\n({pformat(self.__dict__)})"

    def abridged_storage_dir(self) -> str:
        return f".../{self.storage_dir.parts[-2]}/{self.storage_dir.parts[-1]}"

    def regenerate_site_id(self) -> None:
        self.site_id = self.default_site_id()
