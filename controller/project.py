import os
from typing import cast
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import logging
import time
import pickle
import csv
from pathlib import Path
from typing import List
from dataclasses import dataclass
from utils.translate import _
from utils.logging import set_logging_levels
from pydicom import Dataset
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
    C_FAILURE,
    C_STORE_DATASET_ERROR,
    C_STORE_DECODE_ERROR,
)
from model.project import (
    ProjectModel,
    PHI,
    DICOMNode,
    NetworkTimeouts,
    DICOMRuntimeError,
)
from .anonymizer import AnonymizerController
import boto3


logger = logging.getLogger(__name__)


@dataclass
class FindRequest:
    scp_name: str
    name: str
    id: str
    acc_no: str | list[str]
    study_date: str
    modality: str
    ux_Q: Queue


@dataclass
class FindResponse:
    status: Dataset
    identifier: Dataset | None


@dataclass
class ExportRequest:
    dest_name: str
    patient_ids: list[str]  # list of patient IDs to export
    ux_Q: Queue  # queue for UX updates for the full export


@dataclass
class ExportResponse:
    patient_id: str
    files_sent: int  # incremented for each file sent successfully
    error: str | None  # error message
    complete: bool


@dataclass
class MoveRequest:
    scp_name: str
    dest_scp_ae: str
    study_uids: list[str]
    ux_Q: Queue


class ProjectController(AE):
    # DICOM service class uids:
    _VERIFICATION_CLASS = "1.2.840.10008.1.1"  # Echo
    _STUDY_ROOT_QR_CLASSES = [
        "1.2.840.10008.5.1.4.1.2.2.1",  # Find
        "1.2.840.10008.5.1.4.1.2.2.2",  # Move
        "1.2.840.10008.5.1.4.1.2.2.3",  # Get
    ]
    _maximum_pdu_size = 0  # no limit
    _handle_store_time_slice_interval = 0.1  # seconds
    _export_file_time_slice_interval = 0.1  # seconds
    _patient_export_thread_pool_size = 4
    _study_move_thread_pool_size = 4
    _query_result_required_attributes = [
        "PatientID",
        "PatientName",
        "StudyInstanceUID",
        # "StudyDate",
        # "AccessionNumber",
        "ModalitiesInStudy",
        "NumberOfStudyRelatedSeries",
        "NumberOfStudyRelatedInstances",
    ]
    _query_result_fields_to_remove = [
        "QueryRetrieveLevel",
        "RetrieveAETitle",
        "SpecificCharacterSet",
    ]

    def _missing_query_result_attributes(self, ds: Dataset) -> list[str]:
        return [
            attr_name
            for attr_name in self._query_result_required_attributes
            if attr_name not in ds or getattr(ds, attr_name) == ""
        ]

    def _strip_query_result_fields(self, ds: Dataset) -> None:
        for field in self._query_result_fields_to_remove:
            if field in ds:
                delattr(ds, field)

    def __init__(self, model: ProjectModel):
        super().__init__(model.scu.aet)
        self.model = model
        set_logging_levels(model.logging_levels)
        # Make sure storage directory exists:
        os.makedirs(self.model.storage_dir, exist_ok=True)
        self.set_dicom_timeouts(model.network_timeouts)
        # TODO: maintain list of allowed calling AET's and use: def require_calling_aet(self, ae_titles: List[str]) -> None:
        self.require_called_aet = True
        # self.require_calling_aet = ["MDEDEV"]
        self.set_radiology_storage_contexts()
        self.set_verification_context()
        self._reset_scp_vars()
        self.anonymizer = AnonymizerController(model)

    def _reset_scp_vars(self):
        self._abort_query = False
        self._abort_move = False
        self._abort_export = False
        self._export_futures = []
        self._export_executor = None
        self._move_futures = []
        self._move_executor = None
        self.scp = None
        self.s3 = None

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

    def save_model(self, dest_dir: str = None) -> bool:
        if dest_dir is None:
            dest_dir = self.model.storage_dir
        project_pkl_path = Path(dest_dir, ProjectModel.default_project_filename())
        with open(project_pkl_path, "wb") as pkl_file:
            pickle.dump(self.model, pkl_file)
        logger.info(f"Model saved to: {project_pkl_path}")

    @property
    def storage_dir(self):
        return self.model.storage_dir

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
        self.add_supported_context(
            self._VERIFICATION_CLASS, self.model.transfer_syntaxes
        )
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
            build_context(
                abstract_syntax, "1.2.840.10008.1.2.2"
            )  # Explicit VR Big Endian,
            for abstract_syntax in self.model.storage_classes
        ]

    def get_study_root_qr_contexts(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, self.model.transfer_syntaxes)
            for abstract_syntax in self._STUDY_ROOT_QR_CLASSES
        ]

    # Handlers:
    def _handle_abort(self, event: Event):
        logger.error("_handle_abort")
        # if self._move_futures:
        #     logger.error("Aborting move futures")
        #     self._abort_move = True

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
        time.sleep(self._handle_store_time_slice_interval)
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

        remote_scu = DICOMNode(
            remote["address"], remote["port"], remote["ae_title"], False
        )
        logger.debug(remote_scu)

        # DICOM Dataset integrity checking:
        missing_attributes = self.anonymizer.missing_attributes(ds)
        if missing_attributes != []:
            logger.error(
                f"Incoming dataset is missing required attributes: {missing_attributes}"
            )
            logger.error(f"\n{ds}")
            return C_STORE_DATASET_ERROR

        if self.anonymizer.model.get_anon_uid(ds.SOPInstanceUID):
            logger.info(f"Instance already stored:{ds.PatientID}/{ds.SOPInstanceUID}")
            return C_SUCCESS

        logger.info(
            f"=>{ds.PatientID}/{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}"
        )

        self.anonymizer.anonymize_dataset_and_store(remote_scu, ds, self.storage_dir)
        return C_SUCCESS

    def start_scp(self) -> None:
        logger.info(f"start {self.model.scp}, {self.model.storage_dir}...")

        if self.scp:
            msg = _(f"DICOM C-STORE scp is already running on {self.model.scp}")
            logger.error(msg)
            raise DICOMRuntimeError(msg)

        handlers = [(EVT_C_ECHO, self._handle_echo), (EVT_C_STORE, self._handle_store)]
        self._reset_scp_vars()
        self.ae_title = self.model.scu.aet

        try:
            self.scp = self.start_server(
                (self.model.scp.ip, self.model.scp.port),
                block=False,
                evt_handlers=cast(List[EventHandlerType], handlers),
            )
        except Exception as e:
            msg = _(
                f"Failed to start DICOM C-STORE scp on {self.model.scp}, Error: {str(e)}"
            )
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
            logger.debug(
                f"Association established with {association.acceptor.ae_title}"
            )
        except Exception as e:  # (ConnectionError, TimeoutError, RuntimeError) as e:
            logger.error(f"Error establishing association: {e}")
            raise

        return association

    def echo(self, scp: str | DICOMNode) -> bool:
        logger.info(f"Perform C-ECHO from {self.model.scu} to {scp}")
        association = None
        try:
            association = self._connect_to_scp(scp, [self.get_verification_context()])
            status = (Dataset)(association.send_c_echo())
            if not status:
                raise ConnectionError(
                    "Connection timed out, was aborted, or received an invalid response"
                )
            if status.Status == C_SUCCESS:
                logger.info(f"C-ECHO Success")
                association.release()
                return True
            else:
                logger.error(status)
                logger.error(
                    f"C-ECHO Failed status: {VERIFICATION_SERVICE_CLASS_STATUS[status.Status][1]}"
                )
                association.release()
                return False

        except Exception as e:
            logger.error(
                f"Failed DICOM C-ECHO from from {self.model.scu} to {scp}, Error: {(e)}"
            )
            if association:
                association.release()
            return False

    def aws_S3_authenticate(self) -> tuple[bool, str | None]:
        logging.info(f"Authenticate to AWS S3")
        if self.s3:
            logging.info(f"Already authenticated to AWS S3, verify bucket list")
            try:
                response = self.s3.list_buckets()
                logging.info(
                    f"Authentication is valid. S3 buckets:", response["Buckets"]
                )
                return True
            except Exception as e:
                logging.error("s3_list_buckets failed. Error:", e)
                self.s3 = None

        try:
            cognito_client = boto3.client("cognito-idp", region_name="us-east-1")

            response = cognito_client.initiate_auth(
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": self.model.aws_cognito.username,
                    "PASSWORD": self.model.aws_cognito.password,
                },
                ClientId=self.model.aws_cognito.client_id,
            )

            if response["ChallengeName"] == "NEW_PASSWORD_REQUIRED":
                msg = _("User needs to set a new password")
                logging.error(msg)
                return False, msg

            if "ChallengeName" in response:
                msg = _(
                    f"Unexpected Authorisation Challenge : {response['ChallengeName']}"
                )
                logging.error(msg)
                return False, msg

            if "AuthenticationResult" not in response:
                logging.error(f"AuthenticationResult not in response: {response}")
                return False, _(
                    "AWS Cognito authorisation failed\n Authentication Result & Access Token not in response"
                )

            if "AccessToken" not in response["AuthenticationResult"]:
                logging.error(f"AccessToken not in response: {response}")
                return False, _(
                    "AWS Cognito authorisation failed\n Access Token not in response"
                )

            session_token = response["AuthenticationResult"]["AccessToken"]

            response = cognito_client.get_user(AccessToken=session_token)

            logger.info(f"Cognito Authentication successful. User Details: {response}")

            return True, None

        except Exception as e:
            msg = _(f"AWS Authentication failed: {str(e)}")
            logging.error(msg)
            return False, msg

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
                dcm_response: Dataset = association.send_c_store(
                    dataset=dicom_file_path
                )
                if dcm_response.Status != 0:
                    raise DICOMRuntimeError(
                        f"DICOM Response: {STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}"
                    )
                files_sent += 1

        except Exception as e:
            logger.error(f"Send Error: {e}")
            raise
        finally:
            if association:
                association.release()
            return files_sent

    # Blocking: Query remote server for studies matching the given query dataset:
    def find(
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
        logger.info(
            f"C-FIND to {scp} Study Level Query: {name}, {id}, {acc_no}, {study_date}, {modality}"
        )

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.PatientName = name
        ds.PatientID = id
        ds.AccessionNumber = acc_no
        ds.StudyDate = study_date
        ds.ModalitiesInStudy = modality
        ds.NumberOfStudyRelatedSeries = ""
        ds.NumberOfStudyRelatedInstances = ""
        ds.StudyDescription = ""
        ds.StudyInstanceUID = ""

        results = []
        error_msg = ""
        query_association = None
        self._abort_query = False
        try:
            query_association = self._connect_to_scp(
                scp_name, self.get_study_root_qr_contexts()
            )

            responses = query_association.send_c_find(
                ds,
                query_model=self._STUDY_ROOT_QR_CLASSES[0],
            )

            for status, identifier in responses:
                if self._abort_query:
                    raise RuntimeError("Query aborted")

                # Timeouts (Network & DIMSE) are reflected by status being None:
                if not status:
                    raise ConnectionError(
                        "Connection timed out (DIMSE or IDLE), was aborted, or received an invalid response"
                    )

                if status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                ):
                    logger.error(f"C-FIND failure, status: {hex(status.Status)}")
                    raise DICOMRuntimeError(
                        f"C-FIND Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status]}"
                    )

                if status.Status == C_SUCCESS:
                    logger.info("C-FIND query success")

                if identifier:
                    if verify_attributes:
                        missing_attributes = self._missing_query_result_attributes(
                            identifier
                        )
                        if missing_attributes != []:
                            logger.error(
                                f"Query result is missing required attributes: {missing_attributes}"
                            )
                            logger.error(f"\n{identifier}")
                            continue

                    self._strip_query_result_fields(identifier)

                    results.append(identifier)

                if ux_Q:
                    ux_Q.put(FindResponse(status, identifier))

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
                ux_Q.put(FindResponse(ds, None))

        finally:
            if query_association:
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
    def find_acc_nos(
        self,
        scp_name: str,
        acc_no_list: list,
        ux_Q=None,
        verify_attributes=True,
    ) -> list[Dataset] | None:
        assert scp_name in self.model.remote_scps
        scp = self.model.remote_scps[scp_name]
        logger.info(
            f"C-FIND to {scp} Accession Query: {len(acc_no_list)} accession numbers..."
        )
        logger.debug(f"{acc_no_list}")

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.PatientName = ""
        ds.PatientID = ""
        ds.StudyDate = ""
        ds.ModalitiesInStudy = ""
        ds.NumberOfStudyRelatedSeries = ""
        ds.NumberOfStudyRelatedInstances = ""
        ds.StudyDescription = ""
        ds.StudyInstanceUID = ""

        results = []
        error_msg = ""
        query_association = None
        self._abort_query = False
        try:
            query_association = self._connect_to_scp(
                scp_name, self.get_study_root_qr_contexts()
            )

            for acc_no in acc_no_list:
                if self._abort_query:
                    raise RuntimeError("Query aborted")

                if acc_no == "":
                    continue

                ds.AccessionNumber = acc_no

                responses = query_association.send_c_find(
                    ds,
                    query_model=self._STUDY_ROOT_QR_CLASSES[0],
                )

                # Process the response(s) received from the peer
                # one response with C_PENDING with identifier and one response with C_SUCCESS and no identifier
                for status, identifier in responses:
                    if not status:
                        raise ConnectionError(
                            "Connection timed out, was aborted, or received an invalid response"
                        )
                    if status.Status not in (
                        C_SUCCESS,
                        C_PENDING_A,
                        C_PENDING_B,
                    ):
                        logger.error(f"C-FIND failure, status: {hex(status.Status)}")
                        raise DICOMRuntimeError(
                            f"C-FIND Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status][1]}"
                        )

                    if identifier:
                        if verify_attributes:
                            missing_attributes = self._missing_query_result_attributes(
                                identifier
                            )
                            if missing_attributes != []:
                                logger.error(
                                    f"Query result is missing required attributes: {missing_attributes}"
                                )
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
                            ux_Q.put(FindResponse(status, identifier))

            # Signal success to UX once full list of accession numbers has been processed
            if ux_Q:
                logger.info(f"Find Accession Numbers complete")
                ds = Dataset()
                ds.Status = C_SUCCESS
                ux_Q.put(FindResponse(ds, None))

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
                ux_Q.put(FindResponse(ds, None))

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
    def find_ex(self, fr: FindRequest) -> None:
        if isinstance(fr.acc_no, list):
            logger.info("Find accession numbers")
            # Due to client removing numbers as they are found, make a copy of the list:
            if isinstance(fr.acc_no, list):
                acc_no_list = fr.acc_no.copy()
                fr.acc_no = acc_no_list

            threading.Thread(
                target=self.find_acc_nos,
                args=(
                    fr.scp_name,
                    fr.acc_no,
                    fr.ux_Q,
                ),
                daemon=True,
            ).start()
        else:
            logger.info("Find")
            threading.Thread(
                target=self.find,
                args=(
                    fr.scp_name,
                    fr.name,
                    fr.id,
                    fr.acc_no,
                    fr.study_date,
                    fr.modality,
                    fr.ux_Q,
                ),
                daemon=True,
            ).start()

    def abort_query(self):
        logger.info("Abort Query")
        self._abort_query = True

    def find_uids(
        self, scp_name: str, study_uid: str, find_series: bool
    ) -> list[str] | None:
        assert scp_name in self.model.remote_scps
        scp = self.model.remote_scps[scp_name]
        logger.info(
            f"find_uids: C-FIND to {scp} study_uid={study_uid}, find_series={find_series}"
        )
        ds = Dataset()
        ds.QueryRetrieveLevel = "SERIES" if find_series else "IMAGE"
        ds.StudyInstanceUID = study_uid
        if find_series:
            ds.SeriesInstanceUID = ""
        else:
            ds.SOPInstanceUID = ""

        results = []
        query_association = None
        self._abort_query = False
        try:
            query_association = self._connect_to_scp(
                scp_name, self.get_study_root_qr_contexts()
            )

            responses = query_association.send_c_find(
                ds,
                query_model=self._STUDY_ROOT_QR_CLASSES[0],
            )

            for status, identifier in responses:
                if self._abort_query:
                    raise RuntimeError("Query aborted")
                if not status:
                    raise ConnectionError(
                        "Connection timed out, was aborted, or received an invalid response"
                    )
                if status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                ):
                    logger.error(f"C-FIND failure, status: {hex(status.Status)}")
                    raise DICOMRuntimeError(
                        f"C-FIND Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status]}"
                    )

                if status.Status == C_SUCCESS:
                    logger.info("C-FIND query success")

                if identifier:
                    results.append(
                        identifier.SeriesInstanceUID
                    ) if find_series else results.append(identifier.SOPInstanceUID)

        except Exception as e:
            logger.error(str(e))

        finally:
            if query_association:
                query_association.release()

        if len(results) == 0:
            logger.info(f"No uids found for {study_uid}")

        return results

    # Blocking Move Study:
    def _move_study(
        self,
        scp_name: str,
        dest_scp_ae: str,
        study_uid: str,
        ux_Q: Queue,
    ) -> None:
        logger.info(
            f"C-MOVE scp:{scp_name} move to: {dest_scp_ae} study_uid: {study_uid}"
        )

        if self._abort_move:
            raise RuntimeError("Move aborted")

        move_association = None
        error_msg = ""
        try:
            move_association = self._connect_to_scp(
                scp=scp_name,
                contexts=[
                    build_context(
                        self._STUDY_ROOT_QR_CLASSES[1], self.model.transfer_syntaxes
                    )
                ],
            )

            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.StudyInstanceUID = study_uid

            # Use the C-MOVE service to request that the remote SCP move the Study to local storage scp:
            responses = move_association.send_c_move(
                dataset=ds,
                move_aet=dest_scp_ae,
                query_model=self._STUDY_ROOT_QR_CLASSES[1],
                priority=1,
            )

            # Process the responses received from the remote scp:
            for status, identifier in responses:
                if self._abort_move:
                    logger.error(f"_move_study study_uid: {study_uid} aborted")
                    move_association.abort()
                    while not ux_Q.empty():
                        ux_Q.get()
                    return

                if not status:
                    raise ConnectionError(
                        _(
                            f"Connection timed out or aborted moving study_uid: {study_uid}"
                        )
                    )

                if status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                ):
                    logger.error(f"C-MOVE failure, status: {hex(status.Status)}")
                    if identifier:
                        logger.error(identifier)
                    raise DICOMRuntimeError(
                        f"C-MOVE Failed: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                    )

                if status.Status == C_SUCCESS:
                    logger.info(f"C-MOVE success study_uid: {study_uid}")

                # Add the study_uid to the status dataset:
                status.StudyInstanceUID = study_uid
                ux_Q.put(status)

            logger.info(f"C-MOVE complete study_uid: {study_uid}")

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
                ds.StudyInstanceUID = study_uid
                ux_Q.put(ds)

        finally:
            # Release the association
            if move_association:
                move_association.release()

    # Manage bulk patient move using a thread pool:
    def _manage_move(self, req: MoveRequest) -> None:
        self._move_futures = []

        self._move_executor = ThreadPoolExecutor(
            max_workers=self._study_move_thread_pool_size
        )

        with self._move_executor as executor:
            for i in range(len(req.study_uids)):
                future = executor.submit(
                    self._move_study,
                    req.scp_name,
                    req.dest_scp_ae,
                    req.study_uids[i],
                    req.ux_Q,
                )
                self._move_futures.append(future)

            logger.info(f"Move Futures: {len(self._move_futures)}")

            # Check for exceptions in the completed futures
            for future in self._move_futures:
                try:
                    # This will raise any exceptions that _move_study may have raised:
                    future.result()
                except Exception as e:
                    # Handle specific exceptions if needed
                    if not self._abort_move:
                        logger.error(f"Exception caught in _manage_move: {e}")

        logger.info("_manage_move complete")

    # Non-blocking Move Studies:
    def move_studies(self, mr: MoveRequest) -> None:
        self._abort_move = False
        threading.Thread(
            target=self._manage_move,
            args=(mr,),
            daemon=True,
        ).start()

    def abort_move(self):
        logger.info("Abort Move")
        self._abort_move = True
        # logger.info("Cancel Futures")
        # for future in self._move_futures:
        #     future.cancel()
        if self._move_executor:
            self._move_executor.shutdown(wait=True, cancel_futures=True)
            logger.info("Move futures cancelled and executor shutdown")
            self._move_executor = None

    def _export_patient(self, dest_name: str, patient_id: str, ux_Q: Queue) -> None:
        logger.debug(f"_export_patient {patient_id} start to {dest_name}")

        export_association = None
        files_sent = 0
        try:
            # Load DICOM files to send from active local storage directory for this patient:
            patient_dir = Path(self.model.storage_dir, patient_id)

            if not patient_dir.exists():
                raise ValueError(f"Selected directory {patient_dir} does not exist")

            file_paths = []
            for root, _, files in os.walk(patient_dir):
                file_paths.extend(
                    os.path.join(root, file) for file in files if file.endswith(".dcm")
                )

            if len(file_paths) == 0:
                raise DICOMRuntimeError(f"No DICOM files found in {patient_dir}")

            # Connect to remote SCP:
            if self.model.export_to_AWS:
                self
            export_association = self._connect_to_scp(
                dest_name, self.get_radiology_storage_contexts()
            )

            for dicom_file_path in file_paths:
                time.sleep(self._export_file_time_slice_interval)
                if self._abort_export:
                    logger.error(f"_export_patient patient_id: {patient_id} aborted")
                    export_association.abort()
                    while not ux_Q.empty():
                        ux_Q.get()
                    return

                dcm_response: Dataset = export_association.send_c_store(
                    dataset=dicom_file_path
                )

                if not hasattr(dcm_response, "Status"):
                    raise TimeoutError("send_c_store timeout")

                if dcm_response.Status != 0:
                    raise DICOMRuntimeError(
                        f"{STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}"
                    )

                files_sent += 1
                # TODO: notify UX in batches of 10 files sent?
                ux_Q.put(ExportResponse(patient_id, files_sent, None, False))

            # Successful export:
            ux_Q.put(ExportResponse(patient_id, files_sent, None, True))

        except Exception as e:
            if not self._abort_export:
                logger.error(f"Export Patient {patient_id} Error: {e}")
            ux_Q.put(ExportResponse(patient_id, files_sent, f"{e}", True))

        finally:
            if export_association:
                export_association.release()

        return

    # Manage bulk patient export using a thread pool:
    def _manage_export(self, req: ExportRequest) -> None:
        self._export_futures = []

        self._export_executor = ThreadPoolExecutor(
            max_workers=self._patient_export_thread_pool_size
        )

        with self._export_executor as executor:
            for i in range(len(req.patient_ids)):
                future = executor.submit(
                    self._export_patient, req.dest_name, req.patient_ids[i], req.ux_Q
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

    # Non-blocking export_patients:
    def export_patients(self, er: ExportRequest) -> None:
        self._abort_export = False
        self._export_patients_thread = threading.Thread(
            target=self._manage_export,
            args=(er,),
            daemon=True,
        )
        self._export_patients_thread.start()

    def abort_export(self):
        logger.info("Abort Export")
        self._abort_export = True
        # logger.info("Cancel Futures")
        # for future in self._move_futures:
        #     future.cancel()
        if self._export_executor:
            self._export_executor.shutdown(wait=True, cancel_futures=True)
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
                        phi.patient_id,
                        study.anon_date_delta,
                        study.study_date,
                        self.anonymizer.model._acc_no_lookup[study.accession_number],
                        study.accession_number,
                        self.anonymizer.model._uid_lookup[study.study_uid],
                        study.study_uid,
                    )
                )

        filename = (
            f"{self.model.site_id}_{self.model.project_name}_PHI_{len(phi_data)}.csv"
        )
        phi_csv_path = Path(self.model.storage_dir, filename)

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
