import os
from typing import cast, Dict, Optional, List, Tuple, Any
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import logging
import time
from datetime import datetime, timedelta
import pickle
import csv
import boto3
from pathlib import Path
from typing import List
from dataclasses import dataclass
from utils.translate import _
from utils.logging import set_logging_levels
from pydicom import Dataset
from pydicom.uid import UID
from pydicom.dataset import FileMetaDataset
from pynetdicom.association import Association
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import PresentationContext, build_context
from pynetdicom.events import (
    Event,
    EVT_ABORTED,
    EVT_C_STORE,
    EVT_C_ECHO,
    EventHandlerType,
)
from pynetdicom.status import (
    VERIFICATION_SERVICE_CLASS_STATUS,
    STORAGE_SERVICE_CLASS_STATUS,
    QR_FIND_SERVICE_CLASS_STATUS,
    QR_MOVE_SERVICE_CLASS_STATUS,
)
from .dicom_C_codes import (
    C_SUCCESS,
    C_PENDING_A,
    C_PENDING_B,
    C_WARNING,
    C_FAILURE,
    C_STORE_DATASET_ERROR,
    C_STORE_DECODE_ERROR,
)
from model.project import (
    ProjectModel,
    DICOMNode,
    NetworkTimeouts,
    DICOMRuntimeError,
    AuthenticationError,
)
from model.anonymizer import PHI
from .anonymizer import AnonymizerController
from __version__ import __version__

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
        instances: Dict[str, InstanceUIDHierarchy] = {},
    ):
        self.uid = uid
        self.number = number
        self.modality = modality
        self.sop_class_uid = sop_class_uid
        self.instance_count = instance_count
        self.description = description
        self.instances = instances
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
        return f"{self.uid},{self.number or ''},{self.modality or ''},{self.description or ''}[{self.completed_sub_ops},{self.failed_sub_ops},{self.remaining_sub_ops},{self.warning_sub_ops}]{instances_str}"

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
    def __init__(self, uid: str, series: Dict[str, SeriesUIDHierarchy] | None = None):
        self.uid = uid
        self.last_error_msg: str | None = None  # set by GetStudyHierarchy() or Move Operation
        self.series = series if series is not None else {}
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
        return f"{self.uid},{self.last_error_msg or ''},[{self.completed_sub_ops},{self.failed_sub_ops},{self.remaining_sub_ops},{self.warning_sub_ops}]{series_str}"

    def get_number_of_instances(self) -> int:
        count = 0
        for series_obj in self.series.values():
            count += len(series_obj.instances)
        return count

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
class ExportStudyRequest:
    dest_name: str
    patient_ids: list[str]  # list of patient IDs to export
    ux_Q: Queue  # queue for UX updates for the full export


@dataclass
class ExportStudyResponse:
    patient_id: str
    files_sent: int  # incremented for each file sent successfully
    error: str | None  # error message
    complete: bool


@dataclass
class MoveStudiesRequest:
    scp_name: str
    dest_scp_ae: str
    level: str
    studies: list[StudyUIDHierarchy]


class ProjectController(AE):

    PROJECT_MODEL_FILENAME = "ProjectModel.pkl"

    # TODO: GET RSNA ROOT ORGANIZATION UID
    RSNA_ROOT_ORG_UID = "1.2.826.0.1.3680043"
    IMPLEMENTATION_CLASS_UID = UID(RSNA_ROOT_ORG_UID)  # UI: (0002,0012)
    IMPLEMENTATION_VERSION_NAME = "RSNA DICOM Anonymizer" + " " + __version__
    # DICOM service class uids:
    _VERIFICATION_CLASS = "1.2.840.10008.1.1"  # Echo
    _STUDY_ROOT_QR_CLASSES = [
        "1.2.840.10008.5.1.4.1.2.2.1",  # Find
        "1.2.840.10008.5.1.4.1.2.2.2",  # Move
        "1.2.840.10008.5.1.4.1.2.2.3",  # Get
    ]
    _maximum_pdu_size = 0  # no limit
    _handle_store_time_slice_interval = 0.2  # seconds
    _export_file_time_slice_interval = 0.1  # seconds
    _patient_export_thread_pool_size = 4
    _study_move_thread_pool_size = 4
    _required_attributes_study_query = [
        "StudyInstanceUID",
        "ModalitiesInStudy",
        "NumberOfStudyRelatedSeries",
        "NumberOfStudyRelatedInstances",
    ]
    _required_attributes_series_query = ["StudyInstanceUID", "SeriesInstanceUID", "Modality"]
    _query_result_fields_to_remove = [
        "QueryRetrieveLevel",
        "RetrieveAETitle",
        "SpecificCharacterSet",
    ]

    def _missing_attributes(self, required_attributes: list[str], ds: Dataset) -> list[str]:
        return [attr_name for attr_name in required_attributes if attr_name not in ds or getattr(ds, attr_name) == ""]

    def _strip_query_result_fields(self, ds: Dataset) -> None:
        for field in self._query_result_fields_to_remove:
            if field in ds:
                delattr(ds, field)

    def __init__(self, model: ProjectModel):
        super().__init__(ae_title=model.scu.aet)
        self.model = model
        set_logging_levels(levels=model.logging_levels)
        # Ensure storage, public and private directories exist:
        self.model.storage_dir.joinpath(self.model.PRIVATE_DIR).mkdir(parents=True, exist_ok=True)
        self.model.storage_dir.joinpath(self.model.PUBLIC_DIR).mkdir(exist_ok=True)
        self.set_dicom_timeouts(timeouts=model.network_timeouts)
        # remote clients must provide Anonymizer's AE Title
        self._require_called_aet = True
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

    def _reset_scp_vars(self):
        self._abort_query = False
        self._abort_move = False
        self._abort_export = False
        self._export_futures = None
        self._export_executor = None
        self._move_futures = None
        self._move_executor = None
        self.scp = None

    def _post_model_update(self):
        self.stop_scp()
        self.set_dicom_timeouts(self.model.network_timeouts)
        self.set_radiology_storage_contexts()
        self.set_verification_context()
        self._reset_scp_vars()
        self.save_model()
        self.start_scp()

    def __str__(self):
        return super().__str__() + f"\n{self.model}" + f"\n{self.anonymizer.model}"

    def save_model(self, dest_dir: Path | None = None) -> bool:
        if dest_dir is None:
            dest_dir = self.model.storage_dir
        project_pkl_path = Path(dest_dir, self.PROJECT_MODEL_FILENAME)
        try:
            with open(project_pkl_path, "wb") as pkl_file:
                pickle.dump(self.model, pkl_file)
            logger.info(f"Model saved to: {project_pkl_path}")
            return True
        except Exception as e:
            logger.error(f"Fatal Error saving ProjectModel to {project_pkl_path}: {e}")
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
        self.add_supported_context(self._VERIFICATION_CLASS, self.model.transfer_syntaxes)
        return

    def set_radiology_storage_contexts(self) -> None:
        for uid in sorted(self.model.storage_classes):
            self.add_supported_context(uid, self.model.transfer_syntaxes)
        return

    # FOR SCU Association:
    def get_verification_context(self) -> PresentationContext:
        return build_context(
            self._VERIFICATION_CLASS, self.model.transfer_syntaxes
        )  # do not include compressed transfer syntaxes

    def get_radiology_storage_contexts(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, self.model.transfer_syntaxes)
            for abstract_syntax in self.model.storage_classes
        ]

    def set_study_root_qr_contexts(self) -> None:
        for uid in sorted(self._STUDY_ROOT_QR_CLASSES):
            self.add_supported_context(uid, self.model.transfer_syntaxes)
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

    # Handlers:
    def _handle_abort(self, event: Event):
        logger.error(f"_handle_abort: {event}")  # TODO: handle remote association async abort/disconnect

    # DICOM C-ECHO Verification event handler (EVT_C_ECHO):
    def _handle_echo(self, event: Event):
        logger.debug("_handle_echo")
        # TODO: Validate remote IP & AE Title, set calling/called AET
        remote = event.assoc.remote
        logger.info(f"C-ECHO from: {remote}")
        return C_SUCCESS

    # DICOM C-STORE scp event handler (EVT_C_STORE)):
    def _handle_store(self, event: Event):
        # Throttle incoming requests by adding a delay
        # to ensure UX responsiveness
        # time.sleep(self._handle_store_time_slice_interval)
        logger.debug("_handle_store")
        # TODO: Validate remote IP & AE Title
        remote = event.assoc.remote
        try:
            ds = Dataset(event.dataset)
            # Remove any Group 0x0002 elements that may have been included
            ds = ds[0x00030000:]
        except Exception as exc:
            logger.error("Unable to decode incoming dataset")
            logger.exception(exc)
            # Unable to decode dataset
            return C_STORE_DECODE_ERROR

        # Add the File Meta Information
        ds.file_meta = FileMetaDataset(event.file_meta)
        ds.file_meta.ImplementationClassUID = self.IMPLEMENTATION_CLASS_UID  # UI: (0002,0012)
        ds.file_meta.ImplementationVersionName = self.IMPLEMENTATION_VERSION_NAME  # SH: (0002,0013)

        remote_scu = DICOMNode(remote["address"], remote["port"], remote["ae_title"], False)
        logger.debug(remote_scu)

        # DICOM Dataset integrity checking:
        # TODO: send to quarantine?
        missing_attributes = self.anonymizer.missing_attributes(ds)
        if missing_attributes != []:
            logger.error(f"Incoming dataset is missing required attributes: {missing_attributes}")
            logger.error(f"\n{ds}")
            return C_STORE_DATASET_ERROR

        if self.anonymizer.model.uid_received(ds.SOPInstanceUID):
            logger.info(
                f"Instance already stored:{ds.PatientID}/{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}"
            )
            return C_SUCCESS

        logger.info(f"=>{ds.PatientID}/{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}")

        self.anonymizer.anonymize_dataset_and_store(remote_scu, ds)
        return C_SUCCESS

    def start_scp(self) -> None:
        logger.info(f"start {self.model.scp}, {self.model.storage_dir}...")

        if self.scp:
            msg = _(f"DICOM C-STORE scp is already running on {self.model.scp}")
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
            msg = _(f"Failed to start DICOM C-STORE scp on {self.model.scp}, Error: {str(e)}")
            logger.error(msg)
            raise DICOMRuntimeError(msg)

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

    def _connect_to_scp(self, scp: str | DICOMNode, contexts=None) -> Association:
        association = None
        if isinstance(scp, str):
            if scp not in self.model.remote_scps:
                raise ConnectionError(f"Remote SCP {scp} not found")
            remote_scp = self.model.remote_scps[scp]
        else:
            remote_scp = scp

        assert isinstance(remote_scp, DICOMNode)

        try:
            association = self.associate(
                remote_scp.ip,
                remote_scp.port,
                contexts=contexts,
                ae_title=remote_scp.aet,
                bind_address=(self.model.scu.ip, 0),
                evt_handlers=[(EVT_ABORTED, self._handle_abort)],
            )
            if not association.is_established:
                raise ConnectionError(f"Connection error to: {remote_scp}")
            logger.debug(f"Association established with {association.acceptor.ae_title}")
        except Exception as e:  # (ConnectionError, TimeoutError, RuntimeError) as e:
            logger.error(f"Error establishing association: {e}")
            raise

        return association

    def echo(self, scp: str | DICOMNode, ux_Q: Queue | None = None) -> bool:
        logger.info(f"Perform C-ECHO from {self.model.scu} to {scp}")
        association = None
        try:
            association = self._connect_to_scp(scp, [self.get_verification_context()])

            status: Dataset = association.send_c_echo()
            if not status:
                raise ConnectionError("Connection timed out, was aborted, or received an invalid response")

            if status.Status == C_SUCCESS:
                logger.info(f"C-ECHO Success")
                if ux_Q:
                    ux_Q.put(EchoResponse(success=True, error=None))
                association.release()
                return True
            else:
                raise DICOMRuntimeError(f"C-ECHO Failed status: {VERIFICATION_SERVICE_CLASS_STATUS[status.Status][1]}")

        except Exception as e:
            error = f"{(e)}"
            logger.error(error)
            if ux_Q:
                ux_Q.put(EchoResponse(success=False, error=error))
            if association:
                association.release()
            return False

    def echo_ex(self, er: EchoRequest) -> None:
        threading.Thread(target=self.echo, args=(er.scp, er.ux_Q)).start()

    def AWS_credentials_valid(self) -> bool:
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
        # Authenticates AWS Cognito User and returns AWS s3 client object
        # to use in creation of S3 client in each export thread
        # On error raises AuthenticationError with error message or re-raises any other exception thrown by boto3
        # Cache credentials and return s3 client object if credential expiration is longer than 10 mins
        logging.info(f"AWS_authenticate")
        if self.AWS_credentials_valid():
            logger.info(f"Using cached AWS credentials, Expiration:{self._aws_expiration_datetime}")
            self._aws_last_error = None
            return self._s3

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
                raise AuthenticationError(_(f"Unexpected Authorisation Challenge : {response['ChallengeName']}"))

            if "AuthenticationResult" not in response:
                logging.error(f"AuthenticationResult not in response: {response}")
                raise AuthenticationError(
                    _("AWS Cognito IDP authorisation failed\n\nAuthentication Result & Access Token not in response")
                )

            if "IdToken" not in response["AuthenticationResult"]:
                logging.error(f"IdToken not in response: {response}")
                raise AuthenticationError(
                    _("AWS Cognito authorisation failed\n\nIdToken Token not in Authentication Result")
                )

            if "AccessToken" not in response["AuthenticationResult"]:
                logging.error(f"AccessToken not in response: {response}")
                raise AuthenticationError(
                    _("AWS Cognito authorisation failed\n\nAccessToken Token not in Authentication Result")
                )

            cognito_identity_token = response["AuthenticationResult"]["IdToken"]

            # Get the User details and extract the user's sub-directory from User Attributes['sub'] (to follow private prefix)
            response = cognito_idp_client.get_user(AccessToken=response["AuthenticationResult"]["AccessToken"])

            if "UserAttributes" not in response:
                logging.error(f"UserAttributes not in response: {response}")
                raise AuthenticationError(
                    _("AWS Cognito Get User Attributes failed\n\nUserAttributes Token not in get_user response")
                )

            user_attribute_1 = response["UserAttributes"][0]

            if not user_attribute_1 or "Name" not in user_attribute_1 or user_attribute_1["Name"] != "sub":
                logging.error(f"User Attribute 'sub' not in response: {response}")
                raise AuthenticationError(
                    _("AWS Cognito Get User Attributes failed\n\nUser Attribute 'sub' not in get_user response")
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
                raise AuthenticationError(_("AWS Cognito authorisation failed\n IdentityId Token not in response"))

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
            raise e

    # Non-blocking call to AWS to authenticate via boto library:
    def AWS_authenticate_ex(self) -> None:
        threading.Thread(target=self.AWS_authenticate).start()

    # Blocking call to get list of objects in S3 bucket for an anonymized patient_id/study:
    # returns list of instance uids
    def AWS_get_instances(self, anon_pt_id: str, study_uid: str | None = None) -> list[str]:
        s3 = self.AWS_authenticate()
        if not s3 or not self._aws_user_directory:
            raise AuthenticationError("AWS Authentication failed")

        object_path = Path(
            self.model.aws_cognito.s3_prefix, self._aws_user_directory, self.model.project_name, anon_pt_id
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

    # Blocking send
    def send(self, file_paths: list[str], scp_name: str, send_contexts=None):
        logger.info(f"Send {len(file_paths)} files to {scp_name}")
        association = None
        if send_contexts is None:
            send_contexts = self.get_radiology_storage_contexts()
        files_sent = 0
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

    def _query(
        self,
        query_association: Association,
        ds: Dataset,
        ux_Q=None,
        required_attributes: list[str] | None = None,
    ) -> list[Dataset]:
        results = []
        error_msg = ""
        self._abort_query = False
        try:

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
                logger.info(f"Find Accession Numbers complete")
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

    # Blocking: Query remote server for studies matching the given query parameters:
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

        assert scp_name in self.model.remote_scps
        scp = self.model.remote_scps[scp_name]
        logger.info(f"C-FIND to {scp} Study Level Query: {name}, {id}, {acc_no}, {study_date}, {modality}")

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
        try:
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
                    f"{getattr(result, 'StudyDescription', 'N/A')}, "
                    f"{getattr(result, 'AccessionNumber', 'N/A')}, "
                    f"{getattr(result, 'ModalitiesInStudy', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedSeries', 'N/A')}, "
                    f"{getattr(result, 'NumberOfStudyRelatedInstances', 'N/A')}, "
                    # f"{getattr(result, 'StudyInstanceUID', 'N/A')} "
                )

        return results

    # Blocking: Query remote server for studies corresponding to list of accession numbers:
    def find_studies_via_acc_nos(
        self,
        scp_name: str,
        acc_no_list: list,
        ux_Q=None,
        verify_attributes=True,
    ) -> list[Dataset] | None:

        assert scp_name in self.model.remote_scps
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
        try:
            query_association = self._connect_to_scp(scp_name, self.get_study_root_qr_contexts())

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
                logger.info(f"Find Accession Numbers complete")
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

    # Non-blocking Find:
    def find_ex(self, fr: FindStudyRequest) -> None:
        if isinstance(fr.acc_no, list):
            logger.info("Find studies from list of accession numbers...")
            # Due to client removing numbers as they are found, make a copy of the list:
            acc_no_list = fr.acc_no.copy()
            fr.acc_no = acc_no_list
            threading.Thread(
                target=self.find_studies_via_acc_nos,
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

    # Blocking: Query remote DICOM server for study/series/instance uid hierarchy (required for iterative move):
    def get_study_uid_hierarchy(self, scp_name: str, study_uid: str) -> Tuple[str | None, StudyUIDHierarchy]:

        study_uid_hierarchy = StudyUIDHierarchy(uid=study_uid, series={})
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
                            f"Skip Series:{identifier.SeriesInstanceUID}, Series Level Query result is missing required attributes: {missing_attributes}"
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
                    sop_class_uid = identifier.get("SOPClassUID")
                    if sop_class_uid and sop_class_uid not in self.model.storage_classes:
                        logger.info(
                            f"Skip Series[SOPClassUID={identifier.SOPClassUID}]:{identifier.SeriesInstanceUID} with mismatched sop_class_uid"
                        )
                        continue

                    # New SeriesUIDHierarchy:
                    series_descr = identifier.SeriesDescription if hasattr(identifier, "SeriesDescription") else "?"
                    instance_count = (
                        int(identifier.NumberOfSeriesRelatedInstances)
                        if hasattr(
                            identifier, "NumberOfSeriesRelatedInstances"
                        )  # This is an optional return field as per DICOM Std. (dammit)
                        else 1
                    )
                    study_uid_hierarchy.series[identifier.SeriesInstanceUID] = SeriesUIDHierarchy(
                        uid=identifier.SeriesInstanceUID,
                        number=identifier.SeriesNumber if hasattr(identifier, "SeriesNumber") else None,
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
                raise DICOMRuntimeError(f"C-FIND[series] Failed: No series found in study matching project modalities")

            # 3. Get list of Instance UIDs for each Series UID:
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

                    if (
                        identifier
                        and hasattr(identifier, "StudyInstanceUID")
                        and hasattr(identifier, "SeriesInstanceUID")
                        and hasattr(identifier, "SOPInstanceUID")
                    ):
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

    # Blocking: Get List of StudyUIDHierarchies based on value of study_uid within each element of list
    # last_error_msg is set by get_study_uid_hierarchy:
    # TODO: Optimization: make this multi-threaded using futures & thread executor as for manage_move
    #       Get UIDs only down to a specified level as required by move_operation
    def get_study_uid_hierarchies(self, scp_name: str, studies: List[StudyUIDHierarchy]) -> None:
        logger.info(f"Get StudyUIDHierarchies for {len(studies)} studies")
        self._abort_query = False
        for study in studies:
            if self._abort_query:
                logger.info("Query Aborted")
                break
            error_msg, study_uid_hierarchy = self.get_study_uid_hierarchy(scp_name, study.uid)
            study.series = study_uid_hierarchy.series
            study.last_error_msg = error_msg

        logger.info(f"Get StudyUIDHierarchies done")

    # Non-blocking Get List of StudyUIDHierarchies
    def get_study_uid_hierarchies_ex(self, scp_name: str, studies: List[StudyUIDHierarchy]) -> None:
        threading.Thread(
            target=self.get_study_uid_hierarchies,
            args=(
                scp_name,
                studies,
            ),
            daemon=True,  # daemon threads are abruptly stopped at shutdown
        ).start()

    def get_pending_instances(self, study: StudyUIDHierarchy) -> List[InstanceUIDHierarchy]:
        pending_instances: List[InstanceUIDHierarchy] = []
        for series in study.series.values():
            for instance in series.instances.values():
                if not self.anonymizer.model.uid_received(instance.uid):
                    pending_instances.append(instance)
        return pending_instances

    def get_number_of_pending_instances(self, study: StudyUIDHierarchy) -> int:
        return len(self.get_pending_instances(study))

    # Blocking Move Study at STUDY Level, status updates reflected in study_uid_hierarchy, on exception return error message::
    def _move_study_at_study_level(
        self,
        scp_name: str,
        dest_scp_ae: str,
        study: StudyUIDHierarchy,
    ) -> str | None:
        logger.info(f"C-MOVE@Study[{study.uid}] scp:{scp_name} move to:{dest_scp_ae}")

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

            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.StudyInstanceUID = study.uid

            # 2. Use the C-MOVE service to request that the remote SCP move the Study to local storage scp:
            # 2. Move Request for Study UID & wait for Move Responses for each instance in study:
            responses = move_association.send_c_move(
                dataset=ds,
                move_aet=dest_scp_ae,
                query_model=self._STUDY_ROOT_QR_CLASSES[1],
                priority=1,
            )

            # Process the responses received from the remote scp:
            # * Note * pynetdicom docs for send_c_move:
            # If the status category is 'Pending' or 'Success' then yields None.
            # If the status category is 'Warning', 'Failure' or 'Cancel' then yields a ~pydicom.dataset.Dataset which should contain
            # an (0008,0058) *Failed SOP Instance UID List* element, however as this comes from the peer this is not guaranteed
            # and may instead be an empty ~pydicom.dataset.Dataset.
            for status, identifier in responses:
                if self._abort_move:
                    raise (DICOMRuntimeError(f"C-MOVE@Study[{study.uid}] move study aborted"))

                if not status:
                    raise ConnectionError(_(f"Connection timed out or aborted moving study_uid: {study.uid}"))

                if status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B, C_WARNING):
                    logger.error(
                        f"C-MOVE@Study[{study.uid}] failure, status:{hex(status.Status).upper()}: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                    )
                    logger.error(f"_Move Request Dataset:\n{ds}")
                    if identifier:
                        logger.error(f"_Response identifier: {identifier}")
                    continue

                if status.Status == C_SUCCESS:
                    logger.info(f"C-MOVE@Study[{study.uid}] Study Request SUCCESS")

                # Update Move stats from status:
                study.update_move_stats(status)

                if identifier:
                    logger.info(f"C-MOVE@Study[{study.uid}] Response identifier: {identifier}")

            logger.info(f"C-MOVE@Study Request for Study COMPLETE: StudyUIDHierachy:\n{study}")

            # 4. If there are no pending instances, return without error:
            pending_instances = self.get_number_of_pending_instances(study)
            if pending_instances == 0:
                logger.info(f"C-MOVE@Study[{study.uid}] ALL Instances IMPORTED")
                # Mark Study Imported in Anonymizer Model set, for use by Query result Treeview (Show/Hide Imported Studies)
                self.anonymizer.model.set_study_imported(study.uid)
            else:
                # 5. Wait for ALL instances of Study to be Imported,
                #    Timeout if a pending instance is not received within NetworkTimeout
                #    or abort on user signal:
                import_timer = self.model.network_timeouts.network
                prev_pending_instances = pending_instances
                while import_timer > 0:
                    if self._abort_move:
                        raise (DICOMRuntimeError(f"C-MOVE@Study[{study.uid}] aborted"))

                    pending_instances = self.get_number_of_pending_instances(study)

                    if pending_instances == 0:
                        logger.info(f"C-MOVE@Study[{study.uid}] ALL Instances IMPORTED")
                        self.anonymizer.model.set_study_imported(study.uid)
                        break

                    # Reset timer if pending instances count changes:
                    if pending_instances != prev_pending_instances:
                        prev_pending_instances = pending_instances
                        import_timer = self.model.network_timeouts.network

                    time.sleep(1)
                    import_timer -= 1

                # 6. Raise Error if Timeout
                if import_timer == 0:
                    raise (TimeoutError(f"C-MOVE@Study[{study.uid}] Import Timeout"))

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

    # Blocking Move Study at SERIES Level, status updates reflected in study_uid_hierarchy, on exception return error message:
    def _move_study_at_series_level(self, scp_name: str, dest_scp_ae: str, study: StudyUIDHierarchy) -> str | None:

        logger.info(f"C-MOVE@Series[{study.uid}] scp:{scp_name} move to:{dest_scp_ae} ")

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

            # 2. Move Request for each Series UID & wait for Move Response:
            for series in study.series.values():

                if len(series.instances) == 0:
                    logger.error(f"No instances in Series: {series.uid} skipping")
                    continue

                ds = Dataset()
                ds.QueryRetrieveLevel = "SERIES"
                ds.StudyInstanceUID = study.uid
                ds.SeriesInstanceUID = series.uid
                if series.number:
                    ds.SeriesNumber = series.number

                logger.info(
                    f"C-MOVE@Series[{study.uid}] Request: Modality={series.modality} SOPClassUID={series.sop_class_uid} SeriesUID={series.uid} SeriesNumber={series.number}"
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
                for status, identifier in responses:
                    if self._abort_move:
                        raise (DICOMRuntimeError(f"C-MOVE@Series[{study.uid}] study move aborted"))

                    if not status:
                        raise (
                            DICOMRuntimeError(
                                f"C-MOVE@Series[{study.uid}] Connection Error, no status returned from scp"
                            )
                        )

                    if status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B, C_WARNING):
                        logger.error(
                            f"C-MOVE@Series[{study.uid}/{series.uid}] failure, status:{hex(status.Status).upper()}: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                        )
                        logger.error(f"_Move Request Dataset:\n{ds}")
                        if identifier:
                            logger.error(f"_Response identifier: {identifier}")
                        continue

                    if status.Status == C_SUCCESS:
                        logger.info(
                            f"C-MOVE@Series[{study.uid}] Series Request SUCCESS SeriesUID:{series.uid} SeriesNumber:{series.number}"
                        )

                    # Update Move stats from status:
                    series.update_move_stats(status)

            logger.info(f"C-MOVE@Series ALL Series Requests for Study COMPLETE: StudyUIDHierachy:\n{study}")

            # 4. If there are no pending instances, return without error:
            pending_instances = self.get_pending_instances(study)
            if pending_instances == []:
                logger.info(f"C-MOVE@Series[{study.uid}] ALL Instances IMPORTED")
                # Mark Study Imported in Anonymizer Model set, for use by Query result Treeview (Show/Hide Imported Studies)
                self.anonymizer.model.set_study_imported(study.uid)
            else:
                # 5. Wait for ALL instances of Study to be Imported,
                #    Timeout if a pending instance is not received within NetworkTimeout
                #    or abort on user signal:
                import_timer = self.model.network_timeouts.network
                prev_pending_instances = pending_instances
                while import_timer > 0:
                    if self._abort_move:
                        raise (DICOMRuntimeError(f"C-MOVE@Series[{study.uid}] aborted"))

                    pending_instances = self.get_number_of_pending_instances(study)

                    if pending_instances == 0:
                        logger.info(f"C-MOVE@Series[{study.uid}] ALL Instances IMPORTED")
                        self.anonymizer.model.set_study_imported(study.uid)
                        break

                    # Reset timer if pending instances count changes:
                    if pending_instances != prev_pending_instances:
                        prev_pending_instances = pending_instances
                        import_timer = self.model.network_timeouts.network

                    time.sleep(1)
                    import_timer -= 1

                # 6. Raise Error if Timeout
                if import_timer == 0:
                    raise (TimeoutError(f"C-MOVE@Series[{study.uid}] Import Timeout"))

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

    # Blocking Move Study at INSTANCE Level, status updates reflected in study_uid_hierarchy, on exception return error message:
    def _move_study_at_instance_level(
        self,
        scp_name: str,
        dest_scp_ae: str,
        study: StudyUIDHierarchy,
    ) -> str | None:

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
                    if self.anonymizer.model.uid_received(instance.uid):
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
                    for status, identifier in responses:
                        if self._abort_move:
                            raise (DICOMRuntimeError(f"C-MOVE@Instance[{study.uid}] aborted"))

                        logger.debug(f"STATUS: {status}")

                        if not status:
                            raise (
                                DICOMRuntimeError(f"C-MOVE[{study.uid}] Connection Error, no status returned from scp")
                            )

                        if status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B, C_WARNING):
                            logger.error(
                                f"C-MOVE@Instance[{study.uid}/{series.uid}/{instance.uid}] failure, status:{hex(status.Status)}: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                            )
                            logger.error(f"_Move Request Dataset:\n{ds}")
                            if identifier:
                                logger.error(f"_Response identifier: {identifier}")
                            continue

                        if status.Status == C_SUCCESS:
                            logger.info(
                                f"C-MOVE@Instance[{study.uid}/{series.uid}/{instance.uid}] Instance Request SUCCESS"
                            )

                        # Update Move stats from status:
                        series.update_move_stats_instance_level(status)

                logger.info(f"C-MOVE@Instance[{study.uid}/{series.uid}] ALL Instance Requests for Series COMPLETE")

            logger.info(f"C-MOVE@Instance[{study.uid}] ALL Instance Requests COMPLETE")

            # 4. If there are no pending instances, return without error:
            pending_instances = self.get_pending_instances(study)
            if pending_instances == []:
                logger.info(f"C-MOVE[{study.uid}] ALL Instances IMPORTED")
                # Mark Study Imported in Anonymizer Model set, for use by Query result Treeview (Show/Hide Imported Studies)
                self.anonymizer.model.set_study_imported(study.uid)
            else:
                # 5. Wait for ALL instances of Study to be Imported,
                #    Timeout if a pending instance is not received within Network Timeout
                #    or abort on user signal:
                import_timer = self.model.network_timeouts.network
                prev_pending_instances = pending_instances
                while import_timer > 0:
                    if self._abort_move:
                        raise (DICOMRuntimeError(f"C-MOVE@Instance[{study.uid}] aborted"))

                    pending_instances = self.get_number_of_pending_instances(study)

                    if pending_instances == 0:
                        logger.info(f"C-MOVE@Instance[{study.uid}] ALL Instances IMPORTED")
                        self.anonymizer.model.set_study_imported(study.uid)
                        break

                    # Reset timer if pending instances count changes:
                    if pending_instances != prev_pending_instances:
                        prev_pending_instances = pending_instances
                        import_timer = self.model.network_timeouts.network

                    time.sleep(1)
                    import_timer -= 1

                # 6. Raise Error if Timeout
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
        return self._move_futures is not None

    # Blocking manage bulk study move using a thread pool:
    def _manage_move(self, req: MoveStudiesRequest) -> None:
        self._move_futures = []

        self._move_executor = ThreadPoolExecutor(max_workers=self._study_move_thread_pool_size)

        # By DEFAULT Move Level is SERIES
        move_op = self._move_study_at_series_level
        if req.level:
            if "STUDY" in req.level.upper():
                move_op = self._move_study_at_study_level
            elif req.level.upper() in ["IMAGE", "INSTANCE"]:
                move_op = self._move_study_at_instance_level

        logger.info(f"Move Operation: {move_op.__name__}")

        with self._move_executor as executor:

            for study in req.studies:

                pending_instances = self.get_number_of_pending_instances(study)
                if pending_instances == 0:
                    logger.warning(f"Study[{study.uid}] has no pending instances, skipping")
                    self.anonymizer.model.set_study_imported(study.uid)
                    continue

                # If ANY Instances have already been received for study
                # Set Move Operation to Instance Level
                # TODO: Horos does not support Instance Level Move, other PACS?
                # Implement Project / UX Switch to prevent move at instance level
                if pending_instances < study.get_number_of_instances():
                    move_op = self._move_study_at_instance_level

                future = executor.submit(
                    move_op,
                    req.scp_name,
                    req.dest_scp_ae,
                    study,
                )
                self._move_futures.append((future, move_op, study))

            logger.info(f"Move Futures: {len(self._move_futures)}")

            for future, move_op, study in self._move_futures:

                try:
                    error_msg = future.result()  # This will raise any exceptions that _move_study did not catch:

                    # Auto DOWN LEVEL Study Move operation on Timeout:
                    if error_msg and "Timeout" in error_msg:
                        logger.warning(f"Study[{study.uid}] Move Future Error: {error_msg}")
                        next_move_op = None

                        if move_op == self._move_study_at_study_level:
                            next_move_op = self._move_study_at_series_level
                        elif move_op == self._move_study_at_series_level:
                            next_move_op = self._move_study_at_instance_level

                        if next_move_op:
                            new_future = executor.submit(
                                next_move_op,
                                req.scp_name,
                                req.dest_scp_ae,
                                study,
                            )
                            self._move_futures.append((new_future, next_move_op, study))
                            logger.warning(f"Study[{study.uid}] Move Operation DOWN LEVEL to: {next_move_op.__name__}")

                except Exception as e:
                    # Handle specific exceptions if needed
                    if not self._abort_move:
                        logger.error(f"Exception caught in _manage_move: {e}")

        logger.info("_manage_move complete")
        self._move_futures = None
        self._move_executor = None

    # Non-blocking Move Studies:
    def move_studies_ex(self, mr: MoveStudiesRequest) -> None:
        threading.Thread(
            target=self._manage_move,
            args=(mr,),
            daemon=True,  # daemon threads are abruptly stopped at shutdown
        ).start()

    def abort_move(self):
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
        logger.info(f"_export_patient {patient_id} start to {dest_name}")

        export_association = None
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
                    _, study_hierarchy = self.get_study_uid_hierarchy(dest_name, study_uid)
                    for instance in study_hierarchy.get_instances():
                        if instance.uid in export_instance_paths:
                            del export_instance_paths[instance.uid]

            # If NO files to export for this patient, indicate successful export to UX:
            if len(export_instance_paths) == 0:
                logger.info(f"All studies already exported to {dest_name} for patient: {patient_id}")
                ux_Q.put(ExportStudyResponse(patient_id, 0, None, True))
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
                    ux_Q.put(ExportStudyResponse(patient_id, files_sent, None, False))

            else:  # DICOM Export:

                # Connect to remote SCP:
                export_association = self._connect_to_scp(dest_name, self.get_radiology_storage_contexts())

                for dicom_file_path in export_instance_paths.values():
                    time.sleep(self._export_file_time_slice_interval)
                    if self._abort_export:
                        logger.error(f"_export_patient patient_id: {patient_id} aborted")
                        export_association.abort()
                        return

                    dcm_response: Dataset = export_association.send_c_store(dataset=dicom_file_path)

                    if not hasattr(dcm_response, "Status"):
                        raise TimeoutError("send_c_store timeout")

                    if dcm_response.Status != 0:
                        raise DICOMRuntimeError(f"{STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}")

                    files_sent += 1
                    ux_Q.put(ExportStudyResponse(patient_id, files_sent, None, False))

            # Successful export:
            ux_Q.put(ExportStudyResponse(patient_id, files_sent, None, True))

        except Exception as e:
            if not self._abort_export:
                logger.error(f"Export Patient {patient_id} Error: {e}")
            ux_Q.put(ExportStudyResponse(patient_id, files_sent, f"{e}", True))

        finally:
            if export_association:
                export_association.release()

        return

    def bulk_export_active(self) -> bool:
        return self._export_futures is not None

    # Blocking: Manage bulk patient export using a thread pool:
    def _manage_export(self, req: ExportStudyRequest) -> None:
        self._export_futures = []

        self._export_executor = ThreadPoolExecutor(max_workers=self._patient_export_thread_pool_size)

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

    # Non-blocking export_patients:
    def export_patients_ex(self, er: ExportStudyRequest) -> None:
        self._abort_export = False
        threading.Thread(
            target=self._manage_export,
            args=(er,),
            daemon=True,  # daemon threads are abruptly stopped at shutdown
        ).start()

    def abort_export(self):
        logger.info("Abort Export")
        self._abort_export = True
        # logger.info("Cancel Futures")
        # for future in self._move_futures:
        #     future.cancel()
        if self._export_executor:
            self._export_executor.shutdown(wait=False if self.model.export_to_AWS else True, cancel_futures=True)
            logger.info("Move futures cancelled and executor shutdown")
            self._export_executor = None

    def create_phi_csv(self) -> Path | str:
        logger.info("Create PHI CSV")
        field_names = [
            _("ANON-PatientID"),
            _("ANON-PatientName"),
            _("PHI-PatientName"),
            _("PHI-PatientID"),
            _("DateOffset"),
            _("PHI-StudyDate"),
            _("ANON-Accession"),
            _("PHI-Accession"),
            _("ANON-StudyInstanceUID"),
            _("PHI-StudyInstanceUID"),
            _("Number of Series"),
            _("Number of Instances"),
        ]
        phi_data = []
        # Create PHI data table from anonymizer model lookup tables:
        for anon_pt_id in self.anonymizer.model._phi_lookup.keys():
            phi: PHI = self.anonymizer.model._phi_lookup[anon_pt_id]
            for study in phi.studies:
                phi_data.append(
                    (
                        anon_pt_id,
                        anon_pt_id,
                        phi.patient_name,
                        phi.patient_id,  # TODO: Handle missing PatientID / PatientName
                        study.anon_date_delta,
                        study.study_date,
                        self.anonymizer.model._acc_no_lookup[
                            study.accession_number
                        ],  # TODO: Handle missing accession numbers
                        study.accession_number,
                        self.anonymizer.model._uid_lookup[study.study_uid],
                        study.study_uid,
                        len(study.series),
                        sum([s.instances for s in study.series]),
                    )
                )

        os.makedirs(self.model.phi_export_dir(), exist_ok=True)
        filename = f"{self.model.site_id}_{self.model.project_name}_PHI_{len(phi_data)}.csv"
        phi_csv_path = Path(self.model.phi_export_dir(), filename)

        try:
            with open(phi_csv_path, "w", newline="") as csv_file:
                writer = csv.writer(csv_file, delimiter=",")
                writer.writerow(field_names)
                writer.writerows(phi_data)
            logger.info(f"PHI saved to: {phi_csv_path}")
        except Exception as e:
            logger.error(f"Error writing PHI CSV: {e}")
            return repr(e)

        return phi_csv_path
