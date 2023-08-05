import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import build_context
from utils.network import get_network_timeout

logger = logging.getLogger(__name__)

# StudyRootQueryRetrieveInformationModelFind
StudyQueryModel = "1.2.840.10008.5.1.4.1.2.2.1"


# Query remote server for studies matching the given query dataset:
# TODO: dicom address class (ip, port, ae)
def find(
    scp_ip: str,
    scp_port: int,
    scp_ae: str,
    scu_ip: str,
    scu_ae: str,
    name: str,
    id: str,
    acc_no: str,
    study_date: str,
    modality: str,
) -> bool:
    logger.info(f"C-FIND from {scu_ae}@{scu_ip} to {scp_ae}@{scp_ip}:{scp_port}")
    ds = Dataset()
    ds.QueryRetrieveLevel = "STUDY"
    ds.PatientName = name
    ds.PatientID = id
    ds.AccessionNumber = acc_no
    ds.StudyDate = study_date
    ds.Modality = modality
    # Initialize the Application Entity
    ae = AE(scu_ae)
    ae.network_timeout = get_network_timeout()
    try:
        assoc = ae.associate(
            scp_ip,
            scp_port,
            [build_context(StudyQueryModel)],
            ae_title=scp_ae,
            bind_address=(scu_ip, 0),
        )
        if not assoc.is_established:
            logger.error("Association rejected, aborted or never connected")
            return False

        logger.info(f"Association established with {assoc.acceptor.ae_title}")

        # Use the C-FIND service to send the identifier
        responses = assoc.send_c_find(
            ds,
            query_model=StudyQueryModel,
        )

        for status, identifier in responses:
            if status:
                logger.debug("C-FIND query status: 0x{0:04x}".format(status.Status))
                if status.Status in (0xFF00, 0xFF01):
                    logger.info(f"C-FIND Pending: {identifier}")
                elif status.Status == 0x0000:
                    logger.info("C-FIND Success")
                else:
                    logger.error(status)
                    logger.error(
                        "C-FIND Failed status: 0x{0:04x}".format(status.Status)
                    )
            else:
                logger.error(
                    "Connection timed out, was aborted or received invalid response"
                )

            # If the status is 'Pending' then identifier is the C-FIND response
            if status.Status in (0xFF00, 0xFF01):
                logger.info("C-FIND Pending")
            elif status.Status == 0x0000:
                logger.info("C-FIND Success")
            else:
                logger.error(status)
                logger.error("C-FIND Failed status: 0x{0:04x}".format(status.Status))

        # Release the association
        assoc.release()

    except Exception as e:
        logger.error(
            f"Failed DICOM C-FIND to {scp_ae}@{scp_ip}:{scp_port}, Error: {str(e)}"
        )
        return False

    return True
