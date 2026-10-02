"""
ProjectController: DICOM Application Entity (SCU + SCP) for the Anonymizer project.

Networking implementation lives in ``anonymizer.controller.dicom`` mixins.
This module assembles the AE and retains AWS export, PHI, and AI façades.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
from typing import Any, List

import boto3
from pydicom import Dataset, dcmread
from pydicom.uid import UID
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.association import Association
from pynetdicom.presentation import build_context
from pynetdicom.status import STORAGE_SERVICE_CLASS_STATUS

from anonymizer.controller.ai.batch_process import (
    AiBatchCancelledCallback,
    AiBatchMemoryCallback,
    AiBatchProcessOptions,
    AiBatchProgressCallback,
    AiBatchSummary,
    AiBatchWorkflowLogCallback,
    ai_batch_process,
)
from anonymizer.controller.ai.harmonize import (
    HarmonizeStudiesCancelledCallback,
    HarmonizeStudiesLogCallback,
    HarmonizeStudiesProgressCallback,
    HarmonizeStudiesSummary,
    harmonize_studies_batch,
)
from anonymizer.controller.anonymizer import AnonymizerController
from anonymizer.controller.dicom import dicomweb as dicomweb_api
from anonymizer.controller.dicom.association import AssociationMixin
from anonymizer.controller.dicom.echo_scu import EchoMixin
from anonymizer.controller.dicom.find_scu import FindMixin
from anonymizer.controller.dicom.hierarchies import (
    InstanceUIDHierarchy,
    SeriesUIDHierarchy,
    StudyUIDHierarchy,
)
from anonymizer.controller.dicom.requests import (
    EchoRequest,
    EchoResponse,
    ExportPatientsRequest,
    ExportPatientsResponse,
    FindStudyRequest,
    FindStudyResponse,
    MoveStudiesRequest,
)
from anonymizer.controller.dicom.retrieve_scu import RetrieveMixin
from anonymizer.controller.dicom.scp import ScpMixin
from anonymizer.controller.dicom.store_scu import StoreMixin
from anonymizer.controller.phi_io import (
    PHI_IndexRecord,
    build_phi_index,
    format_series_processing_status,
    write_lookup_csv,
)
from anonymizer.controller.phi_io import (
    import_java_phi_studies as phi_io_import_java_phi_studies,
)
from anonymizer.controller.work_state import WorkState
from anonymizer.model.anonymizer import PHI, SeriesProcessingStatus
from anonymizer.model.project import (
    AuthenticationError,
    DICOMRuntimeError,
    ProjectModel,
)
from anonymizer.utils.logging import set_logging_levels
from anonymizer.utils.storage import JavaAnonymizerExportedStudy
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

# Re-export hierarchy / request types for existing call sites
__all__ = [
    "InstanceUIDHierarchy",
    "SeriesUIDHierarchy",
    "StudyUIDHierarchy",
    "EchoRequest",
    "EchoResponse",
    "FindStudyRequest",
    "FindStudyResponse",
    "MoveStudiesRequest",
    "ExportPatientsRequest",
    "ExportPatientsResponse",
    "ProjectController",
]


class ProjectController(
    AssociationMixin,
    ScpMixin,
    EchoMixin,
    StoreMixin,
    FindMixin,
    RetrieveMixin,
    AE,
):
    """
    DICOM Application Entity (pynetdicom.ae sub-class) for the Anonymizer.

    Dual SCU + SCP role (intentional):

    - SCP: C-ECHO, C-STORE (local listen; C-MOVE sub-ops land here)
    - SCU: C-ECHO, C-FIND, C-MOVE, C-GET, C-STORE (export/send)

    Study Root Query/Retrieve Information Model is used for Find / Move / Get.
    Retrieve prefers C-GET when the remote association accepts Get; otherwise C-MOVE.
    """

    PROJECT_MODEL_FILENAME_PKL = "ProjectModel.pkl"
    PROJECT_MODEL_FILENAME_JSON = "ProjectModel.json"

    _VERIFICATION_CLASS = "1.2.840.10008.1.1"
    _STUDY_ROOT_QR_CLASSES = [
        "1.2.840.10008.5.1.4.1.2.2.1",  # Find
        "1.2.840.10008.5.1.4.1.2.2.2",  # Move
        "1.2.840.10008.5.1.4.1.2.2.3",  # Get
    ]

    _handle_store_time_slice_interval = 0.05
    _export_file_time_slice_interval = 0.1
    _patient_export_thread_pool_size = 4
    _study_move_thread_pool_size = 2
    _memory_available_backoff_threshold = 1 << 30

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
        super().__init__(ae_title=model.scu.aet)
        self.model = model
        set_logging_levels(levels=model.logging_levels)
        self.model.storage_dir.joinpath(self.model.PRIVATE_DIR).mkdir(parents=True, exist_ok=True)
        self.model.storage_dir.joinpath(self.model.PUBLIC_DIR).mkdir(exist_ok=True)
        self.set_dicom_timeouts(timeouts=model.network_timeouts)
        self._implementation_class_uid = UID(self.model.IMPLEMENTATION_CLASS_UID)
        self._implementation_version_name = self.model.IMPLEMENTATION_VERSION_NAME
        self._maximum_pdu_size = 0
        self._require_called_aet = True
        self.set_radiology_storage_contexts()
        self.set_verification_context()
        self._reset_scp_vars()
        self._qr_get_supported: dict[str, bool] = {}
        self._qr_move_supported: dict[str, bool] = {}
        self._last_retrieve_modality: str | None = None

        self._aws_credentials = {}
        self._s3 = None
        self._aws_expiration_datetime: datetime | None = None
        self._aws_user_directory: str | None = None
        self._aws_last_error: str | None = None
        self.anonymizer = AnonymizerController(project_model=model)

    def build_dataset_analytics(self, *, should_abort=None):
        from anonymizer.controller.analytics.dataset import build_dataset_analytics

        return build_dataset_analytics(
            self.anonymizer.model,
            Path(self.model.images_dir()),
            should_abort=should_abort,
        )

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
        self.stop_scp()
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
            shutil.copy2(filepath, filepath.with_suffix(filepath.suffix + ".bak"))
            logger.debug(f"Model saved to: {filepath}")
            return True
        except Exception as e:
            logger.error(f"Fatal Error saving ProjectModel to {filepath}: {e}")
            return False

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


    def _export_patient(
        self,
        dest_name: str,
        patient_id: str,
        ux_Q: Queue,
        *,
        export_dicom_seg: bool = False,
    ) -> None:
        """
        Blocking: Export the anonymized patient's DICOM files to the specified destination (DICOM server or AWS S3 bucket).

        Args:
            dest_name (str): The name of the destination.
            patient_id (str): The anonymized Patient ID.
            ux_Q (Queue): The UX queue to send ExportPatientsResponse to.
            export_dicom_seg: When True, convert series segments (TotalSegmentator
                ``seg/`` masks and user ROI annotations) to DICOM-SEG files in each
                series directory before collecting files to send.

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
        logger.info(
            f"_export_patient {patient_id} start, export to :{dest_name} dicom_seg={export_dicom_seg}"
        )

        export_association: Association | None = None
        files_sent = 0
        try:
            # Load DICOM files to send from active local storage directory for this patient:
            patient_dir = Path(self.model.images_dir(), patient_id)

            if not patient_dir.exists():
                raise ValueError(f"Selected directory {patient_dir} does not exist")

            if export_dicom_seg:
                self._prepare_patient_dicom_segs(patient_dir)

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

            else:  # DICOM Export (DIMSE C-STORE or DICOMweb STOW-RS):
                dest_node = self._resolve_remote(dest_name)
                if dest_node.dicomweb:
                    with dicomweb_api.open_session(dest_node, self.model.network_timeouts) as session:
                        for dicom_file_path in export_instance_paths.values():
                            time.sleep(self._export_file_time_slice_interval)
                            if self._abort_export:
                                logger.error(f"_export_patient patient_id: {patient_id} aborted")
                                return
                            dicomweb_api.store_files(
                                session,
                                [dicom_file_path],
                                abort_check=lambda: self._abort_export,
                            )
                            files_sent += 1
                            ux_Q.put(ExportPatientsResponse(patient_id, files_sent, None, False))
                else:
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

    ROI_SEG_FILENAME = "roi_annotations.seg.dcm"

    def _prepare_patient_dicom_segs(self, patient_dir: Path) -> None:
        """Convert series segments to DICOM-SEG files under each series directory.

        Includes TotalSegmentator ``seg/`` anatomy masks (e.g. brain structures) and
        user ROI ``annotations/``. Failures for individual series are logged and
        skipped so the patient export continues.
        """
        from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
        from anonymizer.controller.annotations import export_dicom_seg
        from anonymizer.controller.annotations.export_dicom_seg import build_dicom_seg_export_session

        patient_dir = Path(patient_dir)
        for study_path in sorted(patient_dir.iterdir()):
            if not study_path.is_dir() or study_path.name.startswith("."):
                continue
            for series_path in sorted(study_path.iterdir()):
                if not series_path.is_dir() or series_path.name.startswith("."):
                    continue
                cache_dir = resolve_series_cache_dir(series_path)
                session = build_dicom_seg_export_session(cache_dir)
                if session is None:
                    continue
                dest = series_path / self.ROI_SEG_FILENAME
                try:
                    export_dicom_seg(cache_dir, dest, series_dir=series_path, session=session)
                    logger.info("Prepared DICOM-SEG for export: %s", dest)
                except Exception:
                    logger.exception("DICOM-SEG conversion failed for series %s; continuing export", series_path)

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
                future = executor.submit(
                    self._export_patient,
                    req.dest_name,
                    req.patient_ids[i],
                    req.ux_Q,
                    export_dicom_seg=req.export_dicom_seg,
                )
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
        Delete a study from the local storage, remove Study,Series,Instance UID mappings and remove assoicated PHI data from the anonymizer model.

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

                # Iterate through all SOPInstanceUIDs and remove from AnonymizerModel UID Map:
                for anon_instance_uid in anon_instance_uids:
                    self.anonymizer.model.remove_uid_inverse(anon_instance_uid)

                # Compile list of all SeriesInstanceUIDs in the study by reading the series sub-directories from storage directory:
                anon_series_uids = os.listdir(study_dir)
                # Iterate through all SeriesInstanceUIDs and remove from AnonymizerModel UID Map:
                for anon_series_uid in anon_series_uids:
                    self.anonymizer.model.remove_uid_inverse(anon_series_uid)

                # Remove StudyInstanceUID from AnonymizerModel UID Map:
                self.anonymizer.model.remove_uid_inverse(anon_study_uid)

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
            logger.error(
                f"Critical Error removing phi data for AnonStudyUID: {anon_study_uid} AnonPatientID: {anon_pt_id}"
            )
            return False

        logger.info(f"PHI data removed for StudyUID: {anon_study_uid} PatientID: {anon_pt_id} successfully")
        return True

    def create_phi_csv(self) -> Path | str:
        """
        Create a PHI (Protected Health Information) CSV file.

        Writes one denormalized row per series (study/patient keys repeated), matching
        PHI_IndexRecord + PHI_SeriesIndexRecord. Studies with no series emit one row
        with empty series columns.

        Returns:
            Path | str: The path to the generated PHI CSV file if successful, otherwise an error message.
        """
        logger.info("Create PHI CSV")

        phi_index: List[PHI_IndexRecord] | None = self.get_phi_index_records()

        if not phi_index:
            logger.error("No Studies/PHI data in Anonymizer Model")
            return _("No Studies in Anonymizer Model")

        patient_count, study_count, series_count = PHI_IndexRecord.lookup_csv_entity_counts(phi_index)
        os.makedirs(self.model.phi_export_dir(), exist_ok=True)
        filename = f"{self.model.site_id}_{self.model.project_name}_PHI_{patient_count}_{study_count}_{series_count}.csv"
        phi_csv_path = Path(self.model.phi_export_dir(), filename)

        try:
            write_lookup_csv(phi_csv_path, phi_index)
            logger.info(
                "PHI saved to: %s (%d patients, %d studies, %d series)",
                phi_csv_path,
                patient_count,
                study_count,
                series_count,
            )
        except Exception as e:
            logger.error(f"Error writing PHI CSV: {e}")
            return repr(e)

        return phi_csv_path

    def get_phi_index_records(self) -> list[PHI_IndexRecord] | None:
        """Return PHI dataset rows with study-level AI processing status (via phi_io)."""
        return build_phi_index(self.anonymizer.model)

    def import_java_phi_studies(self, java_studies: list[JavaAnonymizerExportedStudy]) -> None:
        """Import Java Anonymizer exported studies into the PHI ORM store."""
        phi_io_import_java_phi_studies(self.anonymizer.model, java_studies)

    def series_is_harmonized(self, anon_series_uid: str) -> bool:
        return self.anonymizer.model.series_is_harmonized(anon_series_uid)

    def series_has_face_blur(self, anon_series_uid: str) -> bool:
        return self.anonymizer.model.series_has_face_blur(anon_series_uid)

    def get_series_processing_status(self, anon_series_uid: str) -> SeriesProcessingStatus | None:
        return self.anonymizer.model.get_series_processing_status(anon_series_uid)

    def format_series_processing_status(
        self,
        status: SeriesProcessingStatus,
        *,
        include_face_blur: bool = True,
    ) -> str:
        return format_series_processing_status(status, include_face_blur=include_face_blur)

    def get_phi_by_anon_patient_id(self, anon_patient_id: str) -> PHI | None:
        return self.anonymizer.model.get_phi_by_anon_patient_id(anon_patient_id)

    def get_totals(self):
        return self.anonymizer.model.get_totals()

    def get_imported_modalities(self) -> list[str]:
        return self.anonymizer.model.get_imported_modalities()

    def clear_series_tseg_cache(
        self,
        series_path: Path,
        anon_series_uid: str | None = None,
        *,
        also_clear_annotations: bool = False,
    ) -> None:
        from anonymizer.controller.ai.tseg.cache import clear_series_tseg_cache

        clear_series_tseg_cache(
            series_path,
            anon_model=self.anonymizer.model,
            anon_series_uid=anon_series_uid,
            also_clear_annotations=also_clear_annotations,
        )

    def harmonize_studies(
        self,
        studies: list[tuple[str, str]],
        *,
        progress: HarmonizeStudiesProgressCallback | None = None,
        cancelled: HarmonizeStudiesCancelledCallback | None = None,
        on_outcome: HarmonizeStudiesLogCallback | None = None,
    ) -> HarmonizeStudiesSummary:
        """Run unattended harmonize for all CT series under the selected studies."""
        return harmonize_studies_batch(
            self.model.images_dir(),
            studies,
            anon_model=self.anonymizer.model,
            progress=progress,
            cancelled=cancelled,
            on_outcome=on_outcome,
        )

    def ai_batch_process(
        self,
        studies: list[tuple[str, str]],
        options: AiBatchProcessOptions,
        *,
        progress: AiBatchProgressCallback | None = None,
        cancelled: AiBatchCancelledCallback | None = None,
        on_log: AiBatchWorkflowLogCallback | None = None,
        memory_callback: AiBatchMemoryCallback | None = None,
        work_state: WorkState | None = None,
    ) -> AiBatchSummary:
        """Run selected AI algorithms sequentially for series under selected studies."""
        return ai_batch_process(
            self.model.images_dir(),
            studies,
            options,
            anon_model=self.anonymizer.model,
            anon_controller=self.anonymizer,
            project_model=self.model,
            progress=progress,
            cancelled=cancelled,
            on_log=on_log,
            memory_callback=memory_callback,
            work_state=work_state,
        )
