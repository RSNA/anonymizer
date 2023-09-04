import os
import logging
import time
from pynetdicom.events import Event, EVT_C_STORE, EVT_C_ECHO
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.transport import ThreadedAssociationServer
from controller.dicom_return_codes import C_SUCCESS, C_DATA_ELEMENT_DOES_NOT_EXIST
from controller.anonymize import anonymize_dataset_and_store, uid_lookup
from controller.dicom_ae import (
    DICOMNode,
    DICOMRuntimeError,
    set_network_timeout,
    set_radiology_storage_contexts,
    set_verification_context,
)
from utils.translate import _

logger = logging.getLogger(__name__)

# TODO: convert to singleton class inheriting from pynetdicom.AE

# Store scp instance after ae.start_server() is called:
scp: ThreadedAssociationServer | None = None
active_storage_dir: str | None = None  # latched when scp is started
_handle_store_time_slice_interval = 0.1  # seconds

# Required DICOM field attributes for C-STORE and C_FIND results:
required_attributes = [
    "PatientID",
    "PatientName",
    "StudyInstanceUID",
    "StudyDate",
    #   "AccessionNumber",
    "Modality",
    "SeriesNumber",
    "InstanceNumber",
]


# Is SCP running?
def server_running() -> bool:
    global scp
    return scp is not None


def get_active_storage_dir():
    global active_storage_dir
    assert active_storage_dir is not None
    return active_storage_dir


def get_storage_scp_aet():
    global scp
    if scp is None:
        return None
    return scp.ae_title


# DICOM C-ECHO Verification event handler (EVT_C_ECHO)
def _handle_echo(event: Event) -> int:
    logger.debug("_handle_echo")
    # TODO: Validate remote IP & AE Title
    remote = event.assoc.remote
    logger.info(f"C-ECHO from: {remote}")
    return C_SUCCESS


# DICOM C-STORE scp event handler (EVT_C_STORE)):
def _handle_store(event: Event, storage_dir: str) -> int:
    # Throttle incoming requests by adding a delay
    # time.sleep(_handle_store_time_slice_interval)  # to ensure UX responsiveness
    logger.debug("_handle_store")
    # TODO: Validate remote IP & AE Title
    remote = event.assoc.remote
    ds = event.dataset
    ds.file_meta = event.file_meta
    scu = DICOMNode(remote["address"], remote["port"], remote["ae_title"], False)
    logger.debug(scu)
    if not all(attr_name in ds for attr_name in required_attributes):
        missing_attributes = [
            attr_name for attr_name in required_attributes if attr_name not in ds
        ]
        logger.error(
            f"DICOM C-STORE request is missing required attributes: {missing_attributes}"
        )
        logger.error(f"\n{ds}")
        return C_DATA_ELEMENT_DOES_NOT_EXIST
    logger.debug(f"PHI:\n{ds}")
    # Return success if study already stored:
    if ds.SOPInstanceUID in uid_lookup:
        logger.info(f"Instance already stored: {ds.PatientID} {ds.SOPInstanceUID}")
        return C_SUCCESS
    anonymize_dataset_and_store(scu, ds, storage_dir)
    return C_SUCCESS


# Start SCP:
def start(addr: DICOMNode, storage_dir: str):
    """
    Starts the DICOM C-STORE service class provider (SCP).

    Parameters:
    - addr (DICOMNode): The DICOMNode object containing the following attributes:
        - ip (str): The IP address or hostname the server will bind to.
        - port (int): The port number the server will listen on.
        - aet (str): The Application Entity Title the server will use.
    - storage_dir (str): Directory path where incoming DICOM files will be stored.

    Raises:
    - DICOMRuntimeError: If the SCP is already running or if there's an error starting the server.

    Returns:
    None

    Note:
    The function will log informative and error messages using the logger.
    """
    global scp, active_storage_dir
    logger.info(f"start {addr.ip}, {addr.port}, {addr.aet}, {storage_dir}...")
    active_storage_dir = storage_dir

    if server_running():
        msg = _(
            f"DICOM C-STORE scp is already running on {addr.ip}:{addr.port}:{addr.aet}"
        )
        logger.error(msg)
        raise DICOMRuntimeError(msg)

    # Make sure storage directory exists:
    os.makedirs(storage_dir, exist_ok=True)

    ae = AE(addr.aet)
    ae.maximum_pdu_size = 0  # no limit
    set_network_timeout(ae)
    set_radiology_storage_contexts(ae)
    set_verification_context(ae)

    handlers = [(EVT_C_ECHO, _handle_echo), (EVT_C_STORE, _handle_store, [storage_dir])]

    try:
        scp = ae.start_server(
            (addr.ip, addr.port),
            block=False,
            evt_handlers=handlers,
        )
    except Exception as e:
        msg = _(
            f"Failed to start DICOM C-STORE scp on {addr.ip}:{addr.port}, with AE Title = {addr.aet}, Error: {str(e)}"
        )
        logger.error(msg)
        raise DICOMRuntimeError(msg)

    logger.info(
        f"DICOM C-STORE scp listening on {addr.ip}:{addr.port}, with AE Title = {addr.aet}, storing files in {storage_dir}"
    )
    return


# Stop SCP:
def stop(final_shutdown=False) -> None:
    """
    Stops the DICOM C-STORE service class provider (SCP).

    Parameters:
    - final_shutdown (bool, optional): Indicates if this stop action is the final shutdown.
                                       If True, certain log messages are suppressed.
                                       Defaults to False.

    Returns:
    None

    Note:
    The function will log an informative message on user-initiated stops.
    """
    global scp
    if not final_shutdown:
        logger.info("User initiated: Stop DICOM C-STORE scp and close socket")
    if not scp:
        return
    scp.shutdown()
    scp = None
