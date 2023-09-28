import os
from typing import cast
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import logging
import time
import pickle
from pathlib import Path
from typing import List
from dataclasses import dataclass
from pydicom import Dataset
from pynetdicom.association import Association
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import PresentationContext, build_context
from pynetdicom.events import Event, EVT_C_STORE, EVT_C_ECHO, EventHandlerType
from pynetdicom.status import (
    VERIFICATION_SERVICE_CLASS_STATUS,
    STORAGE_SERVICE_CLASS_STATUS,
    QR_FIND_SERVICE_CLASS_STATUS,
    QR_MOVE_SERVICE_CLASS_STATUS,
)
from .dicom_C_codes import (
    C_SUCCESS,
    C_DATA_ELEMENT_DOES_NOT_EXIST,
    C_PENDING_A,
    C_PENDING_B,
    C_FAILURE,
)

from model.project import (
    ProjectModel,
    DICOMNode,
    DICOMRuntimeError,
    default_project_filename,
)
from .anonymizer import AnonymizerController

from utils.translate import _

logger = logging.getLogger(__name__)


@dataclass
class FindRequest:
    scp_name: str
    name: str
    id: str
    acc_no: str
    study_date: str
    modality: str
    ux_Q: Queue


@dataclass
class FindResponse:
    status: Dataset
    identifier: Dataset | None


@dataclass
class ExportRequest:
    scp_name: str
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
    _handle_store_time_slice_interval = 0.1  # seconds
    _patient_export_thread_pool_size = 4
    _study_move_thread_pool_size = 4

    def __init__(self, model: ProjectModel):
        super().__init__(model.scu.aet)
        self.model = model
        # Make sure storage directory exists:
        os.makedirs(self.model.storage_dir, exist_ok=True)
        self.set_all_timeouts(model.network_timeout)
        # TODO: maintain list of allowed calling AET's and use: def require_calling_aet(self, ae_titles: List[str]) -> None:
        self._require_called_aet = True
        self.set_radiology_storage_contexts()
        self.set_verification_context()
        self.maximum_pdu_size = 0  # no limit
        self._handle_store_time_slice_interval = 0.1  # seconds
        self.scp = None
        self.start_scp()
        self.anonymizer = AnonymizerController(model)

    def __str__(self):
        return super().__str__() + f"\n{self.model}" + f"\n{self.anonymizer.model}"

    def save_model(self):
        project_pkl_path = Path(self.model.storage_dir, default_project_filename())
        with open(project_pkl_path, "wb") as pkl_file:
            pickle.dump(self.model, pkl_file)
        logger.info(f"Model saved to: {project_pkl_path}")

    @property
    def storage_dir(self):
        return self.model.storage_dir

    # Set *all* AE timeouts to the global network timeout:
    def set_all_timeouts(self, timeout):
        self._acse_timeout = timeout
        self._dimse_timeout = timeout
        self._network_timeout = timeout
        self._connection_timeout = timeout

    def get_network_timeout(self) -> int:
        return self.model.network_timeout

    # FOR SCP AE: Set allowed storage and verification contexts and corresponding transfer syntaxes
    def set_verification_context(self):
        self.add_supported_context(
            self._VERIFICATION_CLASS, self.model._TRANSFER_SYNTAXES
        )
        return

    def set_radiology_storage_contexts(self) -> None:
        for uid in sorted(self.model._RADIOLOGY_STORAGE_CLASSES.values()):
            self.add_supported_context(uid, self.model._TRANSFER_SYNTAXES)
        return

    # FOR SCU Association:
    def get_verification_context(self) -> PresentationContext:
        return build_context(
            self._VERIFICATION_CLASS, self.model._TRANSFER_SYNTAXES
        )  # do not include compressed transfer syntaxes

    def get_radiology_storage_contexts(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, self.model._TRANSFER_SYNTAXES)
            for abstract_syntax in self.model._RADIOLOGY_STORAGE_CLASSES.values()
        ]

    def set_study_root_qr_contexts(self) -> None:
        for uid in sorted(self._STUDY_ROOT_QR_CLASSES):
            self.add_supported_context(uid, self.model._TRANSFER_SYNTAXES)
        return

    # For testing:
    def get_radiology_storage_contexts_BIGENDIAN(self) -> List[PresentationContext]:
        return [
            build_context(
                abstract_syntax, "1.2.840.10008.1.2.2"
            )  # Explicit VR Big Endian,
            for abstract_syntax in self.model._RADIOLOGY_STORAGE_CLASSES.values()
        ]

    def get_study_root_qr_contexts(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, self.model._TRANSFER_SYNTAXES)
            for abstract_syntax in self._STUDY_ROOT_QR_CLASSES
        ]

    # Handlers:
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
        ds = event.dataset
        ds.file_meta = event.file_meta
        remote_scu = DICOMNode(
            remote["address"], remote["port"], remote["ae_title"], False
        )
        logger.debug(remote_scu)
        self.anonymizer.anonymize_dataset_and_store(remote_scu, ds, self.storage_dir)
        return C_SUCCESS

    from typing import cast

    # ...

    def start_scp(self) -> None:
        logger.info(f"start {self.model.scp}, {self.model.storage_dir}...")

        if self.scp:
            msg = _(f"DICOM C-STORE scp is already running on {self.model.scp}")
            logger.error(msg)
            raise DICOMRuntimeError(msg)

        handlers = [(EVT_C_ECHO, self._handle_echo), (EVT_C_STORE, self._handle_store)]

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
            f"DICOM C-STORE scp listening on {self.model.scp}, storing files in {self.model.storage_dir}"
        )

    def stop_scp(self) -> None:
        if not self.scp:
            return
        logger.info("Stop {scu.aet} scp and close socket")
        self.scp.shutdown()
        self.scp = None

    def connect(self, scp_name: str, contexts=None) -> Association:
        association = None
        try:
            if scp_name not in self.model.remote_scps:
                raise ConnectionError(f"Remote SCP {scp_name} not found")
            remote_scp = self.model.remote_scps[scp_name]

            association = self.associate(
                remote_scp.ip,
                remote_scp.port,
                contexts=contexts,
                ae_title=remote_scp.aet,
                bind_address=(self.model.scu.ip, 0),
            )
            if not association.is_established:
                raise ConnectionError(f"Connection error to: {remote_scp}")
            logger.debug(
                f"Association established with {association.acceptor.ae_title}"
            )
        except (ConnectionError, TimeoutError, RuntimeError) as e:
            logger.error(f"Error establishing association: {e}")
            raise
        return association

    def echo(self, scp_name: str) -> bool:
        logger.debug(
            f"C-ECHO from {self.model.scu} to {self.model.remote_scps[scp_name]}"
        )
        association = None
        try:
            association = self.connect(scp_name, [self.get_verification_context()])
            status = (Dataset)(association.send_c_echo())
            if not status:
                raise ConnectionError(
                    "Connection timed out, was aborted, or received an invalid response"
                )
            if status.Status == C_SUCCESS:
                logger.debug(f"C-ECHO Success")
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
                f"Failed DICOM C-ECHO from from {self.model.scu} to {scp_name}, Error: {(e)}"
            )
            if association:
                association.release()
            return False

    # Blocking send, raises (ConnectionError,TimeoutError,DICOMRuntimeError,RuntimeError,AttributeError,ValueError)
    def send(self, file_paths: list[str], scp_name: str, send_contexts=None):
        logger.info(f"Send {len(file_paths)} files to {scp_name}")
        association = None
        if send_contexts is None:
            send_contexts = self.get_radiology_storage_contexts()
        files_sent = 0
        try:
            association = self.connect(scp_name, send_contexts)
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
    ) -> list[Dataset] | None:
        assert scp_name in self.model.remote_scps
        scp = self.model.remote_scps[scp_name]
        logger.info(
            f"C-FIND to {scp} Query: {name}, {id}, {acc_no}, {study_date}, {modality}"
        )

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.PatientName = name
        ds.PatientID = id
        ds.AccessionNumber = acc_no
        ds.StudyDate = study_date
        ds.ModalitiesInStudy = modality
        ds.NumberOfStudyRelatedSeries = 0
        ds.NumberOfStudyRelatedInstances = 0
        ds.StudyDescription = ""
        ds.StudyInstanceUID = ""

        results = []
        assoc = None
        error_msg = ""
        association = None
        try:
            association = self.connect(scp_name, self.get_study_root_qr_contexts())
            # Use the C-FIND service to send the identifier
            # using the StudyRootQueryRetrieveInformationModelFind
            responses = association.send_c_find(
                ds,
                query_model=self._STUDY_ROOT_QR_CLASSES[0],
            )

            # Process the responses received from the peer
            for status, identifier in responses:
                if not status or status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                ):
                    if not status:
                        raise ConnectionError(
                            "Connection timed out, was aborted, or received an invalid response"
                        )
                    else:
                        raise DICOMRuntimeError(
                            f"C-FIND Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status][1]}"
                        )
                else:
                    if status.Status == C_SUCCESS:
                        logger.info("C-FIND query success")

                    if identifier:
                        # TODO: move this code to UX client?
                        fields_to_remove = [
                            "QueryRetrieveLevel",
                            "RetrieveAETitle",
                            "SpecificCharacterSet",
                        ]
                        for field in fields_to_remove:
                            if field in identifier:
                                delattr(identifier, field)

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
            if association:
                association.release()

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

    def _export_patient(self, scp_name: str, patient_id: str, ux_Q: Queue) -> None:
        logger.debug(f"_export_patient {patient_id} start")

        association = None
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

            association = self.connect(scp_name, self.get_radiology_storage_contexts())

            for dicom_file_path in file_paths:
                dcm_response: Dataset = association.send_c_store(
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

        except Exception as e:
            logger.error(f"Export Patient {patient_id} Error: {e}")
            # TERMINATE patient export on ANY error:
            ux_Q.put(ExportResponse(patient_id, files_sent, f"{e}", True))
            # For all errors other than DICOMRuntimeError, terminate the full export
            # by raiseing the exception in the ThreadPoolExecutor:
            if not isinstance(e, DICOMRuntimeError):
                raise
            else:
                return

        finally:
            # Successful export:
            ux_Q.put(ExportResponse(patient_id, files_sent, None, True))
            if association:
                association.release()

        return

    # Manage bulk patient export using a thread pool:
    def _manage_export(self, req: ExportRequest) -> None:
        futures = []

        with ThreadPoolExecutor(
            max_workers=self._patient_export_thread_pool_size
        ) as executor:
            for i in range(len(req.patient_ids)):
                future = executor.submit(
                    self._export_patient, req.scp_name, req.patient_ids[i], req.ux_Q
                )
                futures.append(future)

            # Check for exceptions in the completed futures
            for future in futures:
                try:
                    # This will raise any exceptions that _export_patient might have raised.
                    future.result()
                except Exception as e:
                    # Handle specific exceptions if needed
                    logger.error(f"An error occurred during export: {e}")
                    # Shutdown executor in case of critical error
                    executor.shutdown(wait=False)
                    break

    # Non-blocking export_patients:
    def export_patients(self, er: ExportRequest) -> None:
        threading.Thread(
            target=self._manage_export,
            args=(er,),
            daemon=True,
        ).start()

    # Blocking Move Study:
    def _move_study(
        self,
        scp_name: str,
        dest_scp_ae: str,
        study_uid: str,
        ux_Q: Queue,
    ) -> None:
        logger.debug(
            f"C-MOVE scp:{scp_name} move to: {dest_scp_ae} study_uid: {study_uid}"
        )

        association = None
        error_msg = ""
        try:
            association = self.connect(
                scp_name=scp_name,
                contexts=[
                    build_context(
                        self._STUDY_ROOT_QR_CLASSES[1], self.model._TRANSFER_SYNTAXES
                    )
                ],
            )

            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.StudyInstanceUID = study_uid

            # Use the C-MOVE service to request that the remote SCP move the Study to local storage scp:
            responses = association.send_c_move(
                ds,
                dest_scp_ae,
                query_model=self._STUDY_ROOT_QR_CLASSES[1],
            )

            # Process the responses received from the remote scp:
            for status, identifier in responses:
                if not status or status.Status not in (
                    C_SUCCESS,
                    C_PENDING_A,
                    C_PENDING_B,
                ):
                    if not status:
                        raise ConnectionError(
                            "Connection timed out, was aborted, or received an invalid response"
                        )
                    else:
                        raise DICOMRuntimeError(
                            f"C-MOVE Failed: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                        )

                # Add the study_uid to the status dataset:
                status.StudyInstanceUID = study_uid
                ux_Q.put(status)

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
            if association:
                association.release()

    # Manage bulk patient move using a thread pool:
    def _manage_move(self, req: MoveRequest) -> None:
        futures = []

        with ThreadPoolExecutor(
            max_workers=self._study_move_thread_pool_size
        ) as executor:
            for i in range(len(req.study_uids)):
                future = executor.submit(
                    self._move_study,
                    req.scp_name,
                    req.dest_scp_ae,
                    req.study_uids[i],
                    req.ux_Q,
                )
                futures.append(future)

            # Check for exceptions in the completed futures
            for future in futures:
                try:
                    # This will raise any exceptions that _move_study may have raised:
                    future.result()
                except Exception as e:
                    # Handle specific exceptions if needed
                    logger.error(f"An error occurred during move: {e}")
                    # Shutdown executor in case of critical error
                    executor.shutdown(wait=False)
                    break

    # Non-blocking Move Studies:
    def move_studies(self, mr: MoveRequest) -> None:
        threading.Thread(
            target=self._manage_move,
            args=(mr,),
            daemon=True,
        ).start()
