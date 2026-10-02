"""C-STORE SCU (send files to a remote SCP)."""

from __future__ import annotations

import logging

from pynetdicom.status import STORAGE_SERVICE_CLASS_STATUS

from anonymizer.controller.dicom import dicomweb as dicomweb_api
from anonymizer.model.project import DICOMRuntimeError

logger = logging.getLogger(__name__)


class StoreMixin:
    def send(self, file_paths: list[str], scp_name: str, send_contexts=None) -> int:
        """
        Blocking call: Sends a list of files to a specified SCP (Service Class Provider).

        Args:
            file_paths (list[str]): A list of file paths to be sent.
            scp_name (str): The name of the SCP to send the files to as defined in the model's remote_scps dictionary.
            send_contexts (Optional): The radiology storage contexts to use for sending.
                If not provided, the default radiology storage contexts will be used.

        Returns:
            int: The number of files successfully sent.

        Raises:
            Any Exception raised by pynetdicom or the underlying transport layer.

        TODO: Memory management, handling large datasets and many concurrent sends
        Do not decode dataset, send raw chunks no larger than max PDU of peer
        see: _config.STORE_SEND_CHUNKED_DATASET
        https://pydicom.github.io/pynetdicom/dev/reference/generated/pynetdicom._config.STORE_SEND_CHUNKED_DATASET.html
        * exact matching accepted presentation context required *

        """
        logger.debug(f"Send {len(file_paths)} files to {scp_name}")
        node = self._resolve_remote(scp_name)
        if node.dicomweb:
            try:
                with dicomweb_api.open_session(node, self.model.network_timeouts) as session:
                    return dicomweb_api.store_files(session, file_paths)
            except Exception as e:
                logger.error("STOW-RS Send Error: %s", e)
                raise

        association = None
        files_sent = 0

        if send_contexts is None:
            send_contexts = self.get_radiology_storage_contexts()

        try:
            association = self._connect_to_scp(scp_name, send_contexts)
            for dicom_file_path in file_paths:
                dcm_response = association.send_c_store(dataset=dicom_file_path)
                if dcm_response.Status != 0:
                    raise DICOMRuntimeError(f"DICOM Response: {STORAGE_SERVICE_CLASS_STATUS[dcm_response.Status][1]}")
                files_sent += 1
        except Exception as e:
            logger.error(f"Send Error: {e}")
            raise

        finally:
            if association:
                association.release()

        return files_sent

