"""Local C-ECHO / C-STORE SCP handlers and server lifecycle."""

from __future__ import annotations

import logging
import time
from typing import List, cast

from psutil import virtual_memory
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.uid import UID
from pynetdicom.events import EVT_C_ECHO, EVT_C_STORE, Event, EventHandlerType

from anonymizer.model.project import DICOMNode, DICOMRuntimeError
from anonymizer.utils.dicom import C_STORE_DATASET_ERROR, C_STORE_DECODE_ERROR, C_SUCCESS
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class ScpMixin:
    def _handle_echo(self, event: Event):
        """
        Handles the C-ECHO event. Always returns the echo request with success.

        Args:
            event (Event): The event object containing the C-ECHO request.

        Returns:
            int: The status code indicating the success of the C-ECHO operation.
        """
        logger.debug("_handle_echo")
        remote = event.assoc.remote
        logger.info(f"C-ECHO from: {remote}")
        return C_SUCCESS

    def _handle_store(self, event: Event):
        """
        DICOM C-STORE scp event handler (EVT_C_STORE)
        Event handler called in the thread context of an SCP association. (up to 10 concurrent associations)

        Args:
            event (Event): The event containing the DICOM dataset to be stored.

        Returns:
            int: The result code indicating the success or failure of the storage operation.
        """
        # Throttle incoming requests by adding a delay to ensure UX responsiveness
        time.sleep(self._handle_store_time_slice_interval)

        # TODO: investigate use of pynetdicom temporary storage for large datasets
        # Instead pass the Event.dataset_path to the Anonymizer workers for processing only metadata, leave pixel data on disk using dcm_read(stop_before_pixels=True)
        # see: https://pydicom.github.io/pynetdicom/dev/reference/generated/pynetdicom._config.STORE_RECV_CHUNKED_DATASET.html

        # Back-off if AnonymizerQueue grows to a limit determined by available memory:
        if virtual_memory().available < self._memory_available_backoff_threshold:
            time.sleep(1)

        logger.debug("_handle_store")
        remote = event.assoc.remote
        try:
            ds = Dataset(event.dataset)
            # Remove any File Meta (Group 0x0002 elements) that may have been included
            ds = ds[0x00030000:]
        except Exception as exc:
            logger.error("Unable to decode incoming dataset")
            logger.exception(exc)
            # Unable to decode dataset
            return C_STORE_DECODE_ERROR

        # Add the File Meta Information (Group 0x0002 elements)
        ds.file_meta = FileMetaDataset(event.file_meta)

        # File Metadata:Implementation Class UID and Version Name:
        ds.file_meta.ImplementationClassUID = UID(self.model.IMPLEMENTATION_CLASS_UID)  # UI: (0002,0012)
        ds.file_meta.ImplementationVersionName = self.model.IMPLEMENTATION_VERSION_NAME  # SH: (0002,0013)

        remote_scu = DICOMNode(remote["address"], remote["port"], remote["ae_title"], False)
        logger.debug(remote_scu)

        # DICOM Dataset integrity checking:
        # TODO: send to quarantine?
        missing_attributes = self.anonymizer.missing_attributes(ds)
        if missing_attributes != []:
            logger.error(f"Incoming dataset is missing required attributes: {missing_attributes}")
            logger.error(f"\n{ds}")
            return C_STORE_DATASET_ERROR

        if self.anonymizer.model.instance_received(ds.SOPInstanceUID):
            logger.debug(
                f"Instance already stored:{ds.PatientID}/{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}"
            )
            return C_SUCCESS

        self.anonymizer.anonymize_dataset_ex(remote_scu, ds)
        return C_SUCCESS

    def start_scp(self) -> None:
        logger.info(f"start {self.model.scp}, {self.model.storage_dir}...")

        if self.scp:
            msg = _("DICOM C-STORE scp is already running on") + f" {self.model.scp}"
            logger.error(msg)
            raise DICOMRuntimeError(msg)

        handlers = [(EVT_C_ECHO, self._handle_echo), (EVT_C_STORE, self._handle_store)]
        self._reset_scp_vars()
        self._ae_title = self.model.scu.aet

        try:
            self.scp = self.start_server(
                (self.model.scp.ip, self.model.scp.port),
                block=False,
                evt_handlers=cast(List[EventHandlerType], handlers),
            )
        except Exception as e:
            msg = _("Failed to start DICOM C-STORE scp on") + f" {self.model.scp}, Error: {str(e)}"
            logger.error(msg)
            raise DICOMRuntimeError(msg) from e

        logger.info(
            f"DICOM C-STORE scp listening on {self.model.scp}, storing files in {self.model.storage_dir}, timeouts: {self.model.network_timeouts}"
        )

    def stop_scp(self) -> None:
        if not self.scp:
            logger.error("stop_scp called but self.scp is None")
            return
        logger.info(f"Stop {self.model.scp} scp and close socket")
        self.scp.shutdown()
        self._reset_scp_vars()

