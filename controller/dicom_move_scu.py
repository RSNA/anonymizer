import logging
from pydicom.dataset import Dataset
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import build_context
from pynetdicom.sop_class import _QR_CLASSES as QR_CLASSES
from pynetdicom.status import QR_MOVE_SERVICE_CLASS_STATUS
from pynetdicom.events import Event, EVT_C_STORE
from pynetdicom.presentation import StoragePresentationContexts
from pynetdicom._globals import ALL_TRANSFER_SYNTAXES

from controller.dicom_storage_scp import (
    C_SUCCESS,
    C_STORE_OUT_OF_RESOURCES,
    C_PENDING_A,
    C_PENDING_B,
)
from controller.anonymize import anonymize_dataset

from utils.translate import _
from utils.storage import local_storage_path
from utils.network import get_network_timeout

from model.project import SITEID, PROJECTNAME, TRIALNAME, UIDROOT

logger = logging.getLogger(__name__)


# DICOM C-STORE scp event handler (EVT_C_STORE)):
def _handle_store(event: Event, storage_dir: str) -> int:
    logger.info("_handle_store")
    # TODO: Validate remote IP & AE Title
    remote = event.assoc.remote
    ds = event.dataset
    ds.file_meta = event.file_meta
    logger.debug(remote)
    logger.debug(ds)
    # TODO: ensure ds has values for PatientName, Modality, StudyDate, SeriesNumber, InstanceNumber
    filename = local_storage_path(storage_dir, SITEID, ds)
    logger.info(
        f"C-STORE [{ds.file_meta.TransferSyntaxUID}]: {remote['ae_title']} => {filename}"
    )
    ds = anonymize_dataset(ds)
    try:
        ds.save_as(filename, write_like_original=False)
    except Exception as exception:
        logger.error("Failed writing instance to storage directory")
        logger.exception(exception)
        return C_STORE_OUT_OF_RESOURCES

    return C_SUCCESS


# Move list of studies from remote server to the local scp storage:
# TODO: dicom address class (ip, port, ae)
def move(
    scp_ip: str,
    scp_port: int,
    scp_ae: str,
    scu_ip: str,
    scu_ae: str,
    study_uid: str,
    storage_dir: str,
) -> bool:
    logger.info(
        f"C-MOVE scu:{scu_ae}@{scu_ip} requesting scp:{scp_ae}@{scp_ip}:{scp_port} to move study {study_uid}"
    )

    # Initialize the Application Entity for handling storage contexts and
    # requesting the move study to this AE
    ae = AE(scu_ae)
    ae.maximum_pdu_size = 0  # Unlimited PDU size

    storage_sop_classes = [cx.abstract_syntax for cx in StoragePresentationContexts]
    for uid in storage_sop_classes:
        ae.add_supported_context(uid, ALL_TRANSFER_SYNTAXES)  # type: ignore

    handlers = [(EVT_C_STORE, _handle_store, [storage_dir])]
    ae.network_timeout = get_network_timeout()
    ae.acse_timeout = get_network_timeout()
    ae.dimse_timeout = get_network_timeout()

    # Start our Storage SCP in non-blocking mode, listening on port 1045
    scu_port = 1045
    try:
        ae.start_server(
            (scu_ip, 1045),
            block=False,
            evt_handlers=handlers,  # type: ignore
        )
    except Exception as e:
        logger.error(
            f"Failed to start DICOM C-STORE scp on {scp_ip}:{scu_port}, with AE Title = {scu_ae}, Error: {str(e)}"
        )
        return False

    error = False
    assoc = None
    try:
        assoc = ae.associate(
            addr=scp_ip,
            port=scp_port,
            contexts=[
                build_context(QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"])
            ],
            ae_title=scp_ae,
            # bind_address=(scu_ip, 0),
        )
        if not assoc.is_established:
            raise Exception("Association rejected, aborted or never connected")

        logger.info(f"Association established with {assoc.acceptor.ae_title}")

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = study_uid

        # Use the C-MOVE service
        responses = assoc.send_c_move(
            ds,
            scu_ae,
            query_model=QR_CLASSES["StudyRootQueryRetrieveInformationModelMove"],
        )

        # Process the responses received from the remote scp:
        for status, _ in responses:
            # TODO:
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
