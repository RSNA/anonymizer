import os
import time
import logging
from pprint import pformat
from typing import Dict, Tuple, List
from dataclasses import dataclass, field
from pathlib import Path
from pynetdicom._globals import ALL_TRANSFER_SYNTAXES, DEFAULT_TRANSFER_SYNTAXES
from utils.modalities import MODALITIES
from utils.translate import _

logger = logging.getLogger(__name__)


# Controller Custom Error classes:
class DICOMRuntimeError(Exception):
    pass


class AuthenticationError(Exception):
    pass


@dataclass
class DICOMNode:
    ip: str
    port: int
    aet: str
    local: bool

    def __repr__(self) -> str:
        return f"AET '{self.aet}' on host {self.ip}:{self.port}"


@dataclass
class NetworkTimeouts:
    # all values in seconds
    tcp_connection: float  # max time to wait for tcp connection to be established
    acse: float  # max time to wait for association messages
    dimse: float  # max time to wait for DIMSE messages
    network: float  # max time to wait for network messages


@dataclass
class LoggingLevels:
    anonymizer: int  # Logging level
    pynetdicom: int  # Logging level
    pydicom: bool  # enable/disable debug config


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
    source: DICOMNode | str
    series: List[Series]


@dataclass
class PHI:
    patient_name: str = ""
    patient_id: str = ""
    sex: str = "U"
    dob: str | None = None
    weight: str | None = None
    bmi: str | None = None
    size: str | None = None
    smoker: str | None = None
    medical_alerts: str | None = None
    allergies: str | None = None
    ethnic_group: str | None = None
    reason_for_visit: str | None = None
    admitting_diagnoses: str | None = None
    history: str | None = None
    additional_history: str | None = None
    comments: str | None = None
    studies: List[Study] = field(default_factory=list)


@dataclass
class AWSCognito:
    account_id: str
    region_name: str
    app_client_id: str
    user_pool_id: str
    identity_pool_id: str
    s3_bucket: str
    s3_prefix: str
    username: str
    password: str


@dataclass
class ProjectModel:
    # Sub-directories in the storage directory:
    PRIVATE_DIR = "private"
    PUBLIC_DIR = "public"
    PHI_EXPORT_DIR = "phi_export"
    QUARANTINE_DIR = "quarantine"

    # Model Version Control
    MODEL_VERSION = 1

    @staticmethod
    def default_site_id() -> str:
        # (the JAVA Anonymizer created a 6 digit ID based on minutes since 1 Jan 1970 and cycling every million mins (695 days))
        # Automatically generate a decimal character unique Site ID based on
        # the number of 30 minute intervals since 1 Jan 1970
        return str(int(time.time() / (60 * 30)))

    @staticmethod
    def default_storage_dir() -> Path:
        return Path(os.path.expanduser("~"), _("ANONYMIZER_STORE"))

    @staticmethod
    def default_local_server() -> DICOMNode:
        return DICOMNode("127.0.0.1", 1045, _("ANONYMIZER"), True)

    @staticmethod
    def default_remote_scps() -> Dict[str, DICOMNode]:
        return {
            "QUERY": DICOMNode("127.0.0.1", 4242, "ORTHANC", False),
            "EXPORT": DICOMNode("127.0.0.1", 11112, "EXPORTAE", False),
        }

    @staticmethod
    def default_aws_cognito() -> AWSCognito:
        return AWSCognito(
            account_id="691746062725",
            region_name="us-east-1",
            app_client_id="fgnijvmig42ruvn37mte1p9au",
            user_pool_id="us-east-1_cFn3IKLqG",
            identity_pool_id="us-east-1:3c616c9d-58f0-4c89-a412-ea8cf259039a",
            s3_bucket="amplify-datauploader-prodmi-stagingbucketeec2e4de-x4qrvyzen65z",
            s3_prefix="private",
            username="anonymizer2",
            password="SpeedFast1967#",
        )

    @staticmethod
    def default_storage_classes() -> List[str]:
        return []

    @staticmethod
    def default_modalities() -> List[str]:
        return ["CR", "DX", "CT", "MR"]

    @staticmethod
    def default_transfer_syntaxes() -> List[str]:
        return DEFAULT_TRANSFER_SYNTAXES

    @staticmethod
    def default_timeouts() -> NetworkTimeouts:
        return NetworkTimeouts(5, 30, 30, 60)

    @staticmethod
    def default_logging_levels() -> LoggingLevels:
        return LoggingLevels(logging.INFO, logging.WARNING, False)

    version: int = MODEL_VERSION
    site_id: str = field(default_factory=default_site_id)
    project_name: str = _("MY_PROJECT")
    uid_root: str = "1.2.826.0.1.3680043.10.188"
    storage_dir: Path = field(default_factory=default_storage_dir)
    modalities: List[str] = field(default_factory=default_modalities)
    storage_classes: List[str] = field(default_factory=default_storage_classes)  # re-initialised in post_init
    transfer_syntaxes: List[str] = field(default_factory=default_transfer_syntaxes)
    logging_levels: LoggingLevels = field(default_factory=default_logging_levels)

    scu: DICOMNode = field(default_factory=default_local_server)
    scp: DICOMNode = field(default_factory=default_local_server)
    remote_scps: Dict[str, DICOMNode] = field(default_factory=default_remote_scps)
    export_to_AWS: bool = False
    aws_cognito: AWSCognito = field(default_factory=default_aws_cognito)
    network_timeouts: NetworkTimeouts = field(default_factory=default_timeouts)
    anonymizer_script_path: Path = Path("assets/scripts/default-anonymizer.script")

    def __post_init__(self):
        self.set_storage_classes_from_modalities()

    def get_class_name(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        return f"{self.get_class_name()}\n({pformat(self.__dict__)})"

    def images_dir(self) -> Path:
        return self.storage_dir.joinpath(self.PUBLIC_DIR)

    def private_dir(self) -> Path:
        return self.storage_dir.joinpath(self.PRIVATE_DIR)

    def abridged_storage_dir(self) -> str:
        return f".../{self.storage_dir.parts[-2]}/{self.storage_dir.parts[-1]}"

    def phi_export_dir(self) -> Path:
        return self.storage_dir.joinpath(self.PRIVATE_DIR, self.PHI_EXPORT_DIR)

    def regenerate_site_id(self) -> None:
        self.site_id = self.default_site_id()

    def set_storage_classes_from_modalities(self):
        if self.storage_classes is None:
            self.storage_classes = []
        else:
            self.storage_classes.clear()
        for modality in self.modalities:
            self.storage_classes += MODALITIES[modality][1]
