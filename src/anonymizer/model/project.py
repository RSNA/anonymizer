"""
This module contains the ProjectModel class and related data classes for storing project settings and configurations.
"""

import time
from copy import copy, deepcopy
from dataclasses import asdict, dataclass, field
from logging import INFO, WARNING, getLevelName
from pathlib import Path
from pprint import pformat
from typing import Dict, List

from dataclasses_json import config, dataclass_json
from pynetdicom._globals import DEFAULT_TRANSFER_SYNTAXES  # type: ignore

from anonymizer.utils.modalities import get_modalities
from anonymizer.utils.translate import _
from anonymizer.utils.version import get_version


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
    sql: bool  # enable/disable SQLAlchemy echo for AnonymizerModel
    store_dicom_source: bool  # store original DICOM files to private/source

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}('anonymizer': {getLevelName(self.anonymizer)}, 'pynetdicom': {getLevelName(self.pynetdicom)}, 'pydicom': {self.pydicom}, 'sql': {self.sql}), 'store_dicom_source': {self.store_dicom_source})"


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

    def __repr__(self) -> str:
        d_copy = copy(self)
        d_copy.password = len(self.password) * "*"
        return f"\nAWSCognito\n({pformat(asdict(d_copy), sort_dicts=False)})"


@dataclass_json()
@dataclass
class ProjectModel:
    """
    The Project data model class to store all the project settings and configurations.
    """

    # Project Model Version Control
    MODEL_VERSION = 5

    # SQLite DB configuration for SQLAlchemy
    # TODO: expand for other supported databases (PostgreSQL, MySQL, etc.)
    SQLITE_DB_DIALECT = "sqlite"
    SQLITE_DB_FILENAME = "anonymizer.db"

    # As per instructions here: https://www.medicalconnections.co.uk/kb/ImplementationUID-And-ImplementationName
    RSNA_ROOT_ORG_UID = "1.2.826.0.1.3680043.10.474"  # sub UID from medicalconnections.co.uk as used by JavaAnonymizer
    IMPLEMENTATION_CLASS_UID = RSNA_ROOT_ORG_UID + ".1"  # UID: (0002,0012)
    IMPLEMENTATION_VERSION_NAME: str = "rsna_anon_" + get_version()  # SH: (0002,0013)

    @staticmethod
    def default_site_id() -> str:
        # (the JAVA Anonymizer created a 6 digit ID based on minutes since 1 Jan 1970 and cycling every million mins (695 days))
        # Automatically generate a decimal character unique Site ID based on
        # the number of 30 minute intervals since 1 Jan 1970
        return str(int(time.time() / (60 * 30)))

    @staticmethod
    def default_language_code() -> str:
        return "en_US"

    @staticmethod
    def default_project_name() -> str:
        return _("MY_PROJECT").strip()

    @staticmethod
    def default_uid_root() -> str:
        return ProjectModel.RSNA_ROOT_ORG_UID + ".2"

    @staticmethod
    def base_dir() -> Path:
        return Path.home() / _("Documents").strip() / _("RSNA Anonymizer").strip()

    @staticmethod
    def default_storage_dir() -> Path:
        return ProjectModel.base_dir() / ProjectModel.default_project_name()

    @staticmethod
    def default_local_server() -> DICOMNode:
        return DICOMNode("0.0.0.0", 1045, _("ANONYMIZER"), True)

    @staticmethod
    def default_remote_scps() -> Dict[str, DICOMNode]:
        return {
            _("QUERY"): DICOMNode("127.0.0.1", 4242, "ORTHANC", False),
            _("EXPORT"): DICOMNode("127.0.0.1", 11112, "EXPORTAE", False),
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
        return LoggingLevels(INFO, WARNING, False, False, False)

    # Custom encoder and decoder for Path objects
    path_field = config(encoder=str, decoder=Path)  # Encode Path as string, Decode string to Path

    version: int = MODEL_VERSION
    language_code: str = field(default_factory=default_language_code)
    site_id: str = field(default_factory=default_site_id)
    project_name: str = field(default_factory=default_project_name)
    uid_root: str = field(default_factory=default_uid_root)
    remove_pixel_phi: bool = False
    storage_dir: Path = field(default_factory=default_storage_dir, metadata=path_field)
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
    anonymizer_script_path: Path = field(default=Path("assets/scripts/default-anonymizer.script"), metadata=path_field)

    def __post_init__(self):
        # Sub-directories in the storage directory:
        self.PRIVATE_DIR = _("private")
        self.PUBLIC_DIR = _("public")
        self.PHI_EXPORT_DIR = _("phi_export")
        self.QUARANTINE_DIR = _("quarantine")
        self.set_storage_classes_from_modalities()

    def get_class_name(self) -> str:
        return self.__class__.__name__

    def __repr__(self) -> str:
        cpy = deepcopy(self)
        cpy.aws_cognito.password = len(cpy.aws_cognito.password) * "*"
        return f"{self.get_class_name()}\n({pformat(asdict(cpy), sort_dicts=False)})"

    def abridged_path(self, path_obj: Path, depth: int = 4, include_filename: bool = False) -> str:
        """
        Returns an abridged representation of a path.

        Args:
            path_obj (Path): The Path object to abridge.
            depth (int): The number of trailing directory levels to include.
            include_filename (bool): Whether to include the filename in the output.

        Returns:
            str: The abridged path.
        """
        if depth <= 0:
            raise ValueError("Depth must be a positive integer.")

        parts = path_obj.parts
        if len(parts) <= depth + int(include_filename):  # Add 1 to depth if including filename
            return str(path_obj)  # Return the full path if it's short enough
        else:
            if include_filename:
                abridged_dir = f".../{'/'.join(parts[-(depth + 1) : -1])}"  # Exclude filename from parts
                return f"{abridged_dir}/{path_obj.name}"
            else:
                abridged_dir = f".../{'/'.join(parts[-depth:])}"
                return abridged_dir

    def images_dir(self) -> Path:
        return self.storage_dir.joinpath(self.PUBLIC_DIR)

    def private_dir(self) -> Path:
        return self.storage_dir.joinpath(self.PRIVATE_DIR)

    def abridged_storage_dir(self) -> str:
        return self.abridged_path(self.storage_dir)

    def get_db_url(self) -> str:
        DB_DIR = self.private_dir()
        DB_FILE = DB_DIR / ProjectModel.SQLITE_DB_FILENAME
        DB_URL = f"{ProjectModel.SQLITE_DB_DIALECT}:///{DB_FILE}"
        return DB_URL

    def abridged_script_path(self) -> str:
        return self.abridged_path(self.anonymizer_script_path, include_filename=True)

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
            self.storage_classes += get_modalities()[modality][1]

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
