import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.sop_class import _QR_CLASSES as QR_CLASSES
from pynetdicom.status import QR_FIND_SERVICE_CLASS_STATUS
from controller.dicom_ae import (
    DICOMNode,
    set_network_timeout,
    get_study_root_qr_contexts,
)
from controller.dicom_return_codes import (
    C_SUCCESS,
    C_PENDING_A,
    C_PENDING_B,
)

logger = logging.getLogger(__name__)


# Query remote server for studies matching the given query dataset:
# TODO: dicom address class (ip, port, ae)
def find(
    scu: DICOMNode,
    scp: DICOMNode,
    name: str,
    id: str,
    acc_no: str,
    study_date: str,
    modality: str,
) -> list[Dataset] | None:
    logger.info(f"C-FIND from {scu} to {scp}")

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
    ae = AE(scu.aet)
    set_network_timeout(ae)

    error = False
    results = []
    assoc = None
    try:
        assoc = ae.associate(
            scp.ip,
            scp.port,
            get_study_root_qr_contexts(),
            ae_title=scp.aet,
            bind_address=(scu.ip, 0),
        )
        if not assoc.is_established:
            logger.error("Association rejected, aborted or never connected")
            return None

        logger.info(f"Association established with {assoc.acceptor.ae_title}")

        # Use the C-FIND service to send the identifier using the StudyRootQueryRetrieveInformationModelFind
        responses = assoc.send_c_find(
            ds,
            query_model=QR_CLASSES["StudyRootQueryRetrieveInformationModelFind"],
        )

        # Process the responses received from the peer
        # TODO: reflect status dataset back to UX client to provide find error detail
        for status, identifier in responses:
            if not status or status.Status not in (C_SUCCESS, C_PENDING_A, C_PENDING_B):
                error = True
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
                    # TODO: move this code to UX client?
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
        error = True
        logger.error(f"Failed DICOM C-FIND to {scp}, Error: {str(e)}")
    finally:
        if assoc:
            assoc.release()
        ae.shutdown()
        if error:
            return None

    if len(results) == 0:
        logger.info("No query results found")
    else:
        logger.info(f"{len(results)} Query results found")
        for result in results:
            logger.info(
                f"{getattr(result, 'PatientName', 'N/A')}, "
                f"{getattr(result, 'PatientID', 'N/A')}, "
                f"{getattr(result, 'StudyDate', 'N/A')}, "
                f"{getattr(result, 'StudyDescription', 'N/A')}, "
                f"{getattr(result, 'AccessionNumber', 'N/A')}, "
                f"{getattr(result, 'ModalitiesInStudy', 'N/A')}, "
                f"{getattr(result, 'NumberOfStudyRelatedSeries', 'N/A')}, "
                f"{getattr(result, 'NumberOfStudyRelatedInstances', 'N/A')}, "
                f"{getattr(result, 'StudyInstanceUID', 'N/A')} "
            )

    return results
