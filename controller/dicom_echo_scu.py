import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import VerificationPresentationContexts
from utils.network import get_network_timeout

logger = logging.getLogger(__name__)


def echo(scp_ip: str, scp_port: int, scp_ae: str, scu_ip: str, scu_ae: str) -> bool:
    logger.info(f"C-ECHO from {scu_ae}@{scu_ip} to {scp_ae}@{scp_ip}:{scp_port}")
    # Initialize the Application Entity
    ae = AE(scu_ae)
    ae.network_timeout = get_network_timeout()

    # ae.requested_contexts = VerificationPresentationContexts
    try:
        assoc = ae.associate(
            scp_ip,
            scp_port,
            VerificationPresentationContexts,
            ae_title=scp_ae,
            bind_address=(scu_ip, 0),
        )
        if not assoc.is_established:
            logger.error("Association rejected, aborted or never connected")
            return False

        logger.info(f"Association established with {assoc.acceptor.ae_title}")

        status = assoc.send_c_echo()

    except Exception as e:
        logger.error(
            f"Failed DICOM C-ECHO from {scu_ae} to {scp_ip}:{scp_port}, with AE Title = {scp_ae}, Error: {str(e)}"
        )
        return False

    assoc.release()
    # Check the status of the returned pydicom Dataset:
    if status:
        logger.debug("C-ECHO request status: 0x{0:04x}".format(status.Status))
        if status.Status == 0x0000:
            logger.info("C-ECHO Success")
            return True
        else:
            logger.error("C-ECHO Failed status: 0x{0:04x}".format(status.Status))
    else:
        logger.error("C-ECHO Failed, no status returned")

    return False
