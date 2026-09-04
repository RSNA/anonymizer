"""Orthanc echo / seed helpers for QueryRetrieve screenshots."""

from __future__ import annotations

import logging
from pathlib import Path

from anonymizer.controller.project import ProjectController
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

ORTHANC_HOST = "127.0.0.1"
ORTHANC_PORT = 4242
ORTHANC_AET = "ORTHANC"


def query_scp_key() -> str:
    return _("QUERY")


def echo_orthanc(controller: ProjectController) -> bool:
    """C-ECHO to the project's QUERY SCP (default Orthanc)."""
    key = query_scp_key()
    if key not in controller.model.remote_scps:
        logger.error("Project missing QUERY remote SCP key %r", key)
        return False
    node = controller.model.remote_scps[key]
    logger.info("Echo Orthanc via %s → %s", key, node)
    return bool(controller.echo(key))


def find_any_studies(controller: ProjectController) -> list:
    key = query_scp_key()
    results = controller.find_studies(
        scp_name=key,
        name="",
        id="",
        acc_no="",
        study_date="",
        modality="",
        ux_Q=None,
        verify_attributes=False,
    )
    return list(results or [])


def find_studies_modality(controller: ProjectController, modality: str) -> list:
    key = query_scp_key()
    results = controller.find_studies(
        scp_name=key,
        name="",
        id="",
        acc_no="",
        study_date="",
        modality=modality,
        ux_Q=None,
        verify_attributes=False,
    )
    return list(results or [])


def seed_orthanc_ct(controller: ProjectController, dicom_paths: list[str]) -> int:
    """Ensure Orthanc has at least one CT study for modality=CT Query screenshots."""
    existing = find_studies_modality(controller, "CT")
    if existing:
        logger.info("Orthanc already has %s CT study result(s); skip CT seed", len(existing))
        return 0
    paths = dicom_paths[:80]
    if not paths:
        raise RuntimeError("No CT DICOM paths available to seed Orthanc")
    key = query_scp_key()
    logger.info("Seeding Orthanc with %s CT file(s) via C-STORE to %s", len(paths), key)
    sent = controller.send(paths, key)
    logger.info("Seeded Orthanc CT: %s file(s) sent", sent)
    return sent


def seed_orthanc_if_empty(controller: ProjectController, dicom_paths: list[str]) -> int:
    """
    If Orthanc has no studies, C-STORE a small set of test files into QUERY SCP.

    Returns number of files sent (0 if already populated or send skipped).
    """
    existing = find_any_studies(controller)
    if existing:
        logger.info("Orthanc already has %s study result(s); skip seed", len(existing))
        return 0

    # Prefer a small subset so seed is fast.
    paths = dicom_paths[:40]
    if not paths:
        raise RuntimeError("No DICOM paths available to seed Orthanc")

    key = query_scp_key()
    logger.info("Seeding Orthanc with %s file(s) via C-STORE to %s", len(paths), key)
    sent = controller.send(paths, key)
    logger.info("Seeded Orthanc: %s file(s) sent", sent)
    return sent


def assert_orthanc_reachable(controller: ProjectController) -> None:
    if not echo_orthanc(controller):
        raise RuntimeError(
            f"Orthanc C-ECHO failed for {ORTHANC_AET}@{ORTHANC_HOST}:{ORTHANC_PORT}. "
            "Start Orthanc locally before capturing QueryRetrieveImport."
        )
