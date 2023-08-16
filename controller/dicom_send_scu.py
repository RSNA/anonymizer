import logging
import threading
import queue
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.status import STORAGE_SERVICE_CLASS_STATUS
from controller.dicom_ae import (
    set_network_timeout,
    set_radiology_storage_contexts,
    get_radiology_storage_contexts,
)
from dataclasses import dataclass


@dataclass
class SendRequest:
    scp_ip: str
    scp_port: int
    scp_ae: str
    scu_ip: str
    scu_ae: str
    dicom_files: list[Dataset | str]  # list of datasets or paths to dicom files
    ux_Q: queue.Queue  # queue for UX updates


@dataclass
class SendResponse:
    dicom_file: Dataset | str  # dataset or path to dicom file
    status: int  # as per dicom standard


logger = logging.getLogger(__name__)


def _send(sc: SendRequest):
    logger.info(
        f"C-STORE from {sc.scu_ae}@{sc.scu_ip} to {sc.scp_ae}@{sc.scp_ip}:{sc.scp_port}"
    )
    # Initialize the Application Entity
    ae = AE(sc.scu_ae)
    set_network_timeout(ae)
    set_radiology_storage_contexts(ae)
    try:
        # Establish association with SCP:
        assoc = ae.associate(
            sc.scp_ip,
            sc.scp_port,
            contexts=get_radiology_storage_contexts(),
            ae_title=sc.scp_ae,
            bind_address=(sc.scu_ip, 0),
        )
        if not assoc.is_established:
            logger.error("Association rejected, aborted or never connected")
            return

        logger.info(f"Association established with {assoc.acceptor.ae_title}")

        # Send DICOM Files:
        for dicom_file in sc.dicom_files:
            dcm_response = (Dataset)(assoc.send_c_store(dicom_file))
            resp = SendResponse(dicom_file, dcm_response.Status)
            if dcm_response.Status != 0:
                logger.error(
                    f"Error sending DICOM file {dicom_file}: {STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}"
                )
            sc.ux_Q.put(resp)  # TODO: handle queue full

        logging.info(f"C-STORE Success files sent = {len(sc.dicom_files)}")

    except Exception as e:
        logger.error(f"Failed DICOM C-STORE, Error: {str(e)}")
        return

    assoc.release()
    ae.shutdown()
    return


def send(sc: SendRequest) -> None:
    threading.Thread(
        target=_send,
        args=(sc,),
        daemon=True,
    ).start()
