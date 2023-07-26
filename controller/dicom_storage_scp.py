import logging
from pathlib import Path
import customtkinter as ctk

from pydicom._version import __version__ as pydicom_version
from pydicom.uid import UID
from pydicom.filewriter import write_file_meta_info

from pynetdicom._version import __version__ as pynetdicom_version

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

from model.project import SITEID, PROJECTNAME, TRIALNAME, UIDROOT

logger = logging.getLogger(__name__)

# Store scp instance after ae.start_server() is called:
scp = None


def server_running():
    global scp
    return scp is not None


# C-STORE status values from DICOM Standard, Part 7:
# https://dicom.nema.org/medical/dicom/current/output/chtml/part07/chapter_9.html#sect_9.1.1
# https://pydicom.github.io/pynetdicom/stable/reference/generated/pynetdicom._handlers.doc_handle_store.html
# Non-Service Class specific statuses - PS3.7 Annex C
C_ECHO_SUCCESS = 0x0000
C_STORE_SUCCESS = 0x0000
C_STORE_NOT_AUTHORISED = 0x0124
C_STORE_OUT_OF_RESOURCES = 0xA700
C_MOVE_UNKNOWN_AE = 0xA801
C_STORE_DATASET_ERROR = 0xA900  # Dataset does not match SOP class
C_STORE_DUPLICATE_INVOCATION = 0x0210
C_STORE_DECODE_ERROR = 0xC210
C_STORE_UNRECOGNIZED_OPERATION = 0xC211
C_STORE_PROCESSING_FAILURE = 0x0110


# TODO: move this to utils.py, investigate global, detachable log window with level and module filter
class TextBoxHandler(logging.Handler):
    def __init__(self, text):
        logging.Handler.__init__(self)
        self.text = text

    def emit(self, record):
        msg = self.format(record)
        self.text.configure(state="normal")
        self.text.insert(ctk.END, msg + "\n")
        self.text.configure(state="disabled")
        self.text.see(ctk.END)


# Install log handler for SCP Textbox:
def loghandler(textbox: ctk.CTkTextbox):
    logger.info(
        f"loghandler pydicom version: {pydicom_version}, pynetdicom version: {pynetdicom_version}   "
    )
    ch = TextBoxHandler(textbox)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)


# DICOM C-ECHO Verification event handler (EVT_C_ECHO)
def _handle_echo(event):
    logger.debug("_handle_echo")
    # TODO: Validate remote IP & AE Title
    remote = event.assoc.remote
    logger.info(f"C-ECHO from: {remote}")
    return C_ECHO_SUCCESS


# DICOM C-STORE scp event handler (EVT_C_STORE)):
def _handle_store(event: Event, storage_dir) -> int:
    global destination_dir
    logger.debug("_handle_store")
    # TODO: Validate remote IP & AE Title
    remote = event.assoc.remote
    ds = event.dataset
    ds.file_meta = event.file_meta
    logger.debug(remote)
    logger.debug(ds)
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

    return C_STORE_SUCCESS


def start(address, port, aet, storage_dir):
    global scp
    logger.info("start")
    ae = AE(aet)
    # Unlimited PDU size
    ae.maximum_pdu_size = 0
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


def stop(final_shutdown=False):
    global scp
    if scp is not None:
        if not final_shutdown:
            logger.info("User initiated: Stop DICOM C-STORE scp and close socket")
        scp.shutdown()
        scp = None
    return True
