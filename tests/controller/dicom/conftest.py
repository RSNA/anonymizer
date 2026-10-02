"""Session-scoped managed Orthanc for dicom_integration tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from tests.controller.dicom.support.orthanc_bundle import (
    ManagedOrthanc,
    OrthancBundleError,
    in_ci,
    start_orthanc,
    stop_orthanc,
)
from tests.controller.dicom.support.test_nodes import LocalStorageSCP


@pytest.fixture(scope="session")
def managed_orthanc() -> Generator[ManagedOrthanc, None, None]:
    """Download (if needed), configure, and start Orthanc for the dicom_integration session."""
    try:
        managed = start_orthanc(scp_port=LocalStorageSCP.port, scp_aet=LocalStorageSCP.aet, wipe=True)
    except OrthancBundleError as exc:
        if in_ci():
            raise
        pytest.skip(f"Managed Orthanc unavailable: {exc}")
    yield managed
    stop_orthanc(managed)
