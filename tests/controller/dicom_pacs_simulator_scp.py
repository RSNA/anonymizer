import logging
import os
from typing import List

from pydicom import Dataset, dcmread
from pynetdicom._globals import DEFAULT_TRANSFER_SYNTAXES  # type: ignore
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.events import EVT_C_ECHO, EVT_C_FIND, EVT_C_MOVE, EVT_C_STORE, Event
from pynetdicom.presentation import PresentationContext, build_context

from anonymizer.controller.dicom_C_codes import (
    C_CANCEL,
    C_FAILURE,
    C_MOVE_UNKNOWN_AE,
    C_PENDING_A,
    C_SOP_CLASS_INVALID,
    C_STORE_OUT_OF_RESOURCES,
    C_SUCCESS,
)
from anonymizer.model.project import DICOMNode

logger = logging.getLogger(__name__)

# TODO: create PACSimulator(AE) class as per ProjectController


_Verification_Class = "1.2.840.10008.1.1"
_STUDY_ROOT_QR_CLASSES = [
    "1.2.840.10008.5.1.4.1.2.2.1",  # Find
    "1.2.840.10008.5.1.4.1.2.2.2",  # Move
    "1.2.840.10008.5.1.4.1.2.2.3",  # Get
]

_TRANSFER_SYNTAXES = DEFAULT_TRANSFER_SYNTAXES

_RADIOLOGY_STORAGE_CLASSES = {
    "Computed Radiography Image Storage": "1.2.840.10008.5.1.4.1.1.1",
    "Computed Tomography Image Storage": "1.2.840.10008.5.1.4.1.1.2",
    "Digital X-Ray Image Storage - For Presentation": "1.2.840.10008.5.1.4.1.1.1.1",
    "Digital X-Ray Image Storage - For Processing": "1.2.840.10008.5.1.4.1.1.1.1.1",
    "Magnetic Resonance Image Storage": "1.2.840.10008.5.1.4.1.1.4",
}

_network_timeout = 3  # seconds


# Set *all* AE timeouts to the global network timeout:
def set_network_timeout(ae: AE) -> None:
    ae.acse_timeout = _network_timeout
    ae.dimse_timeout = _network_timeout
    ae.network_timeout = _network_timeout
    ae.connection_timeout = _network_timeout
    return


def get_network_timeout() -> int:
    return _network_timeout


# FOR SCP AE: Set allowed storage and verification contexts and corresponding transfer syntaxes
def set_verification_context(ae: AE):
    ae.add_supported_context(_Verification_Class, _TRANSFER_SYNTAXES)
    return


def set_radiology_storage_contexts(ae: AE) -> None:
    for uid in sorted(_RADIOLOGY_STORAGE_CLASSES.values()):
        ae.add_supported_context(uid, _TRANSFER_SYNTAXES)
    return


def set_study_root_qr_contexts(ae: AE) -> None:
    for uid in sorted(_STUDY_ROOT_QR_CLASSES):
        ae.add_supported_context(uid, _TRANSFER_SYNTAXES)
    return


def get_radiology_storage_contexts() -> List[PresentationContext]:
    return [
        build_context(abstract_syntax, _TRANSFER_SYNTAXES) for abstract_syntax in _RADIOLOGY_STORAGE_CLASSES.values()
    ]


def get_study_root_qr_contexts() -> List[PresentationContext]:
    return [build_context(abstract_syntax, _TRANSFER_SYNTAXES) for abstract_syntax in _STUDY_ROOT_QR_CLASSES]


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
    logger.debug("_handle_store")
    remote = event.assoc.remote
    ds: Dataset = event.dataset
    ds.file_meta = event.file_meta
    logger.debug(remote)
    logger.debug(ds)
    filename = os.path.join(storage_dir, f"{ds.SeriesInstanceUID}.{ds.InstanceNumber}.dcm")

    logger.debug(f"C-STORE [TxSyn:{ds.file_meta.TransferSyntaxUID}]: {remote['ae_title']} => {filename}")
    try:
        ds.save_as(filename, write_like_original=False)
    except Exception as exception:
        logger.error("Failed writing instance to storage directory")
        logger.exception(exception)
        return C_STORE_OUT_OF_RESOURCES

    return C_SUCCESS


# Implement the handler for evt.EVT_C_FIND
def _handle_find(event, storage_dir: str):
    logger.info("_handle_find")
    ds: Dataset = event.identifier

    # Get/Read ALL SOP Instances in storage_dir:
    instances = []
    for fpath in os.listdir(storage_dir):
        instances.append(dcmread(os.path.join(storage_dir, fpath)))

    if len(instances) == 0:
        logger.error("No instances in pacs file system for C-FIND response")
        return

    if "QueryRetrieveLevel" not in ds:
        # Failure
        logger.error("Missing QueryRetrieveLevel")
        yield C_FAILURE, None
        return

    # Only Search on StudyInstanceUID/SeriesInstanceUID/SOPInstanceUID
    # TODO: Add support for other search criteria

    if ds.QueryRetrieveLevel in ["STUDY", "SERIES"]:
        study_uid = ds.get("StudyInstanceUID", "")
        if study_uid == "":  # return a response for each study
            study_uids = list(set([inst.StudyInstanceUID for inst in instances if hasattr(inst, "StudyInstanceUID")]))
        else:
            study_uids = [study_uid]

        for study_uid in study_uids:
            # Get all instances matching study_uid:
            matching = [inst for inst in instances if inst.StudyInstanceUID == study_uid]

            if len(matching) == 0:
                logger.error("No matching instances for C-FIND response")
                return

            matching_modalities = list(set([inst.Modality for inst in matching if hasattr(inst, "Modality")]))
            matching_sop_classes = list(set([inst.SOPClassUID for inst in matching if hasattr(inst, "SOPClassUID")]))
            matching_series_uids = list(
                set([inst.SeriesInstanceUID for inst in matching if hasattr(inst, "SeriesInstanceUID")])
            )

            identifier = Dataset()
            identifier.QueryRetrieveLevel = ds.QueryRetrieveLevel
            identifier.StudyInstanceUID = study_uid

            m1 = matching[0]

            if hasattr(ds, "PatientName"):
                identifier.PatientName = m1.get("PatientName", "")
            if hasattr(ds, "PatientID"):
                identifier.PatientID = m1.get("PatientID", "")
            if hasattr(ds, "PatientSex"):
                identifier.PatientSex = m1.get("PatientSex", "U")
            if hasattr(ds, "PatientBirthDate"):
                identifier.PatientBirthDate = m1.get("PatientBirthDate", "")
            if hasattr(ds, "StudyDate"):
                identifier.StudyDate = m1.get("StudyDate", "")
            if hasattr(ds, "StudyDescription"):
                identifier.StudyDescription = m1.get("StudyDescription", "")
            if hasattr(ds, "AccessionNumber"):
                identifier.AccessionNumber = m1.get("AccessionNumber", "")

            if ds.QueryRetrieveLevel == "STUDY":
                identifier.ModalitiesInStudy = "".join(matching_modalities)
                identifier.SOPClassesInStudy = "".join(matching_sop_classes)
                identifier.NumberOfStudyRelatedSeries = len(matching_series_uids)
                identifier.NumberOfStudyRelatedInstances = len(matching)
                yield (C_PENDING_A, identifier)
            else:
                for series_uid in matching_series_uids:
                    series_matching = [inst for inst in matching if inst.SeriesInstanceUID == series_uid]
                    identifier.SeriesInstanceUID = series_uid
                    identifier.SeriesNumber = series_matching[0].get("SeriesNumber", "")
                    identifier.Modality = series_matching[0].get("Modality", "")
                    identifier.SOPClassUID = series_matching[0].get("SOPClassUID", "")
                    identifier.NumberOfSeriesRelatedInstances = len(series_matching)
                    yield (C_PENDING_A, identifier)
        return

    study_uid = ds.get("StudyInstanceUID", "")
    series_uid = ds.get("SeriesInstanceUID", "")
    sop_uid = ds.get("SOPInstanceUID", "")

    if sop_uid:
        matching = [inst for inst in instances if inst.SOPInstanceUID == sop_uid]
    elif series_uid:
        matching = [inst for inst in instances if inst.SeriesInstanceUID == series_uid]
    elif study_uid:
        matching = [inst for inst in instances if inst.StudyInstanceUID == study_uid]
    else:
        matching = instances

    if len(matching) == 0:
        logger.error("No matching instances for C-FIND response")
        return

    logger.info(f"Number of matching instances: {len(matching)}")

    for instance in matching:
        if event.is_cancelled:
            logger.error("C-CANCEL find operation")
            yield (C_CANCEL, None)
            return

        logger.debug(f"Return instance: {instance.SOPInstanceUID}")
        yield (C_PENDING_A, instance)

    logger.info("Find complete")


# "The C-MOVE request handler must yield the (address, port) of "
# "the destination AE, then yield the number of sub-operations, "
# "then yield (status, dataset) pairs."
def _handle_move(event, storage_dir: str, known_aet_dict: dict):
    logger.info("_handle_move")
    ds = event.identifier
    logger.info(ds)

    if "QueryRetrieveLevel" not in ds:
        # Failure
        logger.error("Missing QueryRetrieveLevel")
        yield C_SOP_CLASS_INVALID, None
        return

    # Lookup destination AE in known AEs
    if event.move_destination not in known_aet_dict:
        # Unknown destination AE
        logger.error("Unknown move destination AE")
        yield (C_MOVE_UNKNOWN_AE, None)
        return

    (addr, port) = known_aet_dict[event.move_destination]

    # Yield the IP address and listen port of the destination AE
    # and the presentation context for associating with the destination AE
    assoc_param_dict = {"contexts": get_radiology_storage_contexts()}
    logger.info(f"Yield dest ip,port:{addr, port} for AET:{event.move_destination}")
    yield (addr, port, assoc_param_dict)

    # Import stored SOP Instances
    instances = []
    matching = []
    for fpath in os.listdir(storage_dir):
        instances.append(dcmread(os.path.join(storage_dir, fpath)))

    if len(instances) == 0:
        logger.error("No instances in pacs file system for C-MOVE response")
        yield 0
        return

    logger.info(f"{len(instances)} instances found in pacs file system")

    if ds.QueryRetrieveLevel == "STUDY":
        if "StudyInstanceUID" in ds:
            matching = [inst for inst in instances if inst.StudyInstanceUID == ds.StudyInstanceUID]

    elif ds.QueryRetrieveLevel == "SERIES":
        if "StudyInstanceUID" in ds and "SeriesInstanceUID" in ds:
            matching = [
                inst
                for inst in instances
                if inst.StudyInstanceUID == ds.StudyInstanceUID and inst.SeriesInstanceUID == ds.SeriesInstanceUID
            ]

    elif ds.QueryRetrieveLevel == "IMAGE":
        if "StudyInstanceUID" in ds and "SeriesInstanceUID" in ds and "SOPInstanceUID" in ds:
            matching = [
                inst
                for inst in instances
                if inst.StudyInstanceUID == ds.StudyInstanceUID
                and inst.SeriesInstanceUID == ds.SeriesInstanceUID
                and inst.SOPInstanceUID == ds.SOPInstanceUID
            ]

    else:
        logger.error(f"Unsupported QueryRetrieveLevel: {ds.QueryRetrieveLevel}")
        yield 0
        return

    # Yield the total number of C-STORE sub-operations required
    matches = len(matching)
    logger.info(f"Matching instances: {matches}")
    if not matches:
        logger.error(f"No matching instances for C-MOVE response StudyInstanceUID={ds.StudyInstanceUID}")
        yield 0
        return

    yield matches

    # Yield the matching instances
    for instance in matching:
        # Check if C-CANCEL has been received
        if event.is_cancelled:
            logger.error("C-CANCEL move operation")
            yield (C_CANCEL, None)

        # Pending
        logger.info(
            f"Move StudyInstanceUID:{instance.StudyInstanceUID}, SeriesInstanceUID:{instance.SeriesInstanceUID}, InstanceUID:{instance.SOPInstanceUID} InstanceNumber: {instance.InstanceNumber}"
        )
        yield (C_PENDING_A, instance)

    logger.info("Move complete")


# Start SCP:
def start(addr: DICOMNode, storage_dir: str, known_nodes: list[DICOMNode]) -> bool:
    global scp
    logger.info(f"start {addr.ip}, {addr.port}, {addr.aet}, {storage_dir} ...")

    known_aet_dict = {node.aet: (node.ip, node.port) for node in known_nodes}

    if server_running():
        logger.error("PACS SIMULATOR scp is already running")
        return False

    # Make sure storage directory exists:
    os.makedirs(storage_dir, exist_ok=True)

    ae = AE(addr.aet)
    ae.maximum_pdu_size = 0  # no limit
    set_network_timeout(ae)
    set_verification_context(ae)
    set_study_root_qr_contexts(ae)
    set_radiology_storage_contexts(ae)

    handlers = [
        (EVT_C_ECHO, _handle_echo),
        (EVT_C_STORE, _handle_store, [storage_dir]),
        (EVT_C_FIND, _handle_find, [storage_dir]),
        (EVT_C_MOVE, _handle_move, [storage_dir, known_aet_dict]),
    ]

    try:
        scp = ae.start_server(
            (addr.ip, addr.port),
            block=False,
            evt_handlers=handlers,
        )
    except Exception as e:
        logger.error(f"Failed to start PACS SIMULATOR scp on {addr}, Error: {str(e)}")
        return False

    logger.info(f"PACS SIMULATOR scp listening on {addr}, storing files in {storage_dir}")
    return True


# Stop SCP:
def stop() -> None:
    global scp
    if not scp:
        return
    logger.info("Stop PACS SIMULATOR scp and close socket")
    scp.shutdown()
    scp = None
