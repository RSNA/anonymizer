"""QIDO-RS query helpers → pydicom Datasets."""

from __future__ import annotations

import logging
from typing import Any, Callable
from urllib.parse import quote

from pydicom import Dataset
from pydicom.datadict import dictionary_VR, tag_for_keyword
from pydicom.tag import Tag

from anonymizer.controller.dicom.dicomweb.session import DicomWebSession
from anonymizer.model.project import DICOMRuntimeError

logger = logging.getLogger(__name__)

# Keywords requested / mapped for study-level find (match FindMixin identifiers).
STUDY_INCLUDEFIELDS = (
    "StudyInstanceUID",
    "PatientName",
    "PatientID",
    "PatientSex",
    "PatientBirthDate",
    "StudyDate",
    "StudyDescription",
    "AccessionNumber",
    "ModalitiesInStudy",
    "NumberOfStudyRelatedSeries",
    "NumberOfStudyRelatedInstances",
    "SOPClassesInStudy",
)

SERIES_INCLUDEFIELDS = (
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SeriesNumber",
    "SeriesDescription",
    "Modality",
    "SOPClassUID",
    "NumberOfSeriesRelatedInstances",
)

INSTANCE_INCLUDEFIELDS = (
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SOPInstanceUID",
    "InstanceNumber",
    "SOPClassUID",
)


def _tag_hex(keyword: str) -> str:
    tag = tag_for_keyword(keyword)
    if tag is None:
        raise KeyError(f"Unknown DICOM keyword: {keyword}")
    t = Tag(tag)
    return f"{t.group:04X}{t.element:04X}"


def _includefield_params(keywords: tuple[str, ...]) -> list[tuple[str, str]]:
    return [("includefield", _tag_hex(k)) for k in keywords]


def qido_json_to_dataset(item: dict[str, Any]) -> Dataset:
    """Map one QIDO-RS DICOM JSON object to a pydicom Dataset."""
    ds = Dataset()
    for key, entry in item.items():
        if not isinstance(entry, dict):
            continue
        try:
            tag = Tag(int(key, 16))
        except (TypeError, ValueError):
            continue
        values = entry.get("Value")
        if values is None:
            continue
        if not values:
            continue
        # PersonName objects → Alphabetic string
        flat: list[Any] = []
        for v in values:
            if isinstance(v, dict) and "Alphabetic" in v:
                flat.append(v["Alphabetic"])
            else:
                flat.append(v)
        if len(flat) == 1:
            value: Any = flat[0]
        else:
            value = flat
        try:
            vr = entry.get("vr") or dictionary_VR(tag)
            ds.add_new(tag, vr, value)
        except Exception:
            # Fallback: set by keyword if known
            try:
                from pydicom.datadict import keyword_for_tag

                kw = keyword_for_tag(tag)
                if kw:
                    setattr(ds, kw, value)
            except Exception:
                logger.debug("Skip unmapped QIDO tag %s", key)
    return ds


def _raise_for_status(resp, *, label: str) -> None:
    if resp.status_code == 204:
        return
    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        raise DICOMRuntimeError(f"{label} HTTP {resp.status_code}: {detail}")


def _get_json(
    session: DicomWebSession,
    path_parts: tuple[str, ...],
    params: list[tuple[str, str]],
    *,
    label: str,
    abort_check: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    if abort_check and abort_check():
        raise RuntimeError("Query aborted")
    url = session.url(*path_parts)
    resp = session.http.get(url, params=params, timeout=session.timeout)
    if abort_check and abort_check():
        raise RuntimeError("Query aborted")
    if resp.status_code == 204:
        return []
    _raise_for_status(resp, label=label)
    data = resp.json()
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    if not isinstance(data, list):
        raise DICOMRuntimeError(f"{label}: unexpected JSON type {type(data).__name__}")
    return data


def find_studies(
    session: DicomWebSession,
    *,
    patient_name: str = "",
    patient_id: str = "",
    accession: str = "",
    study_date: str = "",
    modality: str = "",
    abort_check: Callable[[], bool] | None = None,
) -> list[Dataset]:
    """QIDO-RS study search matching FindMixin find_studies filters."""
    params: list[tuple[str, str]] = []
    if patient_name:
        params.append(("PatientName", patient_name))
    if patient_id:
        params.append(("PatientID", patient_id))
    if accession:
        params.append(("AccessionNumber", accession))
    if study_date:
        params.append(("StudyDate", study_date))
    if modality:
        params.append(("ModalitiesInStudy", modality))
    params.extend(_includefield_params(STUDY_INCLUDEFIELDS))

    items = _get_json(session, ("studies",), params, label="QIDO-RS studies", abort_check=abort_check)
    return [qido_json_to_dataset(item) for item in items]


def find_series(
    session: DicomWebSession,
    study_uid: str,
    *,
    abort_check: Callable[[], bool] | None = None,
) -> list[Dataset]:
    """QIDO-RS series for a study."""
    params = _includefield_params(SERIES_INCLUDEFIELDS)
    uid = quote(study_uid, safe="")
    items = _get_json(
        session,
        ("studies", uid, "series"),
        params,
        label=f"QIDO-RS series[{study_uid}]",
        abort_check=abort_check,
    )
    return [qido_json_to_dataset(item) for item in items]


def find_instances(
    session: DicomWebSession,
    study_uid: str,
    series_uid: str,
    *,
    abort_check: Callable[[], bool] | None = None,
) -> list[Dataset]:
    """QIDO-RS instances for a series."""
    params = _includefield_params(INSTANCE_INCLUDEFIELDS)
    study = quote(study_uid, safe="")
    series = quote(series_uid, safe="")
    items = _get_json(
        session,
        ("studies", study, "series", series, "instances"),
        params,
        label=f"QIDO-RS instances[{study_uid}/{series_uid}]",
        abort_check=abort_check,
    )
    return [qido_json_to_dataset(item) for item in items]
