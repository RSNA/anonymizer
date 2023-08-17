import os
import logging
from pynetdicom.events import Event, EVT_C_STORE, EVT_C_ECHO
from pynetdicom.ae import ApplicationEntity as AE
from controller.dicom_return_codes import C_SUCCESS, C_STORE_OUT_OF_RESOURCES
from controller.anonymize import anonymize_dataset
from controller.dicom_ae import (
    DICOMRuntimeError,
    set_network_timeout,
    set_radiology_storage_contexts,
    set_verification_context,
)
from utils.translate import _
from utils.storage import local_storage_path
from model.project import SITEID, PROJECTNAME, TRIALNAME, UIDROOT

logger = logging.getLogger(__name__)

# TODO: convert to singleton class

# Store scp instance after ae.start_server() is called:
scp = None


# Is SCP running?
def server_running() -> bool:
    global scp
    return scp is not None


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
    logger.info("_handle_store")
    # TODO: Validate remote IP & AE Title
    remote = event.assoc.remote
    ds = event.dataset
    ds.file_meta = event.file_meta
    logger.debug(remote)
    logger.debug(f"PHI:\n{ds}")
    # TODO: ensure ds has values for PatientName, Modality, StudyDate, StudyTime, SeriesNumber, InstanceNumber
    ds = anonymize_dataset(ds)
    logger.debug(f"ANON:\n{ds}")
    filename = local_storage_path(storage_dir, SITEID, ds)
    logger.info(
        f"C-STORE [{ds.file_meta.TransferSyntaxUID}]: {remote['ae_title']} => {filename}"
    )
    try:
        ds.save_as(filename, write_like_original=False)
    except Exception as exception:
        logger.error("Failed writing instance to storage directory")
        logger.exception(exception)
        return C_STORE_OUT_OF_RESOURCES

    return C_SUCCESS


# Start SCP:
def start(address, port, aet, storage_dir):
    """
    Starts the DICOM C-STORE service class provider (SCP).

    Parameters:
    - address (str): The IP address or hostname the server will bind to.
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
    global scp
    logger.info(f"start {address}, {port}, {aet}, {storage_dir}...")

    if server_running():
        msg = _(f"DICOM C-STORE scp is already running on {address}:{port}:{aet}")
        logger.error(msg)
        raise DICOMRuntimeError(msg)

    # Make sure storage directory exists:
    os.makedirs(storage_dir, exist_ok=True)

    ae = AE(aet)
    ae.maximum_pdu_size = 0  # no limit
    set_network_timeout(ae)
    set_radiology_storage_contexts(ae)
    set_verification_context(ae)

    handlers = [(EVT_C_ECHO, _handle_echo), (EVT_C_STORE, _handle_store, [storage_dir])]

    try:
        scp = ae.start_server(
            (address, port),
            block=False,
            evt_handlers=handlers,
        )
    except Exception as e:
        msg = _(
            f"Failed to start DICOM C-STORE scp on {address}:{port}, with AE Title = {aet}, Error: {str(e)}"
        )
        logger.error(msg)
        raise DICOMRuntimeError(msg)

    logger.info(
        f"DICOM C-STORE scp listening on {address}:{port}, with AE Title = {aet}, storing files in {storage_dir}"
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
