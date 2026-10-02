"""WADO-RS retrieve helpers → pydicom Dataset iterators."""

from __future__ import annotations

import email
import logging
from email.policy import default as email_policy
from io import BytesIO
from typing import Callable, Iterator, Literal
from urllib.parse import quote

from pydicom import Dataset, dcmread

from anonymizer.controller.dicom.dicomweb.session import DicomWebSession
from anonymizer.model.project import DICOMRuntimeError

logger = logging.getLogger(__name__)

RetrieveLevel = Literal["STUDY", "SERIES", "INSTANCE"]


def _parse_multipart_dicom(content_type: str, body: bytes) -> list[Dataset]:
    """Parse multipart/related WADO-RS response into DICOM datasets."""
    # email.message_from_bytes needs a full MIME message with headers
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
    msg = email.message_from_bytes(header.encode("utf-8") + body, policy=email_policy)
    datasets: list[Dataset] = []
    if not msg.is_multipart():
        # Single-part application/dicom
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes) and payload:
            datasets.append(dcmread(BytesIO(payload), force=True))
        return datasets
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = (part.get_content_type() or "").lower()
        if "application/dicom" not in ctype and ctype not in ("", "application/octet-stream"):
            # Still try parts that look like DICOM binaries
            if "json" in ctype or "xml" in ctype:
                continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload:
            continue
        try:
            datasets.append(dcmread(BytesIO(payload), force=True))
        except Exception as exc:
            logger.warning("Skip WADO part parse error: %s", exc)
    return datasets


def _raise_for_status(resp, *, label: str) -> None:
    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        raise DICOMRuntimeError(f"{label} HTTP {resp.status_code}: {detail}")


def _retrieve_url(
    session: DicomWebSession,
    *,
    study_uid: str,
    series_uid: str | None = None,
    instance_uid: str | None = None,
) -> str:
    study = quote(study_uid, safe="")
    if series_uid is None:
        return session.url("studies", study)
    series = quote(series_uid, safe="")
    if instance_uid is None:
        return session.url("studies", study, "series", series)
    inst = quote(instance_uid, safe="")
    return session.url("studies", study, "series", series, "instances", inst)


def iter_instances(
    session: DicomWebSession,
    *,
    study_uid: str,
    series_uid: str | None = None,
    instance_uid: str | None = None,
    abort_check: Callable[[], bool] | None = None,
) -> Iterator[Dataset]:
    """
    WADO-RS retrieve of study, series, or instance; yields decoded Datasets.

    Does not call the anonymizer — callers feed each Dataset into their store path.
    """
    if abort_check and abort_check():
        raise RuntimeError("Retrieve aborted")
    url = _retrieve_url(session, study_uid=study_uid, series_uid=series_uid, instance_uid=instance_uid)
    headers = {"Accept": "multipart/related; type=application/dicom; transfer-syntax=*"}
    resp = session.http.get(url, headers=headers, timeout=session.timeout, stream=True)
    try:
        if abort_check and abort_check():
            raise RuntimeError("Retrieve aborted")
        _raise_for_status(resp, label=f"WADO-RS {url}")
        content_type = resp.headers.get("Content-Type", "")
        body = resp.content
        if "multipart" in content_type.lower():
            datasets = _parse_multipart_dicom(content_type, body)
        else:
            datasets = [dcmread(BytesIO(body), force=True)] if body else []
    finally:
        resp.close()

    for ds in datasets:
        if abort_check and abort_check():
            raise RuntimeError("Retrieve aborted")
        yield ds
