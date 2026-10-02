"""Helpers for Orthanc dicom_integration tests (managed Orthanc lifecycle)."""

from __future__ import annotations

import logging

import pytest

from anonymizer.controller.project import ProjectController
from tests.controller.dicom.support.orthanc_bundle import (
    ManagedOrthanc,
    OrthancBundleError,
    in_ci,
    wipe_patients_via_rest,
)
from tests.controller.dicom.support.test_nodes import OrthancDicomWeb, OrthancSCP

logger = logging.getLogger(__name__)


def enable_orthanc_dimse_remote(controller: ProjectController, managed: ManagedOrthanc | None = None) -> None:
    node = managed.dimse if managed is not None else OrthancSCP
    controller.model.remote_scps[OrthancSCP.aet] = node


def enable_orthanc_dicomweb_remote(controller: ProjectController, managed: ManagedOrthanc | None = None) -> None:
    """Point the project's Orthanc remote at DICOMweb (QIDO/WADO/STOW + test/test)."""
    node = managed.dicomweb if managed is not None else OrthancDicomWeb
    controller.model.remote_scps[OrthancSCP.aet] = node


def wipe_orthanc(managed: ManagedOrthanc | None = None) -> None:
    """Clear Orthanc patients between tests (REST)."""
    del managed  # process still running; wipe via HTTP
    wipe_patients_via_rest()


def require_managed_or_skip(exc: BaseException) -> None:
    """In CI re-raise; locally convert OrthancBundleError into pytest.skip."""
    if isinstance(exc, OrthancBundleError) and not in_ci():
        pytest.skip(str(exc))
    raise exc
