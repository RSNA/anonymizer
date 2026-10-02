"""C-ECHO SCU."""

from __future__ import annotations

import logging
import threading
from queue import Queue

from pydicom import Dataset
from pynetdicom.association import Association
from pynetdicom.status import VERIFICATION_SERVICE_CLASS_STATUS

from anonymizer.controller.dicom.requests import EchoRequest, EchoResponse
from anonymizer.model.project import DICOMNode, DICOMRuntimeError
from anonymizer.utils.dicom import C_SUCCESS
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class EchoMixin:
    def echo(self, scp: str | DICOMNode, ux_Q: Queue | None = None) -> bool:
        """
        Perform C-ECHO operation to the specified SCP.

        Args:
            scp (str | DICOMNode): The SCP (Service Class Provider) to send the C-ECHO request to.
            ux_Q (Queue | None, optional):
                For asynchronous operation via echo_ex, the optional queue to put the EchoResponse object into. Defaults to None.

        Returns:
            bool: True if the C-ECHO operation is successful, False otherwise.
        """
        logger.info(f"Perform C-ECHO from {self.model.scu} to {scp}")
        echo_association: Association | None = None
        try:
            echo_association = self._connect_to_scp(scp, [self.get_verification_context()])

            status: Dataset = echo_association.send_c_echo()
            if not status:
                raise ConnectionError(_("Connection timed out, was aborted, or received an invalid response"))

            if status.Status == C_SUCCESS:
                logger.info("C-ECHO Success")
                if ux_Q:
                    ux_Q.put(EchoResponse(success=True, error=None))
                echo_association.release()
                return True
            else:
                raise DICOMRuntimeError(f"C-ECHO Failed status: {VERIFICATION_SERVICE_CLASS_STATUS[status.Status][1]}")

        except Exception as e:
            error = f"{(e)}"
            logger.error(error)
            if ux_Q:
                ux_Q.put(EchoResponse(success=False, error=error))
            if echo_association:
                echo_association.release()
            return False

    def echo_ex(self, er: EchoRequest) -> None:
        """
        Executes the echo method in a separate thread.

        Args:
            er (EchoRequest): The EchoRequest object containing the scp and ux_Q parameters.
        """
        threading.Thread(target=self.echo, name="ECHO", args=(er.scp, er.ux_Q)).start()

