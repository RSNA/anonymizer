import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import (
    VerificationPresentationContexts,
)
from pynetdicom.presentation import build_context

from utils.network import get_network_timeout

logger = logging.getLogger(__name__)

_RADIOLOGY_CLASSES = {
    "Computed Radiography Image Storage": "1.2.840.10008.5.1.4.1.1.1",
    "Computed Tomography Image Storage": "1.2.840.10008.5.1.4.1.1.2",
    "Enhanced CT Image Storage": "1.2.840.10008.5.1.4.1.1.2.1",
    "Digital X-Ray Image Storage - For Presentation": "1.2.840.10008.5.1.4.1.1.1.1",
    "Digital X-Ray Image Storage - For Processing": "1.2.840.10008.5.1.4.1.1.1.1.1",
    "Digital Mammography X-Ray Image Storage For Presentation": "1.2.840.10008.5.1.4.1.1.1.2",
    "Digital Mammography X-Ray Image Storage For Processing": "1.2.840.10008.5.1.4.1.1.1.2.1",
    "Digital Intra Oral X-Ray Image Storage For Presentation": "1.2.840.10008.5.1.4.1.1.1.3",
    "Digital Intra Oral X-Ray Image Storage For Processing": "1.2.840.10008.5.1.4.1.1.1.3.1",
    "Magnetic Resonance Image Storage": "1.2.840.10008.5.1.4.1.1.4",
    "Enhanced MR Image Storage": "1.2.840.10008.5.1.4.1.1.4.1",
    "Positron Emission Tomography Image Storage": "1.2.840.10008.5.1.4.1.1.128",
    "Enhanced PET Image Storage": "1.2.840.10008.5.1.4.1.1.130",
    "Ultrasound Image Storage": "1.2.840.10008.5.1.4.1.1.6.1",
    "Mammography CAD SR Storage": "1.2.840.10008.5.1.4.1.1.88.50",
    "BreastTomosynthesisImageStorage": "1.2.840.10008.5.1.4.1.1.13.1.3",
}


RadiologyPresentationContexts = [
    build_context(uid) for uid in sorted(_RADIOLOGY_CLASSES.values())
]


def echo(scp_ip: str, scp_port: int, scp_ae: str, scu_ip: str, scu_ae: str) -> bool:
    logger.info(f"C-ECHO from {scu_ae}@{scu_ip} to {scp_ae}@{scp_ip}:{scp_port}")
    # Initialize the Application Entity
    ae = AE(scu_ae)
    # TODO: implement ae timeout setting in util.network
    ae.network_timeout = get_network_timeout()
    ae.connection_timeout = get_network_timeout()
    ae.acse_timeout = get_network_timeout()
    ae.dimse_timeout = get_network_timeout()
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

        status = (Dataset)(assoc.send_c_echo())

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
    ae.network_timeout = get_network_timeout()
    ae.connection_timeout = get_network_timeout()
    ae.acse_timeout = get_network_timeout()
    ae.dimse_timeout = get_network_timeout()
    try:
        # Establish association with SCP:
        assoc = ae.associate(
            scp_ip,
            scp_port,
            RadiologyPresentationContexts,  # Radiology SOP Classes
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
                return False

        logging.info(f"C-STORE Success files sent = {len(dicom_files)}")

    except Exception as e:
        logger.error(f"Failed DICOM C-STORE, Error: {str(e)}")
        return False

    assoc.release()

    return True
