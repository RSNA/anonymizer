import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import build_context
from pynetdicom.sop_class import _QR_CLASSES as QR_CLASSES
from pynetdicom.status import QR_MOVE_SERVICE_CLASS_STATUS
from pynetdicom import debug_logger
from controller.dicom_storage_scp import get_aet, get_AE
from utils.network import get_network_timeout

logger = logging.getLogger(__name__)

debug_logger()


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
) -> list[Dataset] | None:
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
    ae.acse_timeout = get_network_timeout()
    ae.dimse_timeout = get_network_timeout()
    try:
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
            logger.error("Association rejected, aborted or never connected")
            return None

        logger.info(f"Association established with {assoc.acceptor.ae_title}")

        # Use the C-MOVE service to send the identifier
        responses = assoc.send_c_move(
            ds,
            dest_scp_ae,
            query_model=QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"],
        )

        # Process the responses received from the peer
        results = []
        for status, identifier in responses:
            if not status or status.Status not in (0xFF00, 0xFF01, 0x0000):
                if not status:
                    logger.error(
                        "Connection timed out, was aborted, or received an invalid response"
                    )
                else:
                    logger.error(
                        f"C-MOVE Failed: {QR_MOVE_SERVICE_CLASS_STATUS[status.Status][1]}"
                    )
            else:
                if identifier:
                    results.append(identifier)

        # Release the association
        assoc.release()

    except Exception as e:
        logger.error(f"Failed DICOM C-MOVE to {dest_scp_ae}, Error: {str(e)}")
        return None

    if len(results) == 0:
        logger.info("No move results returned")
        return None
    else:
        logger.info(f"{len(results)} Move results")
        for result in results:
            logger.info(result)

    return results
