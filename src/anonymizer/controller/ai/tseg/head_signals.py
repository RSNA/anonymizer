"""Head vs non-head signals from DICOM metadata and cached region labels (leaf; no pipeline deps)."""

from __future__ import annotations

from enum import StrEnum, auto

from pydicom import Dataset


class MetadataSignal(StrEnum):
    HEAD = auto()
    NON_HEAD = auto()
    AMBIGUOUS = auto()


class CachedRegionSignal(StrEnum):
    HEAD = auto()
    NON_HEAD = auto()
    MULTI_REGION = auto()
    UNAVAILABLE = auto()


# DICOM keyword heuristics (not user-facing).
_HEAD_KEYWORDS: tuple[str, ...] = (
    "HEAD",
    "BRAIN",
    "SKULL",
    "NECK",
    "ORBIT",
    "SINUS",
    "FACIAL",
    "CEREB",
    "STROKE",
    "CTA HEAD",
    "HEAD NECK",
)

_NON_HEAD_KEYWORDS: tuple[str, ...] = (
    "CHEST",
    "THOR",
    "ABDOM",
    "PELV",
    "LUNG",
    "LIVER",
    "RENAL",
    "KUB",
    "EXTREM",
    "LOWER LIMB",
    "UPPER LIMB",
    "FOOT",
    "ANKLE",
    "KNEE",
    "HIP",
)


def _dicom_search_text(ds: Dataset | None) -> str:
    if ds is None:
        return ""
    parts = [
        getattr(ds, "BodyPartExamined", None),
        getattr(ds, "SeriesDescription", None),
        getattr(ds, "ProtocolName", None),
        getattr(ds, "StudyDescription", None),
    ]
    return " ".join(str(part).strip() for part in parts if part).upper()


def metadata_signal(ds: Dataset | None) -> MetadataSignal:
    text = _dicom_search_text(ds)
    if not text:
        return MetadataSignal.AMBIGUOUS
    has_head = any(keyword in text for keyword in _HEAD_KEYWORDS)
    has_non_head = any(keyword in text for keyword in _NON_HEAD_KEYWORDS)
    if has_head and not has_non_head:
        return MetadataSignal.HEAD
    if has_non_head and not has_head:
        return MetadataSignal.NON_HEAD
    return MetadataSignal.AMBIGUOUS
