import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import build_context
from pynetdicom.sop_class import _QR_CLASSES as QR_CLASSES
from pynetdicom.status import QR_MOVE_SERVICE_CLASS_STATUS
from pynetdicom import debug_logger
from controller.dicom_return_codes import (
    C_SUCCESS,
    C_PENDING_A,
    C_PENDING_B,
)
from controller.dicom_ae import set_network_timeout

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
    set_network_timeout(ae)

    results = []
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
        logger.error(f"Failed DICOM C-MOVE to {scu_ae}, Error: {str(e)}")
        if error:
            return None

    finally:
        # Release the association
        if assoc:
            assoc.release()
        ae.shutdown()

    return results
