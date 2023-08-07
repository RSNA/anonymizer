import logging

from pynetdicom.events import Event, EVT_C_STORE, EVT_C_ECHO
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import (
    StoragePresentationContexts,
    VerificationPresentationContexts,
)
from pynetdicom._globals import ALL_TRANSFER_SYNTAXES

from controller.anonymize import anonymize_dataset

from utils.translate import _
from utils.storage import local_storage_path
from utils.network import get_network_timeout

from model.project import SITEID, PROJECTNAME, TRIALNAME, UIDROOT

logger = logging.getLogger(__name__)

# TODO: convert to singleton class

# Store scp instance after ae.start_server() is called:
scp = None
ae = None


# Is SCP running?
def server_running() -> bool:
    global scp
    if scp is None:
        return False
    else:
        return True


# SCP AE Title:
def get_aet() -> str:
    global scp
    if scp is None:
        return ""
    else:
        return scp.ae_title


def get_AE():
    global ae
    return ae


# C-STORE status values from DICOM Standard, Part 7:
# https://dicom.nema.org/medical/dicom/current/output/chtml/part07/chapter_9.html#sect_9.1.1
# https://pydicom.github.io/pynetdicom/stable/reference/generated/pynetdicom._handlers.doc_handle_store.html
# Non-Service Class specific statuses - PS3.7 Annex C
# TODO: trim error codes to those relevant, move to utils/errors.py
C_SUCCESS = 0x0000
C_STORE_NOT_AUTHORISED = 0x0124
C_STORE_OUT_OF_RESOURCES = 0xA700
C_MOVE_UNKNOWN_AE = 0xA801
C_STORE_DATASET_ERROR = 0xA900  # Dataset does not match SOP class
C_STORE_DUPLICATE_INVOCATION = 0x0210
C_STORE_DECODE_ERROR = 0xC210
C_STORE_UNRECOGNIZED_OPERATION = 0xC211
C_STORE_PROCESSING_FAILURE = 0x0110
C_CANCEL = 0xFE00
C_PENDING_A = 0xFF00
C_PENDING_B = 0xFF01


# DICOM C-ECHO Verification event handler (EVT_C_ECHO)
def _handle_echo(event: Event) -> int:
    logger.debug("_handle_echo")
    # TODO: Validate remote IP & AE Title
    remote = event.assoc.remote
    logger.info(f"C-ECHO from: {remote}")
    return C_SUCCESS


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


# Start SCP:
def start(address, port, aet, storage_dir) -> bool:
    global scp, ae
    logger.info(f"start {address}, {port}, {aet}, {storage_dir}...")

    if server_running():
        logger.error("DICOM C-STORE scp is already running")
        return False

    ae = AE(aet)
    # Unlimited PDU size
    ae.maximum_pdu_size = 0
    ae.network_timeout = get_network_timeout()
    storage_sop_classes = [
        cx.abstract_syntax
        for cx in StoragePresentationContexts + VerificationPresentationContexts
    ]
    for uid in storage_sop_classes:
        ae.add_supported_context(uid, ALL_TRANSFER_SYNTAXES)  # type: ignore

    handlers = [(EVT_C_ECHO, _handle_echo), (EVT_C_STORE, _handle_store, [storage_dir])]

    try:
        scp = ae.start_server(
            (address, port),
            block=False,
            evt_handlers=handlers,
        )
    except Exception as e:
        logger.error(
            f"Failed to start DICOM C-STORE scp on {address}:{port}, with AE Title = {aet}, Error: {str(e)}"
        )
        return False

    logger.info(
        f"DICOM C-STORE scp listening on {address}:{port}, with AE Title = {aet}, storing files in {storage_dir}"
    )
    return True


# Stop SCP:
def stop(final_shutdown=False) -> None:
    global scp
    if not final_shutdown:
        logger.info("User initiated: Stop DICOM C-STORE scp and close socket")
    if not scp:
        return
    scp.shutdown()
    scp = None
