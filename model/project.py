import os
import time
from logging import DEBUG, INFO, WARNING, getLevelName
from pprint import pformat
from copy import deepcopy
from typing import Dict, Tuple, List
from dataclasses import dataclass, field, asdict
from pathlib import Path
from pynetdicom._globals import ALL_TRANSFER_SYNTAXES, DEFAULT_TRANSFER_SYNTAXES
from utils.modalities import MODALITIES
from utils.translate import _
from __version__ import __version__


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

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}('anonymizer': {getLevelName(self.anonymizer)}, 'pynetdicom': {getLevelName(self.pynetdicom)}, 'pydicom': {self.pydicom}"


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

    # Project Model Version Control
    MODEL_VERSION = 1

    # As per instructions here: https://www.medicalconnections.co.uk/kb/ImplementationUID-And-ImplementationName
    RSNA_ROOT_ORG_UID = "1.2.826.0.1.3680043.10.474"  # sub UID from medicalconnections.co.uk as used by JavaAnonymizer
    IMPLEMENTATION_CLASS_UID = RSNA_ROOT_ORG_UID + ".1"  # UID: (0002,0012)
    IMPLEMENTATION_VERSION_NAME = "rsna_anon" + __version__  # SH: (0002,0013)

    @staticmethod
    def default_site_id() -> str:
        # (the JAVA Anonymizer created a 6 digit ID based on minutes since 1 Jan 1970 and cycling every million mins (695 days))
        # Automatically generate a decimal character unique Site ID based on
        # the number of 30 minute intervals since 1 Jan 1970
        return str(int(time.time() / (60 * 30)))

    @staticmethod
    def default_project_name() -> str:
        return _("MY_PROJECT")

    @staticmethod
    def default_uid_root() -> str:
        return ProjectModel.RSNA_ROOT_ORG_UID + ".2"

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
            username="",
            password="",
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
        return LoggingLevels(INFO, WARNING, False)

    version: int = MODEL_VERSION
    site_id: str = field(default_factory=default_site_id)
    project_name: str = field(default_factory=default_project_name)
    uid_root: str = field(default_factory=default_uid_root)
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
        d = asdict(self)
        d["aws_cognito"] = deepcopy(self.aws_cognito)
        d["aws_cognito"].password = len(d["aws_cognito"].password) * "*"
        # return pformat(d)
        return f"{self.get_class_name()}\n({pformat(d)})"

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

    def add_storage_class(self, storage_class: str):
        if storage_class not in self.storage_classes:
            self.storage_classes.append(storage_class)

    def remove_storage_class(self, storage_class: str):
        if storage_class in self.storage_classes:
            self.storage_classes.remove(storage_class)

    def add_transfer_syntax(self, transfer_syntax: str):
        if transfer_syntax not in self.transfer_syntaxes:
            self.transfer_syntaxes.append(transfer_syntax)

    def remove_transfer_syntax(self, transfer_syntax: str):
        if transfer_syntax in self.transfer_syntaxes:
            self.transfer_syntaxes.remove(transfer_syntax)
