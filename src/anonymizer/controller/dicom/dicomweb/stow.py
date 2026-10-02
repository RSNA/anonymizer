"""STOW-RS store helpers."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Callable, Iterable

from anonymizer.controller.dicom.dicomweb.session import DicomWebSession
from anonymizer.model.project import DICOMRuntimeError

logger = logging.getLogger(__name__)


def _build_multipart(file_paths: list[str], boundary: str) -> bytes:
    parts: list[bytes] = []
    for path in file_paths:
        data = Path(path).read_bytes()
        header = (
            f"--{boundary}\r\n"
            f"Content-Type: application/dicom\r\n"
            f'Content-Location: {Path(path).name}\r\n'
            f"\r\n"
        ).encode("utf-8")
        parts.append(header + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts)


def store_files(
    session: DicomWebSession,
    file_paths: Iterable[str],
    *,
    abort_check: Callable[[], bool] | None = None,
) -> int:
    """
    STOW-RS POST of DICOM files to ``.../studies``.

    Returns the number of files included in a successful request.
    Raises DICOMRuntimeError on HTTP failure.
    """
    paths = [str(p) for p in file_paths]
    if not paths:
        return 0
    if abort_check and abort_check():
        raise RuntimeError("Store aborted")

    # STOW one file per request so abort/progress stay granular (matches DIMSE per-file send).
    stored = 0
    url = session.url("studies")
    for path in paths:
        if abort_check and abort_check():
            raise RuntimeError("Store aborted")
        boundary = f"boundary_{uuid.uuid4().hex}"
        body = _build_multipart([path], boundary)
        headers = {
            "Content-Type": f"multipart/related; type=application/dicom; boundary={boundary}",
            "Accept": "application/dicom+json, application/json, */*",
        }
        resp = session.http.post(url, data=body, headers=headers, timeout=session.timeout)
        if resp.status_code not in (200, 202):
            detail = (resp.text or "")[:300]
            raise DICOMRuntimeError(f"STOW-RS HTTP {resp.status_code}: {detail}")
        stored += 1
        logger.debug("STOW-RS stored %s", path)
    return stored
