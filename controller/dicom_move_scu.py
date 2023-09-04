import logging
from os import error
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import build_context
from pynetdicom.sop_class import _QR_CLASSES as QR_CLASSES
from pynetdicom.status import QR_MOVE_SERVICE_CLASS_STATUS
from controller.dicom_return_codes import C_SUCCESS, C_PENDING_A, C_PENDING_B, C_FAILURE
from controller.dicom_ae import DICOMNode, set_network_timeout, DICOMRuntimeError

logger = logging.getLogger(__name__)

# Max concurrent study moves:
# (each move is a thread which orchestrates a single study's files sequential move)
study_move_thread_pool_size = 4


@dataclass
class MoveRequest:
    scu: DICOMNode
    scp: DICOMNode
    dest_scp_ae: str
    study_uids: list[str]
    ux_Q: Queue


# Blocking: Move 1 study from remote scp server to the scp storage named dest_scp_ae:
def move(
    scu: DICOMNode,
    scp: DICOMNode,
    dest_scp_ae: str,
    study_uid: str,
) -> list[Dataset] | None:
    logger.info(
        f"C-MOVE scu:{scu} scp:{scp} move to: {dest_scp_ae} study_uid: {study_uid}"
    )

    ae = AE(scu.aet)
    set_network_timeout(ae)

    results = []
    error = False
    assoc = None
    try:
        # Connect to remote scp:
        assoc = ae.associate(
            addr=scp.ip,
            port=scp.port,
            contexts=[
                build_context(QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"])
            ],
            ae_title=scp.aet,
            bind_address=(scu.ip, 0),
        )
        if not assoc.is_established:
            raise Exception("Association rejected, aborted or never connected")

        logger.info(f"Association established with {assoc.acceptor.ae_title}")

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = study_uid

        # Use the C-MOVE service to request that the remote SCP move the Study to local storage scp:
        responses = assoc.send_c_move(
            ds,
            dest_scp_ae,
            query_model=QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"],
        )

        # Process the responses received from the remote scp:
        for status, identifier in responses:
            if not status or status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B):
                error = True
                if not status:
                    logger.error(
                        "Connection timed out, was aborted, or received an invalid response"
                    )
                else:
                    logger.error(
                        f"C-MOVE Failed: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                    )

            # The responses received from the SCP include notifications
            # on whether or not the storage sub-operations have been successful.
            # Result dataset:
            # (0000, 0900) Status                              US:
            # If no error:
            # (0000, 1020) Number of Remaining Sub-operations  US:
            # (0000, 1021) Number of Completed Sub-operations  US:
            # (0000, 1022) Number of Failed Sub-operations     US:
            # (0000, 1023) Number of Warning Sub-operations    US:

            results.append(status)

    except Exception as e:
        logger.error(f"Failed DICOM C-MOVE to {dest_scp_ae}, Error: {str(e)}")
        if error:
            return None

    finally:
        # Release the association
        if assoc:
            assoc.release()
        ae.shutdown()

    return results


# Blocking: Move 1 study from remote server to the scp storage named dest_scp_ae:
# Callef from _manage_move():
def _move_study(
    ae: AE,
    scu: DICOMNode,
    scp: DICOMNode,
    dest_scp_ae: str,
    study_uid: str,
    ux_Q: Queue,
) -> None:
    logger.info(
        f"C-MOVE scu:{scu} scp:{scp} move to: {dest_scp_ae} study_uid: {study_uid}"
    )

    assoc = None
    error_msg = ""
    try:
        # Connect to remote scp:
        assoc = ae.associate(
            addr=scp.ip,
            port=scp.port,
            contexts=[
                build_context(QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"])
            ],
            ae_title=scp.aet,
            bind_address=(scu.ip, 0),
        )
        if not assoc.is_established:
            logger.error("Association rejected, aborted or never connected")
            raise ConnectionError(
                f"Failed to establish association with {scp.aet}@{scp.ip}:{scp.port}"
            )
        logger.debug(f"Association established with {assoc.acceptor.ae_title}")

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = study_uid

        # Use the C-MOVE service to request that the remote SCP move the Study to local storage scp:
        responses = assoc.send_c_move(
            ds,
            dest_scp_ae,
            query_model=QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"],
        )

        # Process the responses received from the remote scp:
        for status, identifier in responses:
            if not status or status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B):
                if not status:
                    raise ConnectionError(
                        "Connection timed out, was aborted, or received an invalid response"
                    )
                else:
                    raise DICOMRuntimeError(
                        f"C-MOVE Failed: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                    )

            ux_Q.put(status)

    except (
        ConnectionError,
        TimeoutError,
        RuntimeError,
        ValueError,
        DICOMRuntimeError,
    ) as e:
        # Reflect status dataset back to UX client to provide find error detail
        error_msg = str(e)  # latch exception error msg
        logger.error(error_msg)
        if ux_Q:
            ds = Dataset()
            ds.Status = C_FAILURE
            ds.ErrorComment = error_msg
            ux_Q.put(ds)

    finally:
        # Release the association
        if assoc:
            assoc.release()


# Manage bulk patient export using a thread pool:
def _manage_move(req: MoveRequest) -> None:
    ae = AE(req.scu.aet)
    set_network_timeout(ae)

    futures = []

    with ThreadPoolExecutor(max_workers=study_move_thread_pool_size) as executor:
        for i in range(len(req.study_uids)):
            future = executor.submit(
                _move_study,
                ae,
                req.scu,
                req.scp,
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
                ae.shutdown()
                break


# Non-blocking Move:
def move_studies(mr: MoveRequest) -> None:
    threading.Thread(
        target=_manage_move,
        args=(mr,),
        daemon=True,
    ).start()
