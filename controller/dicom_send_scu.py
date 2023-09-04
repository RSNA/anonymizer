import os
import logging
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import time
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.status import STORAGE_SERVICE_CLASS_STATUS
from utils.translate import _
from controller.dicom_storage_scp import get_active_storage_dir
from controller.dicom_ae import (
    DICOMNode,
    DICOMRuntimeError,
    set_network_timeout,
    set_radiology_storage_contexts,
    get_radiology_storage_contexts,
)


# Max concurrent patient exports:
# (each export is a thread which sends a single patient's files sequentially)
# TODO: make this user settable & add to config.son?
patient_export_thread_pool_size = 4
MAX_RETRIES = 2


@dataclass
class ExportRequest:
    scu: DICOMNode
    scp: DICOMNode
    patient_ids: list[str]  # list of patient IDs to export
    ux_Q: Queue  # queue for UX updates for the full export


@dataclass
class ExportResponse:
    patient_id: str
    files_to_send: int  # total number of files to send for this patient, remains constant
    files_sent: int  # incremented for each file sent successfully
    errors: int
    # TODO: add error message to reflect specific error to UX
    # TODO: simplify: stop export on ANY error

    # Class attribute for single patient termination
    @classmethod
    def patient_critical_error(cls, patient_id):
        return cls(
            patient_id=patient_id,
            files_to_send=0,
            files_sent=0,
            errors=1,
        )

    # Class attribute for ALL patients export termination
    @classmethod
    def full_export_critical_error(cls):
        return cls(
            patient_id="",  # empty string for ALL patients
            files_to_send=0,
            files_sent=0,
            errors=1,
        )

    # Class attribute to check if patient export is complete
    @classmethod
    def patient_export_complete(cls, response):
        return response.files_to_send <= (response.files_sent + response.errors)


logger = logging.getLogger(__name__)


# Blocking send, raises exception on error:
def send(
    file_paths: list[str],
    scu: DICOMNode,
    scp: DICOMNode,
    contexts=get_radiology_storage_contexts(),
) -> bool:
    # Initialize the Application Entity
    ae = AE(scu.aet)
    set_network_timeout(ae)
    set_radiology_storage_contexts(ae)

    # Establish an association (thread) with SCP for this patient's sequential file transfer
    assoc = None
    try:
        assoc = ae.associate(
            scp.ip,
            scp.port,
            contexts=contexts,
            ae_title=scp.aet,
            bind_address=(scu.ip, 0),
        )

        if not assoc.is_established:
            raise ConnectionError(
                f"Failed to establish association with {scp.aet}@{scp.ip}:{scp.port}"
            )

    except (ConnectionError, TimeoutError, RuntimeError) as e:
        logger.error(f"Error establishing association: {e}")
        raise

    for dicom_file_path in file_paths:
        try:
            dcm_response: Dataset = assoc.send_c_store(dataset=dicom_file_path)

            if dcm_response.Status != 0:
                raise DICOMRuntimeError(
                    f"DICOM Response: {STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}"
                )

        except (RuntimeError, AttributeError, ValueError, InvalidDicomError) as e:
            logger.error(f"Error sending DICOM file {dicom_file_path}: {e}")
            assoc.release()
            raise

    assoc.release()
    return True


# Background export worker thread:
def _export_patient(
    ae: AE, scu: DICOMNode, scp: DICOMNode, patient_id: str, ux_Q: Queue
) -> bool:
    logger.info(f"_export_patient {patient_id} start")

    local_storage_dir = get_active_storage_dir()
    if local_storage_dir is None:
        logger.error(f"Active storage directory not set")
        ux_Q.put(ExportResponse.full_export_critical_error())
        return False

    # Load DICOM files to send from active local storage directory for this patient:
    path = os.path.join(local_storage_dir, patient_id)

    if not os.path.isdir(path):
        logger.error(f"Selected directory {path} is not a directory")
        ux_Q.put(ExportResponse.patient_critical_error(patient_id))
        return False

    file_paths = []
    for root, _, files in os.walk(path):
        file_paths.extend(
            os.path.join(root, file) for file in files if file.endswith(".dcm")
        )

    if not file_paths:
        logger.error(f"No DICOM files found in {path}")
        ux_Q.put(ExportResponse.patient_critical_error(patient_id))
        return False

    # Establish an association (thread) with SCP for this patient's sequential file transfer
    # TODO: Optimization, use one association for all patients?
    assoc = None
    try:
        assoc = ae.associate(
            scp.ip,
            scp.port,
            contexts=get_radiology_storage_contexts(),
            ae_title=scp.aet,
            bind_address=(scu.ip, 0),
        )

        if not assoc.is_established:
            raise ConnectionError(
                f"Failed to establish association with {scp.aet}@{scp.ip}:{scp.port}"
            )

    except (ConnectionError, TimeoutError, RuntimeError) as e:
        logger.error(f"Error establishing association: {e}")
        # If association can't be established with this SCP terminate full export:
        ux_Q.put(ExportResponse.full_export_critical_error())
        return False

    files_to_send = len(file_paths)
    files_sent = 0
    errors = 0
    for dicom_file_path in file_paths:
        # TODO: send in batches?
        # time.sleep(0.1)  # throttle for UX responsiveness
        retries = 0
        # TODO: simplify, remote retries?
        while retries < MAX_RETRIES:
            try:
                dcm_response: Dataset = assoc.send_c_store(dataset=dicom_file_path)

                if dcm_response.Status != 0:
                    errors += 1
                    logger.error(
                        f"Error sending DICOM file {dicom_file_path}: {STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}"
                    )
                else:
                    files_sent += 1

                break

            except TimeoutError:
                retries += 1
                logger.warning(
                    f"Timeout error sending DICOM file {dicom_file_path}. Retry {retries}/{MAX_RETRIES}."
                )
                # Raise exception to terminate this patient's export and to signal to the thread pool to terminate all other exports:
                if retries == MAX_RETRIES:
                    ux_Q.put(ExportResponse.full_export_critical_error())
                    assoc.release()
                    raise DICOMRuntimeError(
                        f"Timeout error sending DICOM file {dicom_file_path}."
                    )

            except Exception as e:
                logger.error(f"Error sending DICOM file {dicom_file_path}: {e}")
                errors += 1
                break

        # Notify in batches, not every file:
        ux_Q.put(
            ExportResponse(
                patient_id=patient_id,
                files_to_send=files_to_send,
                files_sent=files_sent,
                errors=errors,
            )
        )

    logging.info(
        f"_export_patient {patient_id} complete, files sent = {files_sent} / {files_to_send}"
    )

    assoc.release()
    return True


# Manage bulk patient export using a thread pool:
def _manage_export(req: ExportRequest) -> None:
    ae = AE(req.scu.aet)
    set_network_timeout(ae)
    set_radiology_storage_contexts(ae)

    futures = []

    with ThreadPoolExecutor(max_workers=patient_export_thread_pool_size) as executor:
        for i in range(len(req.patient_ids)):
            future = executor.submit(
                _export_patient, ae, req.scu, req.scp, req.patient_ids[i], req.ux_Q
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
                executor.shutdown(
                    wait=False
                )  # Shutdown executor in case of critical error
                break


# Non-blocking send:
def export_patients(er: ExportRequest) -> None:
    threading.Thread(
        target=_manage_export,
        args=(er,),
        daemon=True,
    ).start()
