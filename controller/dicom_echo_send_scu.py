import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE

from controller.dicom_ae import (
    set_network_timeout,
    set_verification_context,
    set_radiology_storage_contexts,
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
        logger.debug("C-ECHO request status: 0x{0:04x}".format(status.Status))
        if status.Status == 0x0000:
            logger.info(f"C-ECHO Success")
            return True
        else:
            logger.error(status)
            logger.error("C-ECHO Failed status: 0x{0:04x}".format(status.Status))
    else:
        logger.error("C-ECHO Failed, no status returned")

    return False


# Send DICOM file(s) to SCP, return False if any error
def send(
    scp_ip: str,
    scp_port: int,
    scp_ae: str,
    scu_ip: str,
    scu_ae: str,
    dicom_files: list[str],
) -> bool:
    logger.info(f"C-STORE from {scu_ae}@{scu_ip} to {scp_ae}@{scp_ip}:{scp_port}")
    # Initialize the Application Entity
    ae = AE(scu_ae)
    set_network_timeout(ae)
    set_radiology_storage_contexts(ae)
    try:
        # Establish association with SCP:
        assoc = ae.associate(
            scp_ip,
            scp_port,
            ae_title=scp_ae,
            bind_address=(scu_ip, 0),
        )
        if not assoc.is_established:
            logger.error("Association rejected, aborted or never connected")
            return False

        logger.info(f"Association established with {assoc.acceptor.ae_title}")

        # Send DICOM Files:
        # TODO: yield mechanism, progress bar for dashboard/status bar
        for dicom_file in dicom_files:
            response = (Dataset)(assoc.send_c_store(dicom_file))
            if response.Status != 0:
                logger.error(
                    f"Error sending DICOM file {dicom_file}: {response.Status}"
                )
                return False  # TODO: remove when yield mechanism is implemented

        logging.info(f"C-STORE Success files sent = {len(dicom_files)}")

    except Exception as e:
        logger.error(f"Failed DICOM C-STORE, Error: {str(e)}")
        return False

    assoc.release()
    ae.shutdown()

    return True