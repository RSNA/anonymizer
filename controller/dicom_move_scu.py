import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import build_context
from pynetdicom.sop_class import _QR_CLASSES as QR_CLASSES
from pynetdicom.status import QR_MOVE_SERVICE_CLASS_STATUS
from pynetdicom import debug_logger
from controller.dicom_storage_scp import (
    C_SUCCESS,
    C_STORE_OUT_OF_RESOURCES,
    C_PENDING_A,
    C_PENDING_B,
)
from utils.network import get_network_timeout

logger = logging.getLogger(__name__)

# debug_logger()


# Move list of studies from remote server to the local scp storage:
# TODO: dicom address class (ip, port, ae)
def move(
    scp_ip: str,
    scp_port: int,
    scp_ae: str,
    scu_ip: str,
    scu_ae: str,
    dest_scp_ae: str,
    study_uid: str,
) -> bool:
    logger.info(
        f"C-MOVE scu:{scu_ae}@{scu_ip} scp:{scp_ae}@{scp_ip}:{scp_port} move to: {dest_scp_ae}"
    )
    ds = Dataset()
    ds.QueryRetrieveLevel = "STUDY"
    ds.StudyInstanceUID = study_uid

    logger.info(f"Move StudyInstanceUID: {study_uid}")
    # Initialize the Application Entity
    ae = AE(scu_ae)
    # ae = get_AE()
    # if ae is None:
    #     logger.error("No Application Entity")
    #     return None
    ae.network_timeout = get_network_timeout()
    ae.connection_timeout = get_network_timeout()
    ae.acse_timeout = get_network_timeout()
    ae.dimse_timeout = get_network_timeout()
    error = False
    assoc = None
    try:
        # Connect to remote scp:
        assoc = ae.associate(
            addr=scp_ip,
            port=scp_port,
            contexts=[
                build_context(QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"])
            ],
            ae_title=scp_ae,
            bind_address=(scu_ip, 0),
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
        for status, _ in responses:
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

    except Exception as e:
        logger.error(f"Failed DICOM C-MOVE to {scu_ae}, Error: {str(e)}")
        error = True

    finally:
        # Release the association
        if assoc:
            assoc.release()
        ae.shutdown()
        return not error
