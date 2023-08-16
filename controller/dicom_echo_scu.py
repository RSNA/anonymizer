import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.status import VERIFICATION_SERVICE_CLASS_STATUS
from controller.dicom_ae import (
    set_network_timeout,
    set_verification_context,
    get_verification_context,
)

logger = logging.getLogger(__name__)


def echo(scp_ip: str, scp_port: int, scp_ae: str, scu_ip: str, scu_ae: str) -> bool:
    logger.info(f"C-ECHO from {scu_ae}@{scu_ip} to {scp_ae}@{scp_ip}:{scp_port}")
    # Initialize the Application Entity
    ae = AE(scu_ae)
    set_network_timeout(ae)
    set_verification_context(ae)

    try:
        assoc = ae.associate(
            scp_ip,
            scp_port,
            contexts=[get_verification_context()],
            ae_title=scp_ae,
            bind_address=(scu_ip, 0),
        )
        if not assoc.is_established:
            logger.error("Association rejected, aborted or never connected")
            return False

        logger.info(f"Association established with {assoc.acceptor.ae_title}")
        status = (Dataset)(assoc.send_c_echo())

    except Exception as e:
        logger.error(
            f"Failed DICOM C-ECHO from {scu_ae} to {scp_ip}:{scp_port}, with AE Title = {scp_ae}, Error: {str(e)}"
        )
        return False

    assoc.release()
    ae.shutdown()  # TODO: check if this is necessary for echo scu

    # Check the status of the returned pydicom Dataset:
    if status:
        if status.Status == 0x0000:
            logger.info(f"C-ECHO Success")
            return True
        else:
            logger.error(status)
            logger.error(
                f"C-ECHO Failed status: {VERIFICATION_SERVICE_CLASS_STATUS[status.Status][1]}"
            )
    else:
        logger.error("C-ECHO Failed, no status returned")

    return False
