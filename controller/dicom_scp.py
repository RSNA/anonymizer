import logging
from pathlib import Path
from plistlib import UID
import customtkinter as ctk

from pydicom._version import __version__ as pydicom_version
from pydicom.uid import UID
from pydicom.filewriter import write_file_meta_info

from pynetdicom._version import __version__ as pynetdicom_version
from pynetdicom.dimse_primitives import C_STORE
from pynetdicom.events import Event, EVT_C_STORE
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import AllStoragePresentationContexts

logger = logging.getLogger(__name__)

# Global var to hold storage directory passed to start():
destination_dir = ""
# Store SCP after ae.start_server() is called:
scp = None

# C-STORE status values from DICOM Standard, Part 7:
# https://dicom.nema.org/medical/dicom/current/output/chtml/part07/chapter_9.html#sect_9.1.1
# https://pydicom.github.io/pynetdicom/stable/reference/generated/pynetdicom._handlers.doc_handle_store.html
# Non-Service Class specific statuses - PS3.7 Annex C
C_STORE_SUCCESS = 0x0000
C_STORE_NOT_AUTHORISED = 0x0124
C_STORE_OUT_OF_RESOURCES = 0xA700
C_STORE_DATASET_ERROR = 0xA900  # Dataset does not match SOP class
C_STORE_DUPLICATE_INVOCATION = 0x0210
C_STORE_DECODE_ERROR = 0xC210
C_STORE_UNRECOGNIZED_OPERATION = 0xC211
C_STORE_PROCESSING_FAILURE = 0x0110


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


def loghandler(textbox: ctk.CTkTextbox):
    logger.info("loghandler")
    ch = TextBoxHandler(textbox)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)


# DICOM C-STORE SCP event handler:
def _handle_store(event: Event) -> int:
    logger.info("handle_store")
    remote = event.assoc.remote
    logger.info(remote)
    incoming_filename = Path(
        destination_dir, event.request.AffectedSOPInstanceUID + ".dcm"  # type: ignore
    )
    logger.info(f"Save incoming DICOM file: {incoming_filename}")
    with open(incoming_filename, "wb") as f:
        # Write the preamble and prefix
        f.write(b"\x00" * 128)
        f.write(b"DICM")
        # Encode and write the File Meta Information
        write_file_meta_info(f, event.file_meta, enforce_standard=True)  # type: ignore
        # Write the encoded dataset
        f.write(event.request.DataSet.getvalue())  # type: ignore

    return C_STORE_SUCCESS


def start(address, port, aet, storage_dir):
    global scp
    logger.info("start")
    destination_dir = storage_dir
    ae = AE(aet)
    # Unlimited PDU size
    ae.maximum_pdu_size = 0

    try:
        scp = ae.start_server(
            (address, port),
            block=False,
            evt_handlers=[(EVT_C_STORE, _handle_store)],
            contexts=AllStoragePresentationContexts,
        )
    except Exception as e:
        logger.error(
            f"Failed to start DICOM C-STORE SCP on {address}:{port}, with AE Title = {aet}, Error: {str(e)}"
        )
        return False

    logger.info(
        f"DICOM C-STORE SCP listening on {address}:{port}, with AE Title = {aet}"
    )
    return True


def stop(final_shutdown=False):
    global scp
    if scp is not None:
        if not final_shutdown:
            logger.info("User initiated: Stop DICOM C-STORE SCP and close socket")
        scp.shutdown()
        scp = None
    return True
