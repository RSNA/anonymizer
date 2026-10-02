"""Association timeouts, presentation contexts, and SCP connect helper."""

from __future__ import annotations

import logging
from typing import List

from pynetdicom.association import Association
from pynetdicom.events import EventHandlerType
from pynetdicom.presentation import PresentationContext, build_context, build_role

from anonymizer.model.project import DICOMNode, NetworkTimeouts
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class AssociationMixin:
    def set_dicom_timeouts(self, timeouts: NetworkTimeouts):
        # The maximum amount of time (in seconds) to wait for a TCP connection to be established:
        # only used during the connection phase of an association request.
        self._connection_timeout = timeouts.tcp_connection
        # ACSE: association timeout
        # The maximum amount of time (in seconds) to wait for association related messages.
        self._acse_timeout = timeouts.acse
        # DICOM Message Service Element timeout
        # The maximum amount of time (in seconds) to wait for DIMSE related messages.
        self._dimse_timeout = timeouts.dimse
        # Network timeout
        # The maximum amount of time (in seconds) to wait for network messages before closing an association:
        self._network_timeout = timeouts.network

    def get_network_timeouts(self) -> NetworkTimeouts:
        return self.model.network_timeouts

    def set_verification_context(self):
        self.add_supported_context(self._VERIFICATION_CLASS)
        return

    def set_radiology_storage_contexts(self) -> None:
        for uid in sorted(self.model.storage_classes):
            self.add_supported_context(uid, self.model.transfer_syntaxes)
        return

    def get_verification_context(self) -> PresentationContext:
        return build_context(self._VERIFICATION_CLASS)

    def get_radiology_storage_contexts(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, self.model.transfer_syntaxes)
            for abstract_syntax in self.model.storage_classes
        ]

    def set_study_root_qr_contexts(self) -> None:
        for uid in sorted(self._STUDY_ROOT_QR_CLASSES):
            self.add_supported_context(uid)
        return

    def get_radiology_storage_contexts_BIGENDIAN(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, "1.2.840.10008.1.2.2")
            for abstract_syntax in self.model.storage_classes
        ]

    def get_study_root_qr_contexts(self) -> List[PresentationContext]:
        return [
            build_context(abstract_syntax, self.model.transfer_syntaxes)
            for abstract_syntax in self._STUDY_ROOT_QR_CLASSES
        ]

    def get_study_root_find_contexts(self) -> List[PresentationContext]:
        return [build_context(self._STUDY_ROOT_QR_CLASSES[0])]

    def get_study_root_move_contexts(self) -> List[PresentationContext]:
        return [build_context(self._STUDY_ROOT_QR_CLASSES[1])]

    def get_study_root_get_contexts(self) -> List[PresentationContext]:
        """Study-Root C-GET plus storage contexts (instances return on the same association)."""
        return [build_context(self._STUDY_ROOT_QR_CLASSES[2])] + self.get_radiology_storage_contexts()

    def _storage_scp_roles(self):
        """SCP/SCU Role Selection: requestor is SCP for storage SOP classes (C-GET receive)."""
        return [build_role(uid, scp_role=True, scu_role=False) for uid in self.model.storage_classes]

    def _resolve_remote(self, scp: str | DICOMNode) -> DICOMNode:
        """Resolve a remote SCP name or node to a ``DICOMNode`` (shared by DIMSE and DICOMweb)."""
        if isinstance(scp, str):
            if scp not in self.model.remote_scps:
                raise ConnectionError(f"Remote SCP {scp} not found")
            return self.model.remote_scps[scp]
        return scp

    def _connect_to_scp(
        self,
        scp: str | DICOMNode,
        contexts: List[PresentationContext],
        evt_handlers: List[EventHandlerType] | None = None,
        ext_neg=None,
    ) -> Association:
        """
        Connects to a remote DICOM SCP and establishes an association.

        Args:
            scp: Remote SCP name (in model.remote_scps) or DICOMNode.
            contexts: Presentation contexts to negotiate.
            evt_handlers: Optional association event handlers (e.g. EVT_C_STORE for C-GET).
            ext_neg: Optional extended negotiation items (e.g. SCP/SCU role selection for C-GET).
        """
        remote_scp = self._resolve_remote(scp)

        try:
            association = self.associate(
                remote_scp.ip,
                remote_scp.port,
                contexts=contexts,
                ae_title=remote_scp.aet,
                bind_address=(self.model.scu.ip, 0),
                evt_handlers=evt_handlers,
                ext_neg=ext_neg,
            )
            if not association.is_established:
                raise ConnectionError(_("Connection error to") + f": {remote_scp}")
            logger.debug(f"Association established with {association.acceptor.ae_title}")
        except Exception as e:
            logger.error(f"Error establishing association: {e}")
            raise

        return association
