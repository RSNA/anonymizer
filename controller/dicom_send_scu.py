import logging
import os
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.status import STORAGE_SERVICE_CLASS_STATUS
from utils.translate import _
from view.storage_dir import get_storage_directory
from controller.dicom_ae import (
    DICOMNode,
    DICOMRuntimeError,
    set_network_timeout,
    set_radiology_storage_contexts,
    get_radiology_storage_contexts,
)
from dataclasses import dataclass

# Max concurrent patient exports:
# (each export is a thread which sends a single patient's files sequentially)
# TODO: make this user settable & add to config.son?
patient_export_thread_pool_size = 2
MAX_RETRIES = 3


@dataclass
class ExportRequest:
    scu: DICOMNode
    scp: DICOMNode
    patient_ids: list[str]  # list of patient IDs to export
    ux_Q: queue.Queue  # queue for UX updates


@dataclass
class ExportResponse:
    patient_id: str
    files_to_send: int
    files_sent: int
    errors: int


logger = logging.getLogger(__name__)


# Blocking send (for testing), return False immediately on error:
def send(file_paths: list[str], scu: DICOMNode, scp: DICOMNode) -> bool:
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
        return False

    for dicom_file_path in file_paths:
        try:
            dcm_response: Dataset = assoc.send_c_store(dataset=dicom_file_path)

            if dcm_response.Status != 0:
                raise DICOMRuntimeError(
                    f"DICOM Response: {STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}"
                )

        except Exception as e:
            logger.error(f"Error sending DICOM file {dicom_file_path}: {e}")
            assoc.release()
            return False

    assoc.release()
    return True


# Background export worker thread:
def _export_patient(
    ae: AE, scu: DICOMNode, scp: DICOMNode, patient_id: str, ux_Q: queue.Queue
) -> bool:
    logger.info("_export_patient {patient_id} start")

    # Indicates patient termination
    patient_critical_error_resp = ExportResponse(
        patient_id=patient_id,
        files_to_send=0,
        files_sent=0,
        errors=1,
    )

    # indicates full export termination
    full_export_critical_error_resp = ExportResponse(
        patient_id=patient_id,
        files_to_send=0,
        files_sent=0,
        errors=-1,
    )

    # Load DICOM files to send from local storage for this patient:
    path = os.path.join(get_storage_directory(), patient_id)

    if not os.path.isdir(path):
        logger.error(f"Selected directory {path} is not a directory")
        ux_Q.put(patient_critical_error_resp)
        return False

    file_paths = []
    for root, _, files in os.walk(path):
        file_paths.extend(
            os.path.join(root, file) for file in files if file.endswith(".dcm")
        )

    if not file_paths:
        logger.error(f"No DICOM files found in {path}")
        ux_Q.put(patient_critical_error_resp)
        return False

    # Establish an association (thread) with SCP for this patient's sequential file transfer
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
        ux_Q.put(full_export_critical_error_resp)
        return False

    files_to_send = len(file_paths)
    files_sent = 0
    errors = 0
    for dicom_file_path in file_paths:
        retries = 0
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

            except TimeoutError:
                retries += 1
                logger.warning(
                    f"Timeout error sending DICOM file {dicom_file_path}. Retry {retries}/{MAX_RETRIES}."
                )
                # Raise exception to terminate this patient's export and to signal to the thread pool to terminate all other exports:
                if retries == MAX_RETRIES:
                    ux_Q.put(full_export_critical_error_resp)
                    assoc.release()
                    raise DICOMRuntimeError(
                        f"Timeout error sending DICOM file {dicom_file_path}."
                    )

            except Exception as e:
                logger.error(f"Error sending DICOM file {dicom_file_path}: {e}")
                errors += 1
                break

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
def manage_export(er: ExportRequest) -> None:
    # Initialize the Application Entity
    ae = AE(er.scu.aet)
    set_network_timeout(ae)
    set_radiology_storage_contexts(ae)

    futures = []

    with ThreadPoolExecutor(max_workers=patient_export_thread_pool_size) as executor:
        for i in range(len(er.patient_ids)):
            future = executor.submit(
                _export_patient, ae, er.scu, er.scp, er.patient_ids[i], er.ux_Q
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
        target=manage_export,
        args=(er,),
        daemon=True,
    ).start()
