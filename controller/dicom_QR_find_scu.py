import logging
from typing import final
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import build_context
from pynetdicom.sop_class import _QR_CLASSES as QR_CLASSES
from pynetdicom.status import QR_FIND_SERVICE_CLASS_STATUS
from controller.dicom_ae import set_network_timeout

logger = logging.getLogger(__name__)


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
) -> list[Dataset] | None:
    logger.info(f"C-FIND from {scu_ae}@{scu_ip} to {scp_ae}@{scp_ip}:{scp_port}")

    ds = Dataset()
    ds.QueryRetrieveLevel = "STUDY"
    ds.PatientName = name
    ds.PatientID = id
    ds.AccessionNumber = acc_no
    ds.StudyDate = study_date
    ds.ModalitiesInStudy = modality
    ds.NumberOfStudyRelatedSeries = 0
    ds.NumberOfStudyRelatedInstances = 0
    ds.StudyDescription = ""
    ds.StudyInstanceUID = ""

    logger.info(f"Query: {name}, {id}, {acc_no}, {study_date}, {modality}")
    # Initialize the Application Entity
    ae = AE(scu_ae)
    set_network_timeout(ae)

    results = []
    assoc = None
    try:
        assoc = ae.associate(
            scp_ip,
            scp_port,
            [build_context(QR_CLASSES["StudyRootQueryRetrieveInformationModelFind"])],
            ae_title=scp_ae,
            bind_address=(scu_ip, 0),
        )
        if not assoc.is_established:
            logger.error("Association rejected, aborted or never connected")
            return None

        logger.info(f"Association established with {assoc.acceptor.ae_title}")

        # Use the C-FIND service to send the identifier
        responses = assoc.send_c_find(
            ds,
            query_model=QR_CLASSES["StudyRootQueryRetrieveInformationModelFind"],
        )

        # Process the responses received from the peer
        for status, identifier in responses:
            if not status or status.Status not in (0xFF00, 0xFF01, 0x0000):
                if not status:
                    logger.error(
                        "Connection timed out, was aborted, or received an invalid response"
                    )
                else:
                    logger.error(
                        f"C-FIND Failed: {QR_FIND_SERVICE_CLASS_STATUS[status.Status][1]}"
                    )
            else:
                if identifier:
                    fields_to_remove = [
                        "QueryRetrieveLevel",
                        "RetrieveAETitle",
                        "SpecificCharacterSet",
                    ]
                    for field in fields_to_remove:
                        if field in identifier:
                            delattr(identifier, field)
                    results.append(identifier)

    except Exception as e:
        logger.error(
            f"Failed DICOM C-FIND to {scp_ae}@{scp_ip}:{scp_port}, Error: {str(e)}"
        )
    finally:
        if assoc:
            assoc.release()
        ae.shutdown()

    if len(results) == 0:
        logger.info("No query results found")
        return None
    else:
        logger.info(f"{len(results)} Query results found")
        for result in results:
            logger.info(
                f"{result.PatientName}, {result.PatientID}, {result.StudyDate}, {result.StudyDescription}, {result.AccessionNumber}, {result.ModalitiesInStudy}, {result.NumberOfStudyRelatedSeries}, {result.NumberOfStudyRelatedInstances}, {result.StudyInstanceUID} "
            )

    return results
