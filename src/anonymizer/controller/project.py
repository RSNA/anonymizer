"""
This module defines the ProjectController class, which acts as a DICOM Application Entity (AE) and provides various DICOM services such as C-STORE, C-MOVE, C-ECHO, C-FIND, and C-SEND.

The ProjectController class handles association requests, performs DICOM queries and retrievals, and provides export methods for sending anonymized studies to AWS S3 and exporting PHI (Protected Health Information) to CSV.

The module also defines several data classes used for request and response objects, as well as data structures for organizing DICOM hierarchy.
"""

import csv
import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
from typing import Any, Dict, List, Optional, Tuple, cast

import boto3
from psutil import virtual_memory
from pydicom import Dataset, dcmread
from pydicom.dataset import FileMetaDataset
from pydicom.uid import UID
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.association import Association
from pynetdicom.events import (
    EVT_C_ECHO,
    EVT_C_STORE,
    Event,
    EventHandlerType,
)
from pynetdicom.presentation import PresentationContext, build_context
from pynetdicom.status import (
    QR_FIND_SERVICE_CLASS_STATUS,
    QR_MOVE_SERVICE_CLASS_STATUS,
    STORAGE_SERVICE_CLASS_STATUS,
    VERIFICATION_SERVICE_CLASS_STATUS,
)

from anonymizer.controller.anonymizer import AnonymizerController
from anonymizer.controller.dicom_C_codes import (
    C_FAILURE,
    C_PENDING_A,
    C_PENDING_B,
    C_STORE_DATASET_ERROR,
    C_STORE_DECODE_ERROR,
    C_SUCCESS,
    C_WARNING,
)
from anonymizer.model.anonymizer import PHI_IndexRecord
from anonymizer.model.project import (
    AuthenticationError,
    DICOMNode,
    DICOMRuntimeError,
    NetworkTimeouts,
    ProjectModel,
)
from anonymizer.utils.logging import set_logging_levels
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class InstanceUIDHierarchy:
    def __init__(self, uid: str, number: int | None = None):
        self.uid = uid
        self.number = number

    def __str__(self):
        return f"{self.uid},{self.number or ''}"


class SeriesUIDHierarchy:
    def __init__(
        self,
        uid: str,
        number: int | None = None,
        modality: str | None = None,
        sop_class_uid: str | None = None,
        description: str | None = None,  # TODO: add BodyPartExamined?
        instance_count: int = 0,  # from NumberOfSeriesRelatedInstances
        instances: Optional[Dict[str, InstanceUIDHierarchy]] = None,
    ):
        self.uid = uid
        self.number = number
        self.modality = modality
        self.sop_class_uid = sop_class_uid
        self.instance_count = instance_count
        self.description = description
        self.instances = instances if instances is not None else {}
        # from send_c_move status response:
        self.completed_sub_ops = 0
        self.failed_sub_ops = 0
        self.remaining_sub_ops = 0
        self.warning_sub_ops = 0

    def __str__(self):
        instances_str = "{}"
        if self.instances:
            instances_str = ""
            for instance in self.instances.values():
                instances_str += "\n----" + str(instance)
        return f"{self.uid},{self.number or ''},{self.modality or ''},{self.description or ''}[{self.completed_sub_ops},{self.failed_sub_ops},{self.remaining_sub_ops},{self.warning_sub_ops}]i{self.instance_count}{instances_str}"

    def get_number_of_instances(self) -> int:
        return len(self.instances)

    def find_instance(self, instance_uid: str) -> Optional[InstanceUIDHierarchy]:
        if instance_uid in self.instances:
            return self.instances[instance_uid]
        return None

    def update_move_stats(self, status: Dataset):
        if hasattr(status, "NumberOfRemainingSuboperations"):
            self.remaining_sub_ops = status.NumberOfRemainingSuboperations
        else:
            self.remaining_sub_ops = 0  # When status is C_SUCCESS
        self.completed_sub_ops = status.NumberOfCompletedSuboperations
        self.failed_sub_ops = status.NumberOfFailedSuboperations
        self.warning_sub_ops = status.NumberOfWarningSuboperations

    def update_move_stats_instance_level(self, status: Dataset):
        # Do not track RemainingSuboperations
        if status.Status == C_SUCCESS and status.NumberOfCompletedSuboperations == 1:
            self.completed_sub_ops += 1
            self.failed_sub_ops += status.NumberOfFailedSuboperations
            self.warning_sub_ops += status.NumberOfWarningSuboperations


class StudyUIDHierarchy:
    def __init__(
        self,
        uid: str,
        ptid: str,
        series: Dict[str, SeriesUIDHierarchy] | None = None,
    ):
        self.uid = uid
        self.ptid = ptid
        self.last_error_msg: str | None = None  # set by GetStudyHierarchy() or Move Operation
        self.series = series if series is not None else {}
        self.pending_instances = 0  # set by move operation
        # from send_c_move status response:
        self.completed_sub_ops: int = 0
        self.failed_sub_ops: int = 0
        self.remaining_sub_ops: int = 0
        self.warning_sub_ops: int = 0

    def __str__(self):
        series_str = "{}"
        if self.series:
            series_str = ""
            for series in self.series.values():
                series_str += "\n--" + str(series)
        return f"{self.uid},{self.last_error_msg or ''},[{self.completed_sub_ops},{self.failed_sub_ops},{self.remaining_sub_ops},{self.warning_sub_ops}]i{self.get_number_of_instances()}{series_str}"

    def get_number_of_instances(self) -> int:
        if self.series is None:
            return 0
        return sum(series.instance_count for series in self.series.values())

    def get_instances(self) -> List[InstanceUIDHierarchy]:
        instances = []
        for series_obj in self.series.values():
            instances.extend(series_obj.instances.values())
        return instances

    def update_move_stats(self, status: Dataset):
        if hasattr(status, "NumberOfRemainingSuboperations"):
            self.remaining_sub_ops = status.NumberOfRemainingSuboperations
        else:
            self.remaining_sub_ops = 0  # When status is C_SUCCESS
        self.completed_sub_ops = status.NumberOfCompletedSuboperations
        self.failed_sub_ops = status.NumberOfFailedSuboperations
        self.warning_sub_ops = status.NumberOfWarningSuboperations

    def find_instance(self, instance_uid: str) -> Optional[InstanceUIDHierarchy]:
        for series in self.series.values():
            if instance_uid in series.instances:
                return series.instances[instance_uid]
        return None


@dataclass
class EchoRequest:
    scp: str | DICOMNode
    ux_Q: Queue


@dataclass
class EchoResponse:
    success: bool
    error: str | None


@dataclass
class FindStudyRequest:
    scp_name: str
    name: str
    id: str
    acc_no: str | list[str]
    study_date: str
    modality: str
    ux_Q: Queue


@dataclass
class FindStudyResponse:
    status: Dataset
    study_result: Dataset | None


@dataclass
class MoveStudiesRequest:
    scp_name: str
    dest_scp_ae: str
    level: str
    studies: list[StudyUIDHierarchy]  # Move process updates hierarchy, no MoveStudiesResponse


@dataclass
class ExportPatientsRequest:
    dest_name: str
    patient_ids: list[str]  # list of patient IDs to export
    ux_Q: Queue  # queue for UX updates for the full export


@dataclass
class ExportPatientsResponse:
    patient_id: str
    files_sent: int  # incremented for each file sent successfully
    error: str | None  # error message
    complete: bool


class ProjectController(AE):
    """
    ProjectController is a DICOM Application Entity (pynetdicom.ae sub-class)

    It acts as both a Service Class Provider (SCP) and Service Class User (SCU) for DICOM services:
    scp: C-STORE, C-MOVE
    scu: C-ECHO, C-FIND, C-SEND

    The Study Root Query/Retrieve Information Model is used for C-FIND and C-MOVE services.

    The DICOM SCP will only respond to association requests which address its configured AE Title.
    Any remote client is allowed to associate with the Anonymizer.
    The AE Title of the calling SCU is not checked against a list of permissable client AE Titles.
    The DICOM SCP will allow a maximum of 10 simultaneous associations, as per the pynetdicom.ae default.

    The C-ECHO, C-FIND and C-MOVE Association contexts are set using the Study Root Query & Retrieve SOP classes and default transfer_syntaxes.
    The C-STORE and C-SEND Association contexts are set using the ProjectModel's configured Storage classes and Transfer syntaxes.

    The ProjectController also provides export methods to send anonymized studies to AWS S3 and for exporting PHI of the AnonymizerModel to CSV.
    """

    PROJECT_MODEL_FILENAME_PKL = "ProjectModel.pkl"
    PROJECT_MODEL_FILENAME_JSON = "ProjectModel.json"

    # DICOM service class uids:
    _VERIFICATION_CLASS = "1.2.840.10008.1.1"  # Echo
    _STUDY_ROOT_QR_CLASSES = [
        "1.2.840.10008.5.1.4.1.2.2.1",  # Find
        "1.2.840.10008.5.1.4.1.2.2.2",  # Move
        "1.2.840.10008.5.1.4.1.2.2.3",  # Get
    ]

    # The following parameters may become part of ProjectModel in future for advanced user configuration:
    _handle_store_time_slice_interval = 0.05  # seconds
    _export_file_time_slice_interval = 0.1  # seconds
    _patient_export_thread_pool_size = 4  # concurrent threads
    _study_move_thread_pool_size = 2  # concurrent threads
    _memory_available_backoff_threshold = 1 << 30  # When available memory is less than 1GB, back-off in _handle_store

    # DICOM Data model sanity checking:
    _required_attributes_study_query = [
        "StudyInstanceUID",
        "ModalitiesInStudy",
        "NumberOfStudyRelatedSeries",
        "NumberOfStudyRelatedInstances",
    ]
    _required_attributes_series_query = [
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "Modality",
    ]
    _required_attributes_instance_query = [
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "SOPInstanceUID",
    ]
    _query_result_fields_to_remove = [
        "QueryRetrieveLevel",
        "RetrieveAETitle",
        "SpecificCharacterSet",
    ]

    def _strip_query_result_fields(self, ds: Dataset) -> None:
        for field in self._query_result_fields_to_remove:
            if field in ds:
                delattr(ds, field)

    def _missing_attributes(self, required_attributes: list[str], ds: Dataset) -> list[str]:
        """
        Returns a list of missing attributes from the given dataset.

        Args:
            required_attributes (list[str]): A list of attribute names that are required.
            ds (Dataset): The dataset to check for missing attributes.

        Returns:
            list[str]: A list of attribute names that are missing from the dataset.
        """
        return [attr_name for attr_name in required_attributes if attr_name not in ds or getattr(ds, attr_name) == ""]

    def __init__(self, model: ProjectModel):
        """
        Initializes the ProjectController object.

        Args:
            model (ProjectModel): The project model object.

        Attributes:
            model (ProjectModel): The project model object.
            _implementation_class_uid (UID): The implementation class UID added to association requests.
            _implementation_version_name (str): The implementation version name added to association requests.
            _maximum_pdu_size (int): The maximum PDU size. 0 means no limit.
            _require_called_aet (bool): Flag indicating if remote clients must provide Anonymizer's AE Title.
            _aws_credentials (dict): The AWS credentials.
            _s3 (None or S3Client): The S3 client object.
            _aws_expiration_datetime (None or datetime): The expiration datetime for AWS credentials.
            _aws_user_directory (None or str): The AWS user directory.
            _aws_last_error (None or str): The last AWS error.
            anonymizer (AnonymizerController): The anonymizer controller object.
        """
        super().__init__(ae_title=model.scu.aet)
        self.model = model
        set_logging_levels(levels=model.logging_levels)
        # Ensure storage, public and private directories exist:
        self.model.storage_dir.joinpath(self.model.PRIVATE_DIR).mkdir(parents=True, exist_ok=True)
        self.model.storage_dir.joinpath(self.model.PUBLIC_DIR).mkdir(exist_ok=True)
        self.set_dicom_timeouts(timeouts=model.network_timeouts)
        self._implementation_class_uid = UID(self.model.IMPLEMENTATION_CLASS_UID)  # added to association requests
        self._implementation_version_name = self.model.IMPLEMENTATION_VERSION_NAME  # added to association requests
        self._maximum_pdu_size = 0  # 0 means no limit
        # self._maximum_associations = 10 # max simultaneous remote associations, 10 is the default
        self._require_called_aet = True  # remote clients must provide Anonymizer's AE Title
        # TODO: project model optional setting for allowed list of calling AETs
        # self._require_calling_aet = ["<list of allowed calling AETs>"] # Default: Allow any calling AE Title
        self.set_radiology_storage_contexts()
        self.set_verification_context()
        self._reset_scp_vars()

        # Dynamic AWS vars:
        self._aws_credentials = {}
        self._s3 = None
        self._aws_expiration_datetime: datetime | None = None
        self._aws_user_directory: str | None = None
        self._aws_last_error: str | None = None
        self.anonymizer = AnonymizerController(project_model=model)

    def __str__(self):
        return super().__str__() + f"\n{self.model}" + f"\n{self.anonymizer.model}"

    def _reset_scp_vars(self):
        self._abort_query = False
        self._abort_move = False
        self._abort_export = False
        self._export_futures = None
        self._export_executor = None
        self._move_futures = None
        self._move_executor = None
        self.scp = None

    def update_model(self, new_model: ProjectModel | None = None):
        self.stop_scp()  # calls _reset_scp_vars
        if new_model:
            self.model: ProjectModel = new_model
            self.anonymizer.project_model = new_model
        self.set_dicom_timeouts(self.model.network_timeouts)
        self.set_radiology_storage_contexts()
        self.set_verification_context()
        self.anonymizer.model.engine.echo = self.model.logging_levels.sql
        self.save_model()
        self.start_scp()

    def save_model(self, dest_dir: Path | None = None) -> bool:
        if dest_dir is None:
            dest_dir = self.model.storage_dir
        filepath = dest_dir / self.PROJECT_MODEL_FILENAME_JSON
        try:
            with open(filepath, "w") as f:
                f.write(self.model.to_json(indent=4))  # type: ignore

            # Backup to [filepath].bak
            shutil.copy2(filepath, filepath.with_suffix(filepath.suffix + ".bak"))
            logger.debug(f"Model saved to: {filepath}")
            return True
        except Exception as e:
            logger.error(f"Fatal Error saving ProjectModel to {filepath}: {e}")
            return False

    # Value of None means no timeout
    def set_dicom_timeouts(self, timeouts: NetworkTimeouts):
        # The maximum amount of time (in seconds) to wait for a TCP connection to be established:
        # only used during the connection phase of an association request.
        self._connection_timeout = timeouts.tcp_connection
        # ACSE: association timeout
        # The maximum amount of time (in seconds) to wait for association related messages.
        self._acse_timeout = timeouts.acse
        # DICOM Message Service Element timeout
        # The maximum amount of time (in seconds) to wait for DIMSE related messages.
        self._dimse_timeout = timeouts.dimse
        # Network timeout
        # The maximum amount of time (in seconds) to wait for network messages before closing an association:
        self._network_timeout = timeouts.network

    def get_network_timeouts(self) -> NetworkTimeouts:
        return self.model.network_timeouts

    # FOR SCP AE: Set allowed storage and verification contexts and corresponding transfer syntaxes
    def set_verification_context(self):
        self.add_supported_context(self._VERIFICATION_CLASS)  # default transfer syntaxes
        return

    def set_radiology_storage_contexts(self) -> None:
        """
        Sets the radiology storage contexts by adding supported contexts for each storage class.

        This method iterates over the storage classes in the model and adds supported contexts for each class
        using the user-set transfer syntaxes for storage.

        Called at initialization and when the model is updated.

        Returns:
            None
        """
        for uid in sorted(self.model.storage_classes):
            self.add_supported_context(uid, self.model.transfer_syntaxes)
        return

    # Contexts FOR SCU Association:
    def get_verification_context(self) -> PresentationContext:
        return build_context(self._VERIFICATION_CLASS)  # default transfer syntaxes

    def get_radiology_storage_contexts(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, self.model.transfer_syntaxes)
            for abstract_syntax in self.model.storage_classes
        ]

    def set_study_root_qr_contexts(self) -> None:
        for uid in sorted(self._STUDY_ROOT_QR_CLASSES):
            self.add_supported_context(uid)  # default transfer syntaxes
        return

    # For testing:
    def get_radiology_storage_contexts_BIGENDIAN(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, "1.2.840.10008.1.2.2")  # Explicit VR Big Endian,
            for abstract_syntax in self.model.storage_classes
        ]

    def get_study_root_qr_contexts(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, self.model.transfer_syntaxes)
            for abstract_syntax in self._STUDY_ROOT_QR_CLASSES
        ]

    def get_study_root_find_contexts(self) -> List[PresentationContext]:
        return [build_context(self._STUDY_ROOT_QR_CLASSES[0])]  # default transfer syntaxes

    def get_study_root_move_contexts(self) -> List[PresentationContext]:
        return [build_context(self._STUDY_ROOT_QR_CLASSES[1])]  # default transfer syntaxes

    # DICOM C-ECHO Verification event handler (EVT_C_ECHO):
    def _handle_echo(self, event: Event):
        """
        Handles the C-ECHO event. Always returns the echo request with success.

        Args:
            event (Event): The event object containing the C-ECHO request.

        Returns:
            int: The status code indicating the success of the C-ECHO operation.
        """
        logger.debug("_handle_echo")
        remote = event.assoc.remote
        logger.info(f"C-ECHO from: {remote}")
        return C_SUCCESS

    def _handle_store(self, event: Event):
        """
        DICOM C-STORE scp event handler (EVT_C_STORE)
        Event handler called in the thread context of an SCP association. (up to 10 concurrent associations)

        Args:
            event (Event): The event containing the DICOM dataset to be stored.

        Returns:
            int: The result code indicating the success or failure of the storage operation.
        """
        # Throttle incoming requests by adding a delay to ensure UX responsiveness
        time.sleep(self._handle_store_time_slice_interval)

        # TODO: investigate use of pynetdicom temporary storage for large datasets
        # Instead pass the Event.dataset_path to the Anonymizer workers for processing only metadata, leave pixel data on disk using dcm_read(stop_before_pixels=True)
        # see: https://pydicom.github.io/pynetdicom/dev/reference/generated/pynetdicom._config.STORE_RECV_CHUNKED_DATASET.html

        # Back-off if AnonymizerQueue grows to a limit determined by available memory:
        if virtual_memory().available < self._memory_available_backoff_threshold:
            time.sleep(1)

        logger.debug("_handle_store")
        remote = event.assoc.remote
        try:
            ds = Dataset(event.dataset)
            # Remove any File Meta (Group 0x0002 elements) that may have been included
            ds = ds[0x00030000:]
        except Exception as exc:
            logger.error("Unable to decode incoming dataset")
            logger.exception(exc)
            # Unable to decode dataset
            return C_STORE_DECODE_ERROR

        # Add the File Meta Information (Group 0x0002 elements)
        ds.file_meta = FileMetaDataset(event.file_meta)
        # Only one Transfer Syntax is Big Endian (mostly retired)
        ds.is_little_endian = ds.file_meta.TransferSyntaxUID != "1.2.840.10008.1.2.2"  # Explicit VR Big Endian
        # Only one Transfer Syntax uses Implicit VR
        ds.is_implicit_VR = ds.file_meta.TransferSyntaxUID == "1.2.840.10008.1.2"  # Implicit VR Little Endian

        # File Metadata:Implementation Class UID and Version Name:
        ds.file_meta.ImplementationClassUID = UID(self.model.IMPLEMENTATION_CLASS_UID)  # UI: (0002,0012)
        ds.file_meta.ImplementationVersionName = self.model.IMPLEMENTATION_VERSION_NAME  # SH: (0002,0013)

        remote_scu = DICOMNode(remote["address"], remote["port"], remote["ae_title"], False)
        logger.debug(remote_scu)

        # DICOM Dataset integrity checking:
        # TODO: send to quarantine?
        missing_attributes = self.anonymizer.missing_attributes(ds)
        if missing_attributes != []:
            logger.error(f"Incoming dataset is missing required attributes: {missing_attributes}")
            logger.error(f"\n{ds}")
            return C_STORE_DATASET_ERROR

        if self.anonymizer.model.instance_received(ds.SOPInstanceUID):
            logger.debug(
                f"Instance already stored:{ds.PatientID}/{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}"
            )
            return C_SUCCESS

        self.anonymizer.anonymize_dataset_ex(remote_scu, ds)
        return C_SUCCESS

    def start_scp(self) -> None:
        logger.info(f"start {self.model.scp}, {self.model.storage_dir}...")

        if self.scp:
            msg = _("DICOM C-STORE scp is already running on") + f" {self.model.scp}"
            logger.error(msg)
            raise DICOMRuntimeError(msg)

        handlers = [(EVT_C_ECHO, self._handle_echo), (EVT_C_STORE, self._handle_store)]
        self._reset_scp_vars()
        self._ae_title = self.model.scu.aet

        try:
            self.scp = self.start_server(
                (self.model.scp.ip, self.model.scp.port),
                block=False,
                evt_handlers=cast(List[EventHandlerType], handlers),
            )
        except Exception as e:
            msg = _("Failed to start DICOM C-STORE scp on") + f" {self.model.scp}, Error: {str(e)}"
            logger.error(msg)
            raise DICOMRuntimeError(msg) from e

        logger.info(
            f"DICOM C-STORE scp listening on {self.model.scp}, storing files in {self.model.storage_dir}, timeouts: {self.model.network_timeouts}"
        )

    def stop_scp(self) -> None:
        if not self.scp:
            logger.error("stop_scp called but self.scp is None")
            return
        logger.info(f"Stop {self.model.scp} scp and close socket")
        self.scp.shutdown()
        self._reset_scp_vars()

    def _connect_to_scp(self, scp: str | DICOMNode, contexts: List[PresentationContext]) -> Association:
        """
        Connects to a remote DICOM SCP and establishes an association.

        Args:
            scp (str | DICOMNode): The remote SCP to connect to. It can be either a string representing the SCP name
                or a DICOMNode object.
            contexts (List[PresentationContext]): List of presentation contexts to negotiate during association.

        Returns:
            Association: The established association object.

        Raises:
            ConnectionError: If the remote SCP is not found in the model's remote_scps dictionary.
            ConnectionError: If there is a connection error to the remote SCP.
            Exception (likely ConnectionError, TimeoutError, RuntimeError): If there is an error establishing the association.
        """
        association = None
        if isinstance(scp, str):
            if scp not in self.model.remote_scps:
                raise ConnectionError(f"Remote SCP {scp} not found")
            remote_scp = self.model.remote_scps[scp]
        else:
            remote_scp = scp

        try:
            association = self.associate(
                remote_scp.ip,
                remote_scp.port,
                contexts=contexts,
                ae_title=remote_scp.aet,
                bind_address=(self.model.scu.ip, 0),
                # evt_handlers=[(EVT_ABORTED, self._handle_abort)],
            )
            if not association.is_established:
                raise ConnectionError(_("Connection error to") + f": {remote_scp}")
            logger.debug(f"Association established with {association.acceptor.ae_title}")

        except Exception as e:  # (ConnectionError, TimeoutError, RuntimeError) as e:
            logger.error(f"Error establishing association: {e}")
            raise

        return association

    def echo(self, scp: str | DICOMNode, ux_Q: Queue | None = None) -> bool:
        """
        Perform C-ECHO operation to the specified SCP.

        Args:
            scp (str | DICOMNode): The SCP (Service Class Provider) to send the C-ECHO request to.
            ux_Q (Queue | None, optional):
                For asynchronous operation via echo_ex, the optional queue to put the EchoResponse object into. Defaults to None.

        Returns:
            bool: True if the C-ECHO operation is successful, False otherwise.
        """
        logger.info(f"Perform C-ECHO from {self.model.scu} to {scp}")
        echo_association: Association | None = None
        try:
            echo_association = self._connect_to_scp(scp, [self.get_verification_context()])

            status: Dataset = echo_association.send_c_echo()
            if not status:
                raise ConnectionError(_("Connection timed out, was aborted, or received an invalid response"))

            if status.Status == C_SUCCESS:
                logger.info("C-ECHO Success")
                if ux_Q:
                    ux_Q.put(EchoResponse(success=True, error=None))
                echo_association.release()
                return True
            else:
                raise DICOMRuntimeError(f"C-ECHO Failed status: {VERIFICATION_SERVICE_CLASS_STATUS[status.Status][1]}")

        except Exception as e:
            error = f"{(e)}"
            logger.error(error)
            if ux_Q:
                ux_Q.put(EchoResponse(success=False, error=error))
            if echo_association:
                echo_association.release()
            return False

    def echo_ex(self, er: EchoRequest) -> None:
        """
        Executes the echo method in a separate thread.

        Args:
            er (EchoRequest): The EchoRequest object containing the scp and ux_Q parameters.
        """
        threading.Thread(target=self.echo, name="ECHO", args=(er.scp, er.ux_Q)).start()

    def AWS_credentials_valid(self) -> bool:
        """
        Checks if the AWS credentials are valid. The AWS Credentials are set by AWS_authenticate().

        Returns:
            bool: True if the AWS credentials are valid, False otherwise.
        """
        # If AWS credentials are cached and expiration is less than 10 minutes away, return True
        # else clear stale credentials and return False
        if not self._aws_credentials or self._aws_expiration_datetime is None:
            return False
        if self._aws_expiration_datetime - datetime.now(self._aws_expiration_datetime.tzinfo) < timedelta(minutes=10):
            self._aws_credentials.clear()
            self._s3 = None
            return False
        return True

    # Blocking call to AWS to authenticate via boto library:
    def AWS_authenticate(self) -> Any | None:
        """
        Authenticates AWS Cognito User and returns AWS s3 client object
        to use in creation of S3 client in each export thread.

        On error, returns None and sets self_aws_last_error to AuthenticationError with error message or any other exception thrown by boto3.

        Cache credentials and return s3 client object if credential expiration is longer than 10 mins.
        """
        logging.info("AWS_authenticate")
        if self.AWS_credentials_valid():
            logger.info(f"Using cached AWS credentials, Expiration:{self._aws_expiration_datetime}")
            self._aws_last_error = None
            return self._s3

        self._aws_last_error = None

        try:
            cognito_idp_client = boto3.client("cognito-idp", region_name=self.model.aws_cognito.region_name)

            response = cognito_idp_client.initiate_auth(
                ClientId=self.model.aws_cognito.app_client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": self.model.aws_cognito.username,
                    "PASSWORD": self.model.aws_cognito.password,
                },
            )

            if "ChallengeName" in response and response["ChallengeName"] == "NEW_PASSWORD_REQUIRED":
                # New password required, reset using previous password:
                self.model.aws_cognito.password = self.model.aws_cognito.password + "N1-"
                # TODO: allow user to enter new password?
                session = response["Session"]
                response = cognito_idp_client.respond_to_auth_challenge(
                    ClientId=self.model.aws_cognito.app_client_id,
                    ChallengeName="NEW_PASSWORD_REQUIRED",
                    ChallengeResponses={
                        "USERNAME": self.model.aws_cognito.username,
                        "NEW_PASSWORD": self.model.aws_cognito.password,
                    },
                    Session=session,
                )

            if "ChallengeName" in response:
                raise AuthenticationError(_("Unexpected Authorisation Challenge") + f": {response['ChallengeName']}")

            err_msg = None
            if "AuthenticationResult" not in response:
                err_msg = _("Authentication Result & Access Token not in response")
            elif "IdToken" not in response["AuthenticationResult"]:
                err_msg = _("IdToken not in Authentication Result")
            elif "AccessToken" not in response["AuthenticationResult"]:
                err_msg = _("AccessToken Token not in Authentication Result")

            if err_msg:
                logging.error(f"AuthenticationResult not in response: {response}")
                raise AuthenticationError(_("AWS Cognito IDP authorisation failed") + "\n\n" + err_msg)

            cognito_identity_token = response["AuthenticationResult"]["IdToken"]

            # Get the User details and extract the user's sub-directory from User Attributes['sub'] (to follow private prefix)
            response = cognito_idp_client.get_user(AccessToken=response["AuthenticationResult"]["AccessToken"])

            if "UserAttributes" not in response:
                logging.error(f"UserAttributes not in response: {response}")
                raise AuthenticationError(
                    _("AWS Cognito Get User Attributes failed")
                    + "\n\n"
                    + _("UserAttributes Token not in get_user response")
                )

            user_attribute_1 = response["UserAttributes"][0]

            if not user_attribute_1 or "Name" not in user_attribute_1 or user_attribute_1["Name"] != "sub":
                logging.error(f"User Attribute 'sub' not in response: {response}")
                raise AuthenticationError(
                    _("AWS Cognito Get User Attributes failed")
                    + "\n\n"
                    + _("User Attribute 'sub' not in get_user response")
                )

            self._aws_user_directory = user_attribute_1["Value"]

            # Assume the IAM role associated with the Cognito Identity Pool
            cognito_identity_client = boto3.client("cognito-identity", region_name=self.model.aws_cognito.region_name)
            response = cognito_identity_client.get_id(
                IdentityPoolId=self.model.aws_cognito.identity_pool_id,
                AccountId=self.model.aws_cognito.account_id,
                Logins={
                    f"cognito-idp.{self.model.aws_cognito.region_name}.amazonaws.com/{self.model.aws_cognito.user_pool_id}": cognito_identity_token
                },
            )

            if "IdentityId" not in response:
                logging.error(f"IdentityId not in response: {response}")
                raise AuthenticationError(
                    _("AWS Cognito-identity authorisation failed") + "\n\n" + _("IdentityId Token not in response")
                )

            identity_id = response["IdentityId"]

            # Get temporary AWS credentials
            self._aws_credentials = cognito_identity_client.get_credentials_for_identity(
                IdentityId=identity_id,
                Logins={
                    f"cognito-idp.{self.model.aws_cognito.region_name}.amazonaws.com/{self.model.aws_cognito.user_pool_id}": cognito_identity_token
                },
            )

            self._aws_expiration_datetime = self._aws_credentials["Credentials"][
                "Expiration"
            ]  # AWS returns timezone in datetime object

            logger.info(f"AWS Authentication successful, Credentials Expiration:{self._aws_expiration_datetime}")
            self._aws_last_error = None

            self._s3 = boto3.client(
                "s3",
                aws_access_key_id=self._aws_credentials["Credentials"]["AccessKeyId"],
                aws_secret_access_key=self._aws_credentials["Credentials"]["SecretKey"],
                aws_session_token=self._aws_credentials["Credentials"]["SessionToken"],
            )

            return self._s3

        except Exception as e:
            # Latch error message for UX:
            self._aws_last_error = str(e)
            logger.error(self._aws_last_error)
            return None

    def AWS_authenticate_ex(self) -> None:
        """
        Non-blocking call to AWS to authenticate via boto library:
        Starts a new thread to authenticate with AWS.
        """
        threading.Thread(target=self.AWS_authenticate).start()

    def AWS_get_instances(self, anon_pt_id: str, study_uid: str | None = None) -> list[str]:
        """
        Blocking call to get list of objects in S3 bucket
        Retrieves a list of instance UIDs associated with the specified anonymous patient ID and/or study UID (optional).

        Args:
            anon_pt_id (str): The anonymous patient ID.
            study_uid (str, optional): The study UID. Defaults to None.

        Returns:
            list[str]: A list of instance UIDs.

        Raises:
            AuthenticationError: If AWS authentication fails.
            Any other exception thrown by boto3 paginator

        """
        s3 = self.AWS_authenticate()
        if not s3 or not self._aws_user_directory:
            raise AuthenticationError("AWS Authentication failed")

        object_path = Path(
            self.model.aws_cognito.s3_prefix,
            self._aws_user_directory,
            self.model.project_name,
            anon_pt_id,
        )

        if study_uid:
            object_path = object_path.joinpath(study_uid)

        paginator = s3.get_paginator("list_objects_v2")
        instance_uids: list[str] = []

        # Initial request with prefix (if provided)
        pagination_config: dict[str, str] = {
            "Bucket": self.model.aws_cognito.s3_bucket,
            "Prefix": object_path.as_posix(),
        }
        for page in paginator.paginate(**pagination_config):
            if "Contents" in page:
                instance_uids.extend([os.path.splitext(os.path.basename(obj["Key"]))[0] for obj in page["Contents"]])

        return instance_uids

    def send(self, file_paths: list[str], scp_name: str, send_contexts=None) -> int:
        """
        Blocking call: Sends a list of files to a specified SCP (Service Class Provider).

        Args:
            file_paths (list[str]): A list of file paths to be sent.
            scp_name (str): The name of the SCP to send the files to as defined in the model's remote_scps dictionary.
            send_contexts (Optional): The radiology storage contexts to use for sending.
                If not provided, the default radiology storage contexts will be used.

        Returns:
            int: The number of files successfully sent.

        Raises:
            Any Exception raised by pynetdicom or the underlying transport layer.

        TODO: Memory management, handling large datasets and many concurrent sends
        Do not decode dataset, send raw chunks no larger than max PDU of peer
        see: _config.STORE_SEND_CHUNKED_DATASET
        https://pydicom.github.io/pynetdicom/dev/reference/generated/pynetdicom._config.STORE_SEND_CHUNKED_DATASET.html
        * exact matching accepted presentation context required *

        """
        logger.debug(f"Send {len(file_paths)} files to {scp_name}")
        association = None
        files_sent = 0

        if send_contexts is None:
            send_contexts = self.get_radiology_storage_contexts()

        try:
            association = self._connect_to_scp(scp_name, send_contexts)
            for dicom_file_path in file_paths:
                dcm_response: Dataset = association.send_c_store(dataset=dicom_file_path)
                if dcm_response.Status != 0:
                    raise DICOMRuntimeError(f"DICOM Response: {STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}")
                files_sent += 1
        except Exception as e:
            logger.error(f"Send Error: {e}")
            raise

        finally:
            if association:
                association.release()

        return files_sent

    def abort_query(self):
        logger.info("Abort Query")
        self._abort_query = True

    # TODO: to be implemented as helper for refactoring find routines below
    def _query(
        self,
        query_association: Association,
        ds: Dataset,
        ux_Q=None,
        required_attributes: list[str] | None = None,
    ) -> list[Dataset]:
        """
        Executes a query using the provided query_association and dataset.

        Args:
            query_association (Association): The association used for the query.
            ds (Dataset): The dataset containing the query parameters.
            ux_Q (Queue, optional): The queue used for returning results to the UX. Defaults to None.
            required_attributes (list[str] | None, optional): The list of required attributes in the query result. Defaults to None.

        Returns:
            list[Dataset]: The list of query results.

        Raises:
            RuntimeError: If the query is aborted.
            ConnectionError: If the connection times out, is aborted, or receives an invalid response.
            DICOMRuntimeError: If the C-FIND operation fails with status not pending or success.
            Any Exception raised by pynetdicom or the underlying transport layer:
                ConnectionError, TimeoutError, RuntimeError, ValueError, AttributeError
        """
        results = []
        error_msg = ""
        self._abort_query = False
        try:
            # Send C-FIND request
            responses = query_association.send_c_find(
                ds,
                query_model=self._STUDY_ROOT_QR_CLASSES[0],  # Find
            )

            # Process the response(s) received from the peer
            # one response with C_PENDING with identifier and one response with C_SUCCESS and no identifier
            for status, identifier in responses:
                if self._abort_query:
                    raise RuntimeError("Query aborted")

                if not status:
                    raise ConnectionError("Connection timed out, was aborted, or received an invalid response")
                if status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                ):
                    logger.error(f"C-FIND failure, status: {hex(status.Status)}")
                    raise DICOMRuntimeError(f"C-FIND Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status][1]}")

                if identifier:
                    if required_attributes:
                        missing_attributes = self._missing_attributes(required_attributes, identifier)
                        if missing_attributes != []:
                            logger.error(f"Query result is missing required attributes: {missing_attributes}")
                            logger.error(f"\n{identifier}")
                            continue

                    self._strip_query_result_fields(identifier)

                    results.append(identifier)

                    # Only return identifiers back to UX
                    # do not return (C_SUCCESS, None) as in find()
                    if ux_Q:
                        ux_Q.put(FindStudyResponse(status, identifier))

            # Signal success to UX once full list of accession numbers has been processed
            if ux_Q:
                logger.info("Find Accession Numbers complete")
                ds = Dataset()
                ds.Status = C_SUCCESS
                ux_Q.put(FindStudyResponse(ds, None))

        except (
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
            AttributeError,
            DICOMRuntimeError,
        ) as e:
            # Reflect status dataset back to UX client to provide find error detail
            error_msg = str(e)  # latch exception error msg
            logger.error(error_msg)
            if ux_Q:
                ds = Dataset()
                ds.Status = C_FAILURE
                ds.ErrorComment = error_msg
                ux_Q.put(FindStudyResponse(ds, None))

        finally:
            if query_association:
                query_association.release()

        return results

    def find_studies(
        self,
        scp_name: str,
        name: str,
        id: str,
        acc_no: str,
        study_date: str,
        modality: str,
        ux_Q=None,
        verify_attributes=True,
    ) -> list[Dataset] | None:
        """
        Blocking: Query remote server for studies matching the given query parameters:

        Args:
            scp_name (str): The name of the SCP (Service Class Provider) to connect to from the ProjectModel's remote_scps dictionary.
            name (str): The name of the patient.
            id (str): The ID of the patient.
            acc_no (str): The accession number of the study.
            study_date (str): The date of the study.
            modality (str): The modality of the study.
            ux_Q (Queue, optional): The queue to put the find study responses in. Defaults to None.
            verify_attributes (bool, optional): Flag to indicate whether to verify the attributes of the study results. Defaults to True.

        Returns:
            list[Dataset] | None: A list of study results as Dataset objects, or None if no results are found
            On any error: the error message is captured and reflected back to the UX client via a pydicom status dataset within FindStudyResponse placed in ux_Q.

        """
        try:
            if scp_name not in self.model.remote_scps:
                raise ConnectionError(f"Remote SCP {scp_name} not found in ProjectModel remote_scps dictionary")

            scp = self.model.remote_scps[scp_name]
            logger.info(f"C-FIND[study] to {scp} Study Level Query: {name}, {id}, {acc_no}, {study_date}, {modality}")

            # Phase 1: Study Level Query
            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.AccessionNumber = acc_no
            ds.StudyDate = study_date
            ds.ModalitiesInStudy = modality
            ds.SOPClassesInStudy = ""
            ds.PatientName = name
            ds.PatientID = id
            ds.PatientSex = ""
            ds.PatientBirthDate = ""

            ds.NumberOfStudyRelatedSeries = ""
            ds.NumberOfStudyRelatedInstances = ""
            ds.StudyDescription = ""
            ds.StudyInstanceUID = ""

            results = []
            error_msg = ""
            query_association = None
            self._abort_query = False

            query_association = self._connect_to_scp(scp_name, self.get_study_root_find_contexts())

            study_responses = query_association.send_c_find(
                ds,
                query_model=self._STUDY_ROOT_QR_CLASSES[0],
            )

            for study_status, study_result in study_responses:
                if self._abort_query:
                    raise RuntimeError("Query aborted")

                # Timeouts (Network & DIMSE) are reflected by status being None:
                if not study_status:
                    raise ConnectionError(
                        "Connection timed out (DIMSE or IDLE), was aborted, or received an invalid response"
                    )

                if study_status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                ):
                    logger.error(f"C-FIND Study failure, status: {hex(study_status.Status)}")
                    raise DICOMRuntimeError(f"C-FIND Study Failed: {QR_FIND_SERVICE_CLASS_STATUS[study_status.Status]}")

                if study_status.Status == C_SUCCESS:
                    logger.info("C-FIND study query success")

                if study_result:
                    if verify_attributes:
                        missing_study_attributes = self._missing_attributes(
                            self._required_attributes_study_query, study_result
                        )
                        if missing_study_attributes != []:
                            logger.error(f"Query result is missing required attributes: {missing_study_attributes}")
                            logger.error(f"\n{study_result}")
                            continue

                    self._strip_query_result_fields(study_result)

                    results.append(study_result)

                if ux_Q:
                    ux_Q.put(FindStudyResponse(study_status, study_result))

        except (
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
            AttributeError,
            DICOMRuntimeError,
        ) as e:
            # Reflect status dataset back to UX client to provide find error detail
            error_msg = str(e)  # latch exception error msg
            logger.error(error_msg)
            if ux_Q:
                ds = Dataset()
                ds.Status = C_FAILURE
                ds.ErrorComment = error_msg
                ux_Q.put(FindStudyResponse(ds, None))

        finally:
            if query_association:
                if self._abort_query:
                    query_association.abort()
                else:
                    query_association.release()

        if len(results) == 0:
            logger.info("No query results found")
        else:
            logger.info(f"{len(results)} Query results found")
            for result in results:
                logger.debug(
                    # f"{getattr(result, 'PatientName', 'N/A')}, "
                    # f"{getattr(result, 'PatientID', 'N/A')}, "
                    # f"{getattr(result, 'StudyDate', 'N/A')}, "
                    # f"{getattr(result, 'AccessionNumber', 'N/A')}, "
                    # f"{getattr(result, 'StudyInstanceUID', 'N/A')} "
                    f"{getattr(result, 'StudyDescription', 'N/A')}, "
                    f"{getattr(result, 'ModalitiesInStudy', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedSeries', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedInstances', 'N/A')}, "
                )

        return results

    def find_studies_via_acc_nos(
        self,
        scp_name: str,
        acc_no_list: list,
        ux_Q=None,
        verify_attributes=True,
    ) -> list[Dataset] | None:
        """
        Blocking: Query remote server for studies corresponding to list of accession numbers

        Args:
            scp_name (str): The name of the SCP (Service Class Provider) to connect to.
            acc_no_list (list): A list of accession numbers to search for.
            ux_Q (Queue, optional): A queue to send intermediate results to the user interface. Defaults to None.
            verify_attributes (bool, optional): Flag to indicate whether to verify the attributes of the query results. Defaults to True.

        Returns:
            list[Dataset] | None: A list of Dataset objects representing the query results, or None if no results were found.
            If PACS does an implicit wildcard search remove these responses, only accept exact AccessionNumber matches
            On any error: the error message is captured and reflected back to the UX client via a pydicom status dataset within FindStudyResponse placed in ux_Q.
        """
        try:
            if scp_name not in self.model.remote_scps:
                raise ConnectionError(f"Remote SCP {scp_name} not found")

            scp = self.model.remote_scps[scp_name]
            logger.info(f"C-FIND to {scp} Accession Query: {len(acc_no_list)} accession numbers...")
            acc_no_list = list(set(acc_no_list))  # remove duplicates
            logger.debug(f"{acc_no_list}")

            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.ModalitiesInStudy = ""
            ds.NumberOfStudyRelatedSeries = ""
            ds.NumberOfStudyRelatedInstances = ""
            ds.StudyDescription = ""
            ds.StudyInstanceUID = ""
            ds.PatientName = ""
            ds.PatientID = ""
            ds.StudyDate = ""

            results = []
            error_msg = ""
            query_association = None
            self._abort_query = False

            query_association = self._connect_to_scp(scp_name, self.get_study_root_find_contexts())

            for acc_no in acc_no_list:
                if self._abort_query:
                    raise RuntimeError("Query aborted")

                if acc_no == "":
                    continue

                ds.AccessionNumber = acc_no

                responses = query_association.send_c_find(
                    ds,
                    query_model=self._STUDY_ROOT_QR_CLASSES[0],  # Find
                )

                # Process the response(s) received from the peer
                # one response with C_PENDING with identifier and one response with C_SUCCESS and no identifier
                for status, identifier in responses:
                    if not status:
                        raise ConnectionError("Connection timed out, was aborted, or received an invalid response")
                    if status.Status not in (
                        C_SUCCESS,
                        C_PENDING_A,
                        C_PENDING_B,
                    ):
                        logger.error(f"C-FIND failure, status: {hex(status.Status)}")
                        raise DICOMRuntimeError(f"C-FIND Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status][1]}")

                    if identifier:
                        if verify_attributes:
                            missing_study_attributes = self._missing_attributes(
                                self._required_attributes_study_query, identifier
                            )
                            if missing_study_attributes != []:
                                logger.error(f"Query result is missing required attributes: {missing_study_attributes}")
                                logger.error(f"\n{identifier}")
                                continue

                        # If PACS does an implicit wildcard search remove these responses, only accept exact matches:
                        if identifier.AccessionNumber != acc_no:
                            logger.error(
                                f"Remote Server Accession Number partial match: AccessionNumber {identifier.AccessionNumber} does not match request: {acc_no}"
                            )
                            continue

                        self._strip_query_result_fields(identifier)

                        results.append(identifier)

                        # Only return identifiers back to UX
                        # do not return (C_SUCCESS, None) as in find()
                        if ux_Q:
                            ux_Q.put(FindStudyResponse(status, identifier))

            # Signal success to UX once full list of accession numbers has been processed
            if ux_Q:
                logger.info("Find Accession Numbers complete")
                ds = Dataset()
                ds.Status = C_SUCCESS
                ux_Q.put(FindStudyResponse(ds, None))

        except (
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
            AttributeError,
            DICOMRuntimeError,
        ) as e:
            # Reflect status dataset back to UX client to provide find error detail
            error_msg = str(e)  # latch exception error msg
            logger.error(error_msg)
            if ux_Q:
                ds = Dataset()
                ds.Status = C_FAILURE
                ds.ErrorComment = error_msg
                ux_Q.put(FindStudyResponse(ds, None))

        finally:
            if query_association:
                query_association.release()

        if len(results) == 0:
            logger.info("No query results found")
        else:
            logger.info(f"{len(results)} Query results found")
            for result in results:
                logger.debug(
                    f"{getattr(result, 'PatientName', 'N/A')}, "
                    f"{getattr(result, 'PatientID', 'N/A')}, "
                    f"{getattr(result, 'StudyDate', 'N/A')}, "
                    f"{getattr(result, 'StudyDescription', 'N/A')}, "
                    f"{getattr(result, 'AccessionNumber', 'N/A')}, "
                    f"{getattr(result, 'ModalitiesInStudy', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedSeries', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedInstances', 'N/A')}, "
                    f"{getattr(result, 'StudyInstanceUID', 'N/A')} "
                )

        return results

    def find_ex(self, fr: FindStudyRequest) -> None:
        """
        Non-blocking: Find studies based on the provided search parameters or accession numbers.

        Args:
            fr (FindStudyRequest): The FindStudyRequest object containing the search parameters or just accession numbers in the acc_no field.

        Returns:
            None
        """
        if isinstance(fr.acc_no, list):
            logger.info("Find studies from list of accession numbers...")
            # Due to client removing numbers as they are found, make a copy of the list:
            acc_no_list = fr.acc_no.copy()
            fr.acc_no = acc_no_list
            threading.Thread(
                target=self.find_studies_via_acc_nos,
                name="FindStudiesAccNos",
                args=(
                    fr.scp_name,
                    fr.acc_no,
                    fr.ux_Q,
                ),
                daemon=True,  # daemon threads are abruptly stopped at shutdown
            ).start()
        else:
            logger.info("Find studies from search parameters...")
            threading.Thread(
                target=self.find_studies,
                name="FindStudies",
                args=(
                    fr.scp_name,
                    fr.name,
                    fr.id,
                    fr.acc_no,
                    fr.study_date,
                    fr.modality,
                    fr.ux_Q,
                ),
                daemon=True,  # daemon threads are abruptly stopped at shutdown
            ).start()

    def get_study_uid_hierarchy(
        self,
        scp_name: str,
        study_uid: str,
        patient_id: str,
        instance_level: bool = False,
    ) -> Tuple[str | None, StudyUIDHierarchy]:
        """
        Blocking: Query remote DICOM server for study/series/instance uid hierarchy (required for iterative move) for the specified Study UID.
        Perform a SERIES level query first to get the list of Series UIDs for the Study UID.
        IF the remote SCP does not respond with NumberOfSeriesRelatedInstances and instance_level is False, raise an exception & catch error message.
        IF instance_level is True, perform an INSTANCE level query for each Series UID to get the list of Instance UIDs.

        Args:
            scp_name (str): The name of the SCP.
            study_uid (str): The Study UID.
            patient_id (str): The Patient ID. (not used for query, copied to StudyUIDHierarchy object)
            instance_level (bool, optional): Flag indicating whether to retrieve instance-level information. Defaults to False.

        Returns:
            Tuple[str | None, StudyUIDHierarchy]: A tuple containing the error message (if any) and the StudyUIDHierarchy object.
            The error message reflects any exception caught during the query process.
        """
        logger.info(
            f"Get StudyUIDHierarchy from {scp_name} for StudyUID={study_uid}, PatientID={patient_id} instance_level={instance_level}"
        )

        study_uid_hierarchy = StudyUIDHierarchy(uid=study_uid, ptid=patient_id, series={})
        error_msg = None

        scp = self.model.remote_scps[scp_name]

        query_association: Association | None = None

        try:
            # 1. Connect to SCP:
            query_association = self._connect_to_scp(scp_name, self.get_study_root_find_contexts())

            # 2. Get list of Series UIDs for the Study UID:
            logger.info(f"C-FIND[series] to {scp} study_uid={study_uid}")
            ds = Dataset()
            ds.QueryRetrieveLevel = "SERIES"
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = ""
            ds.SeriesNumber = ""
            ds.SeriesDescription = ""
            ds.Modality = ""
            ds.SOPClassUID = ""
            ds.NumberOfSeriesRelatedInstances = ""

            responses = query_association.send_c_find(
                ds,
                query_model=self._STUDY_ROOT_QR_CLASSES[0],  # Find
            )

            for status, identifier in responses:
                if self._abort_query:
                    raise RuntimeError("Query aborted")
                if not status:
                    raise ConnectionError("Connection timed out, was aborted, or received an invalid response")
                if status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B):
                    logger.error(f"C-FIND[series] failure, status: {hex(status.Status)}")
                    raise DICOMRuntimeError(f"C-FIND[series] Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status]}")

                if status.Status == C_SUCCESS:
                    logger.info("C-FIND[series] query success")
                if identifier:
                    missing_attributes = self._missing_attributes(self._required_attributes_series_query, identifier)
                    if missing_attributes:
                        logger.error(
                            f"Skip Series for Study:{study_uid}, Series Level Query result is missing required attributes: {missing_attributes}"
                        )
                        logger.error(f"\n{identifier}")
                        continue
                    if identifier.StudyInstanceUID != study_uid:
                        logger.error(
                            f"Skip Series:{identifier.SeriesInstanceUID} Mismatch: StudyUID:{study_uid}<>{identifier.StudyInstanceUID}"
                        )
                        continue
                    if identifier.Modality not in self.model.modalities:
                        logger.info(
                            f"Skip Series[Modality={identifier.Modality}]:{identifier.SeriesInstanceUID} with mismatched modality"
                        )
                        continue
                    # Some PACS may provide SOPClassUID at series & study level if they contain a single class
                    # ALL PACS should provide SOPClassUID at instance level
                    sop_class_uid = identifier.get("SOPClassUID", None)
                    if sop_class_uid and sop_class_uid not in self.model.storage_classes:
                        logger.info(
                            f"Skip Series[SOPClassUID={identifier.SOPClassUID}]:{identifier.SeriesInstanceUID} with mismatched sop_class_uid"
                        )
                        continue

                    # New SeriesUIDHierarchy:
                    series_descr = identifier.SeriesDescription if hasattr(identifier, "SeriesDescription") else "?"
                    instance_count = identifier.get("NumberOfSeriesRelatedInstances", 0)
                    if not instance_level and not instance_count:
                        raise DICOMRuntimeError(
                            _("Unable to retrieve UID Hierarchy for reliable import operation via DICOM C-MOVE.")
                            + f" {scp_name} "
                            + _("Server")
                            + " "
                            + _("did not return the number of instances in a series.")
                            + " "
                            + _(
                                "Standard DICOM field (0020,1209) NumberOfSeriesRelatedInstances is missing in the query response."
                            )
                        )

                    # IF this Series already exists in the hierarchy,
                    # assume the scp is sending a query response for each instance and increment the series instance count:
                    # TODO: is this acceptable? alternatively could force instance level query below
                    if identifier.SeriesInstanceUID in study_uid_hierarchy.series:
                        if instance_count != 1:
                            raise DICOMRuntimeError(
                                f"SCP Series Query Response for series:{identifier.SeriesInstanceUID}, inconsistent NumberOfSeriesRelatedInstances: {instance_count}"
                            )
                        study_uid_hierarchy.series[identifier.SeriesInstanceUID].instance_count += 1
                        logger.info(
                            f"Add instance to existing series: {identifier.SeriesInstanceUID} i{study_uid_hierarchy.series[identifier.SeriesInstanceUID].instance_count}"
                        )
                    else:
                        study_uid_hierarchy.series[identifier.SeriesInstanceUID] = SeriesUIDHierarchy(
                            uid=identifier.SeriesInstanceUID,
                            number=identifier.get("SeriesNumber", None),  # TODO: should this be auto-generated if None?
                            modality=identifier.Modality,
                            sop_class_uid=identifier.SOPClassUID,
                            description=series_descr,
                            instance_count=instance_count,
                            instances={},
                        )
                        logger.info(
                            f"New Series[Modality={identifier.Modality},SOPClassUID={identifier.SOPClassUID}]: {series_descr}/{identifier.SeriesInstanceUID}/{identifier.SeriesNumber} | {instance_count}"
                        )

            logger.info(f"StudyUID={study_uid}, {len(study_uid_hierarchy.series)} Series found")
            if len(study_uid_hierarchy.series) == 0:
                raise DICOMRuntimeError("C-FIND[series] Failed: No series found in study matching project modalities")

            if instance_level:
                # 3. If Instance level required: Get list of Instance UIDs for each Series UID:
                for series in study_uid_hierarchy.series.values():
                    ds = Dataset()
                    ds.QueryRetrieveLevel = "IMAGE"
                    ds.StudyInstanceUID = study_uid
                    ds.SeriesInstanceUID = series.uid
                    ds.SOPInstanceUID = ""
                    ds.InstanceNumber = ""

                    responses = query_association.send_c_find(
                        ds,
                        query_model=self._STUDY_ROOT_QR_CLASSES[0],  # Find
                    )
                    for status, identifier in responses:
                        if self._abort_query:
                            raise RuntimeError("Query aborted")
                        if not status:
                            raise ConnectionError("Connection timed out, was aborted, or received an invalid response")
                        if status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B):
                            logger.error(f"C-FIND[instance] failure, status: {hex(status.Status)}")
                            raise DICOMRuntimeError(
                                f"C-FIND[instance] Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status]}"
                            )

                        if status.Status == C_SUCCESS:
                            logger.info("C-FIND[instance] query success")

                        if identifier:
                            missing_attributes = self._missing_attributes(
                                self._required_attributes_instance_query, identifier
                            )
                            if missing_attributes:
                                logger.error(
                                    f"Skip Instance for Series:{series.uid}, Instance Level Query result is missing required attributes: {missing_attributes}"
                                )
                                logger.error(f"\n{identifier}")
                                continue
                            if identifier.StudyInstanceUID == study_uid and identifier.SeriesInstanceUID == series.uid:
                                series.instances[identifier.SOPInstanceUID] = InstanceUIDHierarchy(
                                    uid=identifier.SOPInstanceUID,
                                    number=identifier.InstanceNumber if hasattr(identifier, "InstanceNumber") else None,
                                )
                            else:
                                logger.error(
                                    f"Mismatch: Study:{study_uid}<>{identifier.StudyInstanceUID} and/or Series:{series.uid}<>{identifier.SeriesInstanceUID}"
                                )

                    logger.info(f"SeriesUID={series.uid}: {len(series.instances)} Instance UIDs found")
                    # Overwrite instance_count with actual instance count:
                    series.instance_count = len(series.instances)

            # Initialise Study pending instances to total instance count:
            study_uid_hierarchy.pending_instances = study_uid_hierarchy.get_number_of_instances()

        except Exception as e:
            error_msg = str(e)  # latch exception error msg
            study_uid_hierarchy.last_error_msg = error_msg
            logger.error(error_msg)

        finally:
            if query_association:
                if self._abort_query:
                    query_association.abort()
                else:
                    query_association.release()

        return error_msg, study_uid_hierarchy

    def get_study_uid_hierarchies(self, scp_name: str, studies: List[StudyUIDHierarchy], instance_level: bool) -> None:
        """
        Blocking: Get List of StudyUIDHierarchies based on value of study_uid within each element of list of StudyUIDHierarchy objects.
        last_error_msg of each StudyUIDHierarch object is set by get_study_uid_hierarchy()

        TODO: Optimization: make this multi-threaded using futures & thread executor as for manage_move

        Args:
            scp_name (str): The name of the SCP.
            studies (List[StudyUIDHierarchy]): A list of StudyUIDHierarchy objects representing the studies.
            instance_level (bool): A flag indicating whether to retrieve instance-level information.

        Returns:
            None
        """
        logger.info(f"Get StudyUIDHierarchies for {len(studies)} studies, instance_level: {instance_level}")
        self._abort_query = False
        for study in studies:
            if self._abort_query:
                logger.info("GetStudyUIDHierarchies Aborted")
                break
            error_msg, study_uid_hierarchy = self.get_study_uid_hierarchy(
                scp_name, study.uid, study.ptid, instance_level
            )
            study.series = study_uid_hierarchy.series
            study.last_error_msg = error_msg
            # Initialise Study pending instances to total instance count:
            study.pending_instances = study_uid_hierarchy.pending_instances

        logger.info("Get StudyUIDHierarchies done")

    def get_study_uid_hierarchies_ex(
        self, scp_name: str, studies: List[StudyUIDHierarchy], instance_level: bool
    ) -> None:
        """
        Non-blocking Get List of StudyUIDHierarchies

        Args:
            scp_name (str): The name of the SCP (Service Class Provider).
            studies (List[StudyUIDHierarchy]): A list of StudyUIDHierarchy objects representing the studies.
            instance_level (bool): Indicates whether to retrieve instance-level hierarchies.

        Returns:
            None
        """
        threading.Thread(
            target=self.get_study_uid_hierarchies,
            name="GetStudyUIDHierarchies",
            args=(scp_name, studies, instance_level),
            daemon=True,  # daemon threads are abruptly stopped at shutdown
        ).start()

    def get_number_of_pending_instances(self, study: StudyUIDHierarchy) -> int:
        """
        Calculates the number of pending instances for a given study by subtracting the number of instance in StudyUIDHierarchy
        from the total number of instances stored in the AnonymizerModel. (not from reading the file system)

        Args:
            study (StudyUIDHierarchy): The study for which to calculate the number of pending instances.

        Returns:
            int: The number of pending instances for the study.
        """
        return study.get_number_of_instances() - self.anonymizer.model.get_stored_instance_count(study_uid=study.uid)

    # TODO: Refactor: create version of move_study with move_level parameter

    def _move_study_at_study_level(self, scp_name: str, dest_scp_ae: str, study: StudyUIDHierarchy) -> str | None:
        """
        Move a study at the study level from one SCP to another.

        Args:
            scp_name (str): The name of the source SCP.
            dest_scp_ae (str): The AE title of the move destination SCP.
            study (StudyUIDHierarchy): The hierarchy of the study to be moved, defined only by Study UID.

        Returns:
            str | None: An error message if any exception or error occurs during the move, otherwise None.
            Status updates are reflected in study_uid_hierarchy provided.
        """
        logger.info(f"C-MOVE@Study[{study.uid}] scp:{scp_name} move to:{dest_scp_ae}")

        move_association = None
        error_msg = None

        if study is None or len(study.series) == 0:
            error_msg = "No Series in Study"
            return error_msg

        target_count = study.get_number_of_instances()
        if target_count == 0:
            error_msg = "No Instances in Study"
            return error_msg

        study.pending_instances = self.anonymizer.model.get_pending_instance_count(study.uid, target_count)
        if study.pending_instances == 0:
            error_msg = "All Instances already imported"
            return error_msg

        try:
            # 1. Establish Association for MOVE request:
            move_association = self._connect_to_scp(scp_name, self.get_study_root_move_contexts())

            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.StudyInstanceUID = study.uid

            logger.info(f"C-MOVE@Study[{study.uid}] Request: InstanceCount={study.get_number_of_instances()}")

            # 2. Use the C-MOVE service to request that the remote SCP move the Study to local storage scp:
            # Send Move Request for Study UID & wait for Move Responses for each instance in study:
            responses = move_association.send_c_move(
                dataset=ds,
                move_aet=dest_scp_ae,
                query_model=self._STUDY_ROOT_QR_CLASSES[1],
                priority=1,  # High priority
            )

            # Process the responses received from the remote scp:
            # * Note * pynetdicom docs for send_c_move:
            # If the status category is 'Pending' or 'Success' then yields None.
            # If the status category is 'Warning', 'Failure' or 'Cancel' then yields a ~pydicom.dataset.Dataset which should contain
            # an (0008,0058) *Failed SOP Instance UID List* element, however as this comes from the peer this is not guaranteed
            # and may instead be an empty ~pydicom.dataset.Dataset.
            for status, identifier in responses:
                time.sleep(0.1)
                if self._abort_move:
                    raise (DICOMRuntimeError(f"C-MOVE@Study[{study.uid}] move study aborted"))

                if not status:
                    raise ConnectionError(_("Connection timed out or aborted moving study_uid") + f": {study.uid}")

                if status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                    C_WARNING,
                ):
                    raise DICOMRuntimeError(
                        f"C-MOVE@Study[{study.uid}] failure, status:{hex(status.Status).upper()}: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                    )

                if status.Status == C_SUCCESS:
                    logger.info(f"C-MOVE@Study[{study.uid}] Study Request SUCCESS")

                # Update Move stats from status:
                study.update_move_stats(status)

                # Update Pending Instances count from AnonymizerModel, relevant for Syncrhonous Move:
                study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                    study.uid, study.get_number_of_instances()
                )

                if identifier:
                    logger.info(f"C-MOVE@Study[{study.uid}] Response identifier: {identifier}")

            logger.info(f"C-MOVE@Study Request for Study COMPLETE: StudyUIDHierachy:\n{study}")

            # 3. Wait for ALL instances of Study to be Imported by verifying with AnonymizerModel
            #    Timeout if a pending instance is not received within NetworkTimeout
            #    or abort on user signal:
            prev_pending_instances = study.pending_instances
            import_timer = int(self.model.network_timeouts.network)
            while import_timer:
                if self._abort_move:
                    raise DICOMRuntimeError(f"C-MOVE@Study[{study.uid}] aborted")

                study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                    study.uid, study.get_number_of_instances()
                )

                if study.pending_instances == 0:
                    logger.info(f"C-MOVE@Study[{study.uid}] ALL Instances IMPORTED")
                    break

                # Reset timer if pending instances count changes:
                if study.pending_instances != prev_pending_instances:
                    prev_pending_instances = study.pending_instances
                    import_timer = int(self.model.network_timeouts.network)

                import_timer -= 1
                time.sleep(1)

            # 4. Raise Error if Timeout
            if import_timer == 0:
                raise TimeoutError(f"C-MOVE@Study[{study.uid}] Import Timeout")

        except Exception as e:
            error_msg = str(e)  # latch exception error msg
            study.last_error_msg = error_msg
            logger.error(error_msg)

        finally:
            # Release the association
            if move_association:
                if self._abort_move:
                    move_association.abort()
                else:
                    move_association.release()
        return error_msg

    def _move_study_at_series_level(self, scp_name: str, dest_scp_ae: str, study: StudyUIDHierarchy) -> str | None:
        """
        Blocking: Moves a study at the series level from one SCP to another.

        Args:
            scp_name (str): The name of the source SCP.
            dest_scp_ae (str): The AE title of the move destination SCP.
            study (StudyUIDHierarchy): The hierarchy of the study to be moved defined down to the Series level

        Returns:
            str | None: An error message if any exception or error occurs during the move, otherwise None.
            Status updates reflected in study_uid_hierarchy provided
        """
        logger.info(f"C-MOVE@Series[{study.uid}] scp:{scp_name} move to:{dest_scp_ae} ")

        move_association = None
        error_msg = None

        if study is None or len(study.series) == 0:
            error_msg = "No Series in Study"
            return error_msg

        target_count = study.get_number_of_instances()
        if target_count == 0:
            error_msg = "No Instances in Study"
            return error_msg

        study.pending_instances = self.anonymizer.model.get_pending_instance_count(study.uid, target_count)
        if study.pending_instances == 0:
            error_msg = "All Instances already imported"
            return error_msg

        try:
            for series in study.series.values():
                # 0.1 Skip Series with no instances:
                if series.instance_count == 0:
                    logger.info(f"C-MOVE@Series Skip Series[{study.uid}/{series.uid}] InstanceCount=0")
                    continue

                # 0.2 Skip Series if instances all imported:
                if self.anonymizer.model.series_complete(series.uid, series.instance_count):
                    logger.info(f"C-MOVE@Series Skip Series[{study.uid}/{series.uid}] all instances imported")
                    continue

                # 1. Establish Association for Series MOVE request:
                move_association = self._connect_to_scp(scp_name, self.get_study_root_move_contexts())

                # 2. Move Request for each Series UID & wait for Move Response:
                study_pending_instances_before_series_move = study.pending_instances

                ds = Dataset()
                ds.QueryRetrieveLevel = "SERIES"
                ds.StudyInstanceUID = study.uid
                ds.SeriesInstanceUID = series.uid
                if series.number:
                    ds.SeriesNumber = series.number

                logger.info(
                    f"C-MOVE@Series[{study.uid}/{series.uid}] Request: Modality={series.modality} SOPClassUID={series.sop_class_uid} InstanceCount={series.instance_count}"
                )

                responses = move_association.send_c_move(
                    dataset=ds,
                    move_aet=dest_scp_ae,
                    query_model=self._STUDY_ROOT_QR_CLASSES[1],  # Move
                    priority=1,  # High priority
                )

                # Process the responses received from the remote scp:
                # * Note * pynetdicom docs for send_c_move:
                # If the status category is 'Pending' or 'Success' then yields None.
                # If the status category is 'Warning', 'Failure' or 'Cancel' then yields a ~pydicom.dataset.Dataset which should contain
                # an (0008,0058) *Failed SOP Instance UID List* element, however as this comes from the peer this is not guaranteed
                # and may instead be an empty ~pydicom.dataset.Dataset.
                for status, __ in responses:
                    if self._abort_move:
                        raise (DICOMRuntimeError(f"C-MOVE@Series[{study.uid}] study move aborted"))

                    if not status:
                        raise (
                            DICOMRuntimeError(
                                f"C-MOVE@Series[{study.uid}] Connection Error, no status returned from scp"
                            )
                        )

                    if status.Status not in (
                        C_SUCCESS,
                        C_PENDING_A,
                        C_PENDING_B,
                        C_WARNING,
                    ):
                        raise DICOMRuntimeError(
                            f"C-MOVE@Series[{study.uid}/{series.uid}] failure, status:{hex(status.Status).upper()}: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                        )

                    if status.Status == C_SUCCESS:
                        logger.info(
                            f"C-MOVE@Series[{study.uid}/{series.uid}] Series Request SUCCESS SeriesNumber:{series.number}"
                        )

                    # Update Move stats from status:
                    series.update_move_stats(status)

                    # Update Pending Instances count from AnonymizerModel, relevant for Syncrhonous Move:
                    study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                        study.uid, study.get_number_of_instances()
                    )

                # 3. Wait for ALL instances of Series to be Imported by verifying with AnonymizerModel
                #    Timeout if a pending instance is not received within NetworkTimeout
                #    or abort on user signal:
                prev_pending_instances = study.pending_instances
                import_timer = int(self.model.network_timeouts.network)
                while import_timer:
                    if self._abort_move:
                        raise DICOMRuntimeError(f"C-MOVE@Series[{study.uid}] aborted")

                    study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                        study.uid, study.get_number_of_instances()
                    )

                    if study_pending_instances_before_series_move - study.pending_instances >= series.instance_count:
                        logger.info(f"C-MOVE@Series[{study.uid}/{series.uid}] ALL Instances IMPORTED for Series")
                        break

                    # Reset timer if pending instances count changes:
                    if study.pending_instances != prev_pending_instances:
                        prev_pending_instances = study.pending_instances
                        import_timer = int(self.model.network_timeouts.network)

                    import_timer -= 1
                    time.sleep(1)

                # 4. Raise Error if Timeout
                if import_timer == 0:
                    raise TimeoutError(f"C-MOVE@Series[{study.uid}/{series.uid}] Import Timeout")

                move_association.release()

            logger.info(f"C-MOVE@Series ALL Series Requests for Study COMPLETE: StudyUIDHierachy:\n{study}")

        except Exception as e:
            error_msg = str(e)  # latch exception error msg
            study.last_error_msg = error_msg
            logger.error(error_msg)

        finally:
            # Release the association:
            if move_association:
                if self._abort_move:
                    move_association.abort()
                else:
                    move_association.release()
        return error_msg

    def _move_study_at_instance_level(self, scp_name: str, dest_scp_ae: str, study: StudyUIDHierarchy) -> str | None:
        """
        Blocking: Moves a study at the instance level from one SCP to another.

        Args:
            scp_name (str): The name of the source SCP.
            dest_scp_ae (str): The AE title of the destination SCP.
            study (StudyUIDHierarchy): The study to be moved with the hierarchy defined down to instance level.

        Returns:
            str | None: An error message if any exception or error occurs during the move, otherwise None.
            Status updates are reflected in the provided study_uid_hierarchy
        """
        logger.info(f"C-MOVE@Instance[{study.uid}] scp:{scp_name} move to: {dest_scp_ae} ")

        move_association = None
        error_msg = None

        if study is None or len(study.series) == 0:
            error_msg = "No Series in Study"
            return error_msg

        if study.get_number_of_instances() == 0:
            error_msg = "No Instances in Study"
            return error_msg

        try:
            # 1. Establish Association for MOVE request:
            move_association = self._connect_to_scp(scp_name, self.get_study_root_move_contexts())

            # 2. Move Request for each Instance UID & wait for Move Response:
            for series in study.series.values():
                if len(series.instances) == 0:
                    logger.error(f"No instances in Series: {series.uid} skipping")
                    continue

                for instance in series.instances.values():
                    # Skip already imported instances
                    if self.anonymizer.model.instance_received(instance.uid):
                        logger.debug(f"Instance already imported: {instance.uid}, skipping")
                        continue

                    ds = Dataset()
                    ds.QueryRetrieveLevel = "IMAGE"
                    ds.StudyInstanceUID = study.uid
                    ds.SeriesInstanceUID = series.uid
                    ds.SOPInstanceUID = instance.uid
                    if instance.number:
                        ds.InstanceNumber = instance.number

                    logger.info(
                        f"C-MOVE@Instance[{study.uid}] request SeriesUID:{series.uid} InstanceUID:{instance.uid}"
                    )
                    logger.debug(ds)

                    responses = move_association.send_c_move(
                        dataset=ds,
                        move_aet=dest_scp_ae,
                        query_model=self._STUDY_ROOT_QR_CLASSES[1],  # Move
                        priority=1,  # High priority
                    )

                    # Process the responses received from the remote scp:
                    # * Note * pynetdicom docs for send_c_move:
                    # If the status category is 'Pending' or 'Success' then yields None.
                    # If the status category is 'Warning', 'Failure' or 'Cancel' then yields a ~pydicom.dataset.Dataset which should contain
                    # an (0008,0058) *Failed SOP Instance UID List* element, however as this comes from the peer this is not guaranteed
                    # and may instead be an empty ~pydicom.dataset.Dataset.
                    for status, __ in responses:
                        time.sleep(0.1)
                        if self._abort_move:
                            raise (DICOMRuntimeError(f"C-MOVE@Instance[{study.uid}] aborted"))

                        logger.debug(f"STATUS: {status}")

                        if not status:
                            raise DICOMRuntimeError(
                                f"C-MOVE[{study.uid}] Connection Error, no status returned from scp"
                            )

                        if status.Status not in (
                            C_SUCCESS,
                            C_PENDING_A,
                            C_PENDING_B,
                            C_WARNING,
                        ):
                            raise DICOMRuntimeError(
                                f"C-MOVE@Instance[{study.uid}/{series.uid}/{instance.uid}] failure, status:{hex(status.Status)}: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                            )

                        if status.Status == C_SUCCESS:
                            logger.info(
                                f"C-MOVE@Instance[{study.uid}/{series.uid}/{instance.uid}] Instance Request SUCCESS"
                            )

                        # Update Move stats from status:
                        series.update_move_stats_instance_level(status)

                        # Update Pending Instances count from AnonymizerModel, relevant for Syncrhonous Move:
                        study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                            study.uid, study.get_number_of_instances()
                        )

                logger.info(f"C-MOVE@Instance[{study.uid}/{series.uid}] ALL Instance Requests for Series COMPLETE")

            logger.info(f"C-MOVE@Instance[{study.uid}] ALL Instance Requests COMPLETE")

            # 3. Wait for ALL instances of Study to be Imported by verifying with AnonymizerModel
            #    Timeout if a pending instance is not received within Network Timeout
            #    or abort on user signal:
            prev_pending_instances = 0
            import_timer = int(self.model.network_timeouts.network)
            while import_timer:
                if self._abort_move:
                    raise (DICOMRuntimeError(f"C-MOVE@Instance[{study.uid}] aborted"))

                study.pending_instances = self.anonymizer.model.get_pending_instance_count(
                    study.uid, study.get_number_of_instances()
                )

                if study.pending_instances == 0:
                    logger.info(f"C-MOVE@Instance[{study.uid}] ALL Instances IMPORTED")
                    break

                # Reset timer if pending instances count changes:
                if study.pending_instances != prev_pending_instances:
                    prev_pending_instances = study.pending_instances
                    import_timer = int(self.model.network_timeouts.network)

                import_timer -= 1
                time.sleep(1)

            # 4. Raise Error if Timeout
            if import_timer == 0:
                raise (TimeoutError(f"C-MOVE@Instance[{study.uid}] Import Timeout"))

        except Exception as e:
            error_msg = str(e)  # latch exception error msg
            study.last_error_msg = error_msg
            logger.error(error_msg)

        finally:
            # Release the association:
            if move_association:
                if self._abort_move:
                    move_association.abort()
                else:
                    move_association.release()

        return error_msg

    def bulk_move_active(self) -> bool:
        """
        Check if there are any active move futures.

        Returns:
            bool: True if there are active move futures, False otherwise.
        """
        return self._move_futures is not None

    def _manage_move(self, req: MoveStudiesRequest) -> None:
        """
        Blocking: Manages a bulk move operation for a list of studies using a thread pool (self._study_move_thread_pool_size).

        Args:
            req (MoveStudiesRequest): The request dataclass object containing the details of the move operation.

                @dataclass
                class MoveStudiesRequest:
                    scp_name: str
                    dest_scp_ae: str # move destination
                    level: str  # STUDY, SERIES, IMAGE OR INSTANCE
                    studies: list[StudyUIDHierarchy]

        Returns:
            None
        """
        self._move_futures = []

        self._move_executor = ThreadPoolExecutor(
            max_workers=self._study_move_thread_pool_size,
            thread_name_prefix="MoveStudy",
        )

        # By DEFAULT Move Level is SERIES
        move_op = self._move_study_at_series_level
        if req.level:
            if "STUDY" in req.level.upper():
                move_op = self._move_study_at_study_level
            elif req.level.upper() in [_("IMAGE"), _("INSTANCE")]:
                move_op = self._move_study_at_instance_level

        logger.info(f"Move Operation: {move_op.__name__}")

        with self._move_executor as executor:
            for study in req.studies:
                future = executor.submit(
                    move_op,
                    req.scp_name,
                    req.dest_scp_ae,
                    study,
                )
                self._move_futures.append((future, move_op, study))

            logger.info(f"Move Futures: {len(self._move_futures)}")

            for future, __, study in self._move_futures:
                try:
                    error_msg = future.result()  # This will raise any exceptions that _move_study did not catch
                    if error_msg:
                        logger.warning(f"Study[{study.uid}] Move Future Error: {error_msg}")

                    # Auto DOWN LEVEL Study Move operation on Timeout:
                    # This algorithm was removed after testing with Hyland VNA indicated that it does not support instance move
                    # User level selection for Import process then implemented
                    # if error_msg and "Timeout" in error_msg:
                    #     logger.warning(f"Study[{study.uid}] Move Future Error: {error_msg}")
                    #     next_move_op = None

                    #     if move_op == self._move_study_at_study_level:
                    #         next_move_op = self._move_study_at_series_level
                    #     elif move_op == self._move_study_at_series_level:
                    #         next_move_op = self._move_study_at_instance_level

                    #     if next_move_op:
                    #         new_future = executor.submit(
                    #             next_move_op,
                    #             req.scp_name,
                    #             req.dest_scp_ae,
                    #             study,
                    #         )
                    #         self._move_futures.append((new_future, next_move_op, study))
                    #         logger.warning(f"Study[{study.uid}] Move Operation DOWN LEVEL to: {next_move_op.__name__}")

                except Exception as e:
                    # Handle specific exceptions if needed
                    if not self._abort_move:
                        logger.error(f"Exception caught in _manage_move: {e}")

        logger.info("_manage_move complete")
        self._move_futures = None
        self._move_executor = None

    def move_studies_ex(self, mr: MoveStudiesRequest) -> None:
        """
        Move studies asynchronously.

        Args:
            mr (MoveStudiesRequest): The request object containing the details of the studies to be moved.

                @dataclass
                class MoveStudiesRequest:
                    scp_name: str
                    dest_scp_ae: str
                    level: str
                    studies: list[StudyUIDHierarchy]
        """
        threading.Thread(
            target=self._manage_move,
            name="ManageMove",
            args=(mr,),
            daemon=True,  # daemon threads are abruptly stopped at shutdown
        ).start()

    def abort_move(self):
        """
        Aborts the current move operation.

        This method sets a flag to indicate that the move operation should be aborted.
        If a move executor is active, it cancels all pending move futures and shuts down the executor.
        After the move operation is aborted, the flag is reset.

        Returns:
            None
        """
        logger.info("Abort Move")
        self._abort_move = True
        if self._move_executor:
            self._move_executor.shutdown(wait=True, cancel_futures=True)
            logger.info("Move futures cancelled and executor shutdown")
            self._move_futures = None
            self._move_executor = None
        logger.info("Move abort complete")
        self._abort_move = False

    def _export_patient(self, dest_name: str, patient_id: str, ux_Q: Queue) -> None:
        """
        Blocking: Export the anonymized patient's DICOM files to the specified destination (DICOM server or AWS S3 bucket).

        Args:
            dest_name (str): The name of the destination.
            patient_id (str): The anonymized Patient ID.
            ux_Q (Queue): The UX queue to send ExportPatientsResponse to.

                Any exceptions & errors are reflected via the error field of ExportPatientsResponse

                @dataclass
                class ExportPatientsResponse:
                    patient_id: str
                    files_sent: int  # incremented for each file sent successfully
                    error: str | None  # error message
                    complete: bool  # True if all files sent successfully

        Returns:
            None
        """
        logger.info(f"_export_patient {patient_id} start, export to :{dest_name}")

        export_association: Association | None = None
        files_sent = 0
        try:
            # Load DICOM files to send from active local storage directory for this patient:
            patient_dir = Path(self.model.images_dir(), patient_id)

            if not patient_dir.exists():
                raise ValueError(f"Selected directory {patient_dir} does not exist")

            # Get all the DICOM files for this patient:
            file_paths = []
            for root, _, files in os.walk(patient_dir):
                file_paths.extend(os.path.join(root, file) for file in files if file.endswith(".dcm"))

            # Convert to dictionary with instance UIDs as keys:
            export_instance_paths = {Path(file_path).stem: file_path for file_path in file_paths}

            # Remove all instances which are already on destination from the export list:
            # For AWS get all instances for this patient id:
            if self.model.export_to_AWS:
                for instance_uid in self.AWS_get_instances(patient_id):
                    if instance_uid in export_instance_paths:
                        del export_instance_paths[instance_uid]
            else:
                # For DICOM Servers iterate through Study sub-directories for this patient
                # If a study instance is on the remote server (DICOM or AWS), remove from export_instance_paths dict
                self._abort_query = False
                for study_uid in os.listdir(patient_dir):
                    time.sleep(self._export_file_time_slice_interval)
                    if self._abort_export:
                        logger.error(f"_export_patient patient_id: {patient_id} aborted")
                        return

                    study_path = os.path.join(patient_dir, study_uid)
                    if not os.path.isdir(study_path):
                        continue

                    # Get Study UID Hierarchy:
                    _, study_hierarchy = self.get_study_uid_hierarchy(dest_name, study_uid, patient_id, True)
                    for instance in study_hierarchy.get_instances():
                        if instance.uid in export_instance_paths:
                            del export_instance_paths[instance.uid]

            # If NO files to export for this patient, indicate successful export to UX:
            if len(export_instance_paths) == 0:
                logger.info(f"All studies already exported to {dest_name} for patient: {patient_id}")
                ux_Q.put(ExportPatientsResponse(patient_id, 0, None, True))
                return

            # EXPORT Files:
            if self.model.export_to_AWS:
                s3 = self.AWS_authenticate()  # Raise AuthenticationError on error
                if not s3 or self._aws_user_directory is None:
                    raise ValueError("AWS Cognito authentication failed")

                for dicom_file_path in export_instance_paths.values():
                    time.sleep(self._export_file_time_slice_interval)
                    if self._abort_export:
                        logger.error(f"_export_patient patient_id: {patient_id} aborted")
                        return

                    logger.info(f"Upload to S3: {dicom_file_path}")

                    object_key = Path(
                        self.model.aws_cognito.s3_prefix,
                        self._aws_user_directory,
                        self.model.project_name,
                        Path(dicom_file_path).relative_to(self.model.images_dir()),
                    ).as_posix()

                    # TODO: use multi-part upload_part method for large files
                    # which can be aborted via s3.abort_multipart_upload
                    # or use thread for s3.upload_file and use callback of transferred bytes
                    s3.upload_file(dicom_file_path, self.model.aws_cognito.s3_bucket, object_key)
                    logger.info(f"Uploaded to S3: {object_key}")

                    files_sent += 1
                    ux_Q.put(ExportPatientsResponse(patient_id, files_sent, None, False))

            else:  # DICOM Export:
                # Connect to remote SCP and establish association based on the storage class and transfer syntax of file
                # Always export using the same storage class and transfer syntax as the original file
                # TODO: Implement Transcoding here
                last_sop_class_uid = None
                last_transfer_synax = None
                for dicom_file_path in export_instance_paths.values():
                    time.sleep(self._export_file_time_slice_interval)
                    if self._abort_export:
                        logger.error(f"_export_patient patient_id: {patient_id} aborted")
                        if export_association:
                            export_association.abort()
                        return

                    # Load dataset from file:
                    ds = dcmread(os.fspath(dicom_file_path))
                    if not hasattr(ds, "SOPClassUID") or not hasattr(ds, "file_meta"):
                        raise ValueError(f"Invalid DICOM file: {dicom_file_path}")
                    # Establish a new association if there is a change of SOPClassUID or TransferSyntaxUID:
                    if last_sop_class_uid != ds.SOPClassUID or last_transfer_synax != ds.file_meta.TransferSyntaxUID:
                        logger.info(
                            f"Connect to SCP: {dest_name} for SOPClassUID: {ds.SOPClassUID}, TransferSyntaxUID: {ds.file_meta.TransferSyntaxUID}"
                        )
                        if export_association:
                            export_association = export_association.release()
                        send_context = build_context(ds.SOPClassUID, ds.file_meta.TransferSyntaxUID)
                        export_association = self._connect_to_scp(dest_name, [send_context])
                        last_sop_class_uid = ds.SOPClassUID
                        last_transfer_synax = ds.file_meta.TransferSyntaxUID

                    if export_association:
                        dcm_response: Dataset = export_association.send_c_store(dataset=ds)
                    else:
                        logging.error(
                            "Internal error, _connect_to_scp did not establish association and did not raise corrresponding exception"
                        )

                    if not hasattr(dcm_response, "Status"):
                        raise TimeoutError("send_c_store timeout")

                    if dcm_response.Status != 0:
                        raise DICOMRuntimeError(f"{STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}")

                    files_sent += 1
                    ux_Q.put(ExportPatientsResponse(patient_id, files_sent, None, False))

            # Successful export:
            ux_Q.put(ExportPatientsResponse(patient_id, files_sent, None, True))

        except Exception as e:
            if not self._abort_export:
                logger.error(f"Export Patient {patient_id} Error: {e}")
            ux_Q.put(ExportPatientsResponse(patient_id, files_sent, f"{e}", True))

        finally:
            if export_association:
                export_association.release()

        return

    def bulk_export_active(self) -> bool:
        """
        Checks if bulk export is active.

        Returns:
            bool: True if bulk export is active, False otherwise.
        """
        return self._export_futures is not None

    def _manage_export(self, req: ExportPatientsRequest) -> None:
        """
        Blocking: Manage bulk patient export using a thread pool

        Args:
            req (ExportPatientsRequest): The export request containing destination name, patient IDs, and UX_Q.

                @dataclass
                class ExportPatientsRequest:
                    dest_name: str
                    patient_ids: list[str]  # list of patient IDs to export
                    ux_Q: Queue  # queue for UX updates for the full export

        Returns:
            None
        """
        self._export_futures = []

        self._export_executor = ThreadPoolExecutor(
            max_workers=self._patient_export_thread_pool_size,
            thread_name_prefix="ExportPatient",
        )

        with self._export_executor as executor:
            for i in range(len(req.patient_ids)):
                future = executor.submit(self._export_patient, req.dest_name, req.patient_ids[i], req.ux_Q)
                self._export_futures.append(future)

            logger.info(f"Export Futures: {len(self._export_futures)}")

            # Check for exceptions in the completed futures
            for future in self._export_futures:
                try:
                    # This will raise any exceptions that _export_patient might have raised.
                    future.result()
                except Exception as e:
                    # Handle specific exceptions if needed
                    if not self._abort_export:
                        logger.error(f"Exception caught in _manage_export: {e}")

        logger.info("_manage_export complete")

    def export_patients_ex(self, er: ExportPatientsRequest) -> None:
        """
        Non-blocking: Export patients based on the given ExportPatientsRequest.

        Args:
            er (ExportPatientsRequest): The ExportPatientsRequest object containing the export parameters.

                @dataclass
                class ExportPatientsRequest:
                    dest_name: str
                    patient_ids: list[str]  # list of patient IDs to export
                    ux_Q: Queue  # queue for UX updates for the full export

        Returns:
            None
        """
        self._abort_export = False
        threading.Thread(
            target=self._manage_export,
            name="ManageExport",
            args=(er,),
            daemon=True,  # daemon threads are abruptly stopped at shutdown
        ).start()

    def abort_export(self):
        """
        Aborts the export process.

        This method sets a flag to indicate that the export process should be aborted.
        It also cancels any pending move futures and shuts down the export executor.

        Note: If the export is being done to AWS, the executor will be shut down with wait=False,
        allowing any pending move futures to complete before shutting down.

        """
        logger.info("Abort Export")
        self._abort_export = True
        # logger.info("Cancel Futures")
        # for future in self._move_futures:
        #     future.cancel()
        if self._export_executor:
            self._export_executor.shutdown(wait=not self.model.export_to_AWS, cancel_futures=True)
            logger.info("Move futures cancelled and executor shutdown")
            self._export_executor = None

    def delete_study(self, anon_pt_id: str, anon_study_uid: str) -> bool:
        """
        Delete a study from the local storage and remove assoicated PHI data from the anonymizer model.

        Args:
            anon_pt_id (str): The Anonymized Patient ID of the study to be deleted.
            anon_study_uid (str): The Anonymized Study Instance UID of the study to be deleted.

        Returns:
            bool: True if the study was deleted successfully, False otherwise.
        """
        logger.info(f"Delete Anon StudyUID:{anon_study_uid} for Anon PatientID: {anon_pt_id}")
        patient_dir = Path(self.model.images_dir(), anon_pt_id)
        study_dir = Path(self.model.images_dir(), anon_pt_id, anon_study_uid)
        if study_dir.exists():
            try:
                # Compile list of all SOPInstanceUIDs in the study by reading the instance filename from storage directory:
                anon_instance_uids = []
                for root, _, files in os.walk(study_dir):
                    for file in files:
                        if file.endswith(".dcm"):
                            anon_instance_uids.append(Path(root, file).stem)

                # Iterate through all SOPInstanceUIDs and remove from AnonymizerModel uid_lookup using bidict inverse lookup:
                for anon_instance_uid in anon_instance_uids:
                    self.anonymizer.model.remove_uid_inverse(anon_instance_uid)

                # Remove files from local storage directory:
                shutil.rmtree(study_dir)
                logger.info(f"Study directory: {study_dir} deleted successfully")

                # If no more studies in patient directory, remove the patient directory:
                if not any(patient_dir.iterdir()):
                    shutil.rmtree(patient_dir)
                    logger.warning(
                        f"{patient_dir} empty => Patient {anon_pt_id} directory removed following study deletion"
                    )

            except Exception as e:
                # TODO: rollback?
                logger.error(f"Error deleting study files: {e}")
                return False

        # Remove PHI data from anonymizer model:
        if not self.anonymizer.model.remove_phi(anon_pt_id, anon_study_uid):
            logger.error(f"Critical Error removing phi data for StudyUID: {anon_study_uid} PatientID: {anon_pt_id}")
            return False

        logger.info(f"PHI data removed for StudyUID: {anon_study_uid} PatientID: {anon_pt_id} successfully")
        return True

    def create_phi_csv(self) -> Path | str:
        """
        Create a PHI (Protected Health Information) CSV file.

        This method generates a CSV file containing PHI data from the anonymizer model lookup tables.
        The CSV file includes the fields of AnonymizerModel.PHI_IndexRecord dataclass.

        Returns:
            Path | str: The path to the generated PHI CSV file if successful, otherwise an error message.
        """
        logger.info("Create PHI CSV")

        phi_index: List[PHI_IndexRecord] | None = self.anonymizer.model.get_phi_index()

        if not phi_index:
            logger.error("No Studies/PHI data in Anonymizer Model")
            return _("No Studies in Anonymizer Model")

        os.makedirs(self.model.phi_export_dir(), exist_ok=True)
        filename = f"{self.model.site_id}_{self.model.project_name}_PHI_{len(phi_index)}.csv"
        phi_csv_path = Path(self.model.phi_export_dir(), filename)

        try:
            with open(phi_csv_path, "w", newline="") as csv_file:
                writer = csv.writer(csv_file, delimiter=",")
                writer.writerow(PHI_IndexRecord.get_field_titles())
                for record in phi_index:
                    writer.writerow(record.flatten())
            logger.info(f"PHI saved to: {phi_csv_path}")
        except Exception as e:
            logger.error(f"Error writing PHI CSV: {e}")
            return repr(e)

        return phi_csv_path
