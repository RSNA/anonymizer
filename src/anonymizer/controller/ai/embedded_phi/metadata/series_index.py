"""Series-level metadata PHI index: per-SOP rows + unique free-text strings.

Public API
----------
intern_string(value: str, pool: dict[str, str]) -> str
    Return a pooled string so identical values share one object.

intern_metadata_rows(rows: Sequence[MetadataPhiRow], pool: dict[str, str]) -> tuple[MetadataPhiRow, ...]
    Intern text / span leaf strings across rows (and across SOPs via shared pool).

extract_sop_metadata_rows(ds: Dataset, *, resolve_keep=None, string_pool: dict[str, str] | None=None, mark_iod: bool=True) -> tuple[MetadataPhiRow, ...]
    Extract PHI metadata rows for one instance, optionally flag IOD-unexpected,

unique_metadata_texts(metadata_by_sop: Mapping[str, Sequence[MetadataPhiRow]]) -> tuple[str, ...]
    First-seen unique non-empty free-text / SEQ(text) values across the series.

metadata_text_occurrence_count(metadata_by_sop: Mapping[str, Sequence[MetadataPhiRow]]) -> int
    Count non-date text/SEQ cells (pre-dedupe) — useful for efficiency asserts.
"""
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    MetadataPhiRow,
    SpanFragment,
    extract_metadata_phi_rows,
)
from anonymizer.controller.ai.embedded_phi.metadata.iod_allowlist import load_dicom_info, mark_iod_unexpected

logger = logging.getLogger(__name__)


def intern_string(value: str, pool: dict[str, str]) -> str:
    """Return a pooled string so identical values share one object."""
    return pool.setdefault(value, value)


def intern_metadata_rows(
    rows: Sequence[MetadataPhiRow],
    pool: dict[str, str],
) -> tuple[MetadataPhiRow, ...]:
    """Intern text / span leaf strings across rows (and across SOPs via shared pool)."""
    out: list[MetadataPhiRow] = []
    for row in rows:
        text = intern_string(row.text, pool)
        spans = tuple(
            SpanFragment(
                start=span.start,
                end=span.end,
                tag_path=span.tag_path,
                leaf_text=intern_string(span.leaf_text, pool),
            )
            for span in row.spans
        )
        if text is row.text and spans == row.spans:
            out.append(row)
        else:
            out.append(replace(row, text=text, spans=spans))
    return tuple(out)


def extract_sop_metadata_rows(
    ds: Dataset,
    *,
    resolve_keep=None,
    string_pool: dict[str, str] | None = None,
    mark_iod: bool = True,
) -> tuple[MetadataPhiRow, ...]:
    """
    Extract PHI metadata rows for one instance, optionally flag IOD-unexpected,
    and intern strings into string_pool.
    """
    rows = extract_metadata_phi_rows(ds, resolve_keep=resolve_keep)
    if mark_iod:
        sop_class = str(getattr(ds, "SOPClassUID", "") or "")
        try:
            rows = mark_iod_unexpected(
                rows, sop_class, dicom_info=load_dicom_info()
            )
        except Exception:
            logger.warning(
                "IOD unexpected marking failed for SOP Class %s; leaving flags clear",
                sop_class,
                exc_info=True,
            )
    pool = string_pool if string_pool is not None else {}
    return intern_metadata_rows(rows, pool)


def unique_metadata_texts(
    metadata_by_sop: Mapping[str, Sequence[MetadataPhiRow]],
) -> tuple[str, ...]:
    """
    First-seen unique non-empty free-text / SEQ(text) values across the series.

    Dates (DA/DT) are omitted — Detect/NER uses this index for text only; date
    shift uses uncovered date rows on each SOP.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for rows in metadata_by_sop.values():
        for row in rows:
            if row.is_date:
                continue
            text = str(row.text).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            unique.append(text)
    return tuple(unique)


def metadata_text_occurrence_count(
    metadata_by_sop: Mapping[str, Sequence[MetadataPhiRow]],
) -> int:
    """Count non-date text/SEQ cells (pre-dedupe) — useful for efficiency asserts."""
    return sum(
        1 for rows in metadata_by_sop.values() for row in rows if not row.is_date
    )
