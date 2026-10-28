"""Synthetic metadata PHI catalog helpers for controller unit tests.

Loads planted public/private free-text rows from
tests/fixtures/phi_text/metadata_phi_catalog.jsonl, builds minimal Secondary
Capture datasets, and maps extract rows to MetadataNerItem for detect tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    extract_metadata_phi_rows,
    is_anonymizer_field,
)
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import MetadataNerItem

_CATALOG_PATH = (
    Path(__file__).resolve().parents[4] / "fixtures" / "phi_text" / "metadata_phi_catalog.jsonl"
)


def catalog_path() -> Path:
    """Absolute path to the committed metadata PHI catalog."""
    return _CATALOG_PATH


def load_metadata_phi_catalog(*, path: Path | None = None) -> list[dict[str, Any]]:
    """
    Load catalog rows from JSONL.

    Args:
        path: Override catalog path (tests only).

    Returns:
        One dict per non-empty JSONL line.
    """
    source = path or catalog_path()
    rows: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        rows.append(json.loads(stripped))
    return rows


def catalog_by_id(*, path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Index catalog rows by id."""
    return {str(row["id"]): row for row in load_metadata_phi_catalog(path=path)}


def resolve_plant_rows(
    row: Mapping[str, Any],
    *,
    by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Expand a catalog row into concrete plant specs.

    Combo rows (scope both / plant_ids) expand to the referenced plants;
    other rows are returned as a single-element list.
    """
    plant_ids = row.get("plant_ids")
    if plant_ids:
        index = by_id if by_id is not None else catalog_by_id()
        out: list[dict[str, Any]] = []
        for plant_id in plant_ids:
            planted = index[str(plant_id)]
            if planted.get("plant_ids"):
                raise ValueError(f"nested combo not supported: {plant_id}")
            out.append(dict(planted))
        return out
    return [dict(row)]


def _sc_dataset() -> Dataset:
    """Minimal Secondary Capture dataset for planting PHI carriers."""
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "OT"
    return ds


def _plant_public(ds: Dataset, row: Mapping[str, Any]) -> None:
    keyword = str(row["keyword"])
    text = str(row["text"])
    setattr(ds, keyword, text)
    patient_id = row.get("patient_id")
    if patient_id:
        ds.PatientID = str(patient_id)


def _plant_private(ds: Dataset, row: Mapping[str, Any]) -> None:
    creator = str(row["private_creator"])
    group = int(row["group"])
    suffix = int(row["element_suffix"])
    vr = str(row.get("vr") or "LO")
    text = str(row["text"])
    block = ds.private_block(group, creator, create=True)
    block.add_new(suffix, vr, text)


def plant_row(ds: Dataset, row: Mapping[str, Any]) -> None:
    """Plant one public or private catalog plant onto ds."""
    scope = str(row.get("scope") or "")
    if scope == "public":
        _plant_public(ds, row)
        return
    if scope == "private":
        _plant_private(ds, row)
        return
    raise ValueError(f"cannot plant scope={scope!r} for id={row.get('id')!r}")


def build_dataset_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> Dataset:
    """
    Build a minimal SC dataset planting every public keyword and private block.

    Combo rows expand via plant_ids. Multiple PatientID values: last wins.
    """
    ds = _sc_dataset()
    index = by_id if by_id is not None else catalog_by_id()
    for row in rows:
        for plant in resolve_plant_rows(row, by_id=index):
            plant_row(ds, plant)
    return ds


def build_dataset_for_id(
    catalog_id: str,
    *,
    by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> Dataset:
    """Build a dataset for one catalog id (including combo rows)."""
    index = by_id if by_id is not None else catalog_by_id()
    return build_dataset_from_rows([index[catalog_id]], by_id=index)


def ner_items_from_dataset(ds: Dataset) -> list[MetadataNerItem]:
    """
    Map extract_metadata_phi_rows to MetadataNerItem for detect/filter tests.

    Mirrors the assessment dialog's field_name / VR / tag_path facts without
    importing the view layer.
    """
    items: list[MetadataNerItem] = []
    for row in extract_metadata_phi_rows(ds):
        items.append(
            MetadataNerItem(
                text=row.text,
                field_name=row.name,
                tag=row.tag,
                vr=row.vr,
                tag_path=row.tag_path,
                is_anonymizer_field=is_anonymizer_field(
                    tag=row.tag,
                    name=row.name,
                    tag_path=row.tag_path,
                ),
                is_date=row.is_date,
            )
        )
    return items


def extract_public_private(
    ds: Dataset,
) -> tuple[list[Any], list[Any]]:
    """Split extract rows into (public, private) lists."""
    rows = extract_metadata_phi_rows(ds)
    public = [r for r in rows if not r.is_private]
    private = [r for r in rows if r.is_private]
    return public, private


def assert_private_names_include_creators(
    private_rows: Iterable[Any],
    creators: Sequence[str],
) -> None:
    """Require each private row display name to mention a known creator."""
    names = [str(r.name) for r in private_rows]
    assert names, "expected at least one private extract row"
    for name in names:
        assert name.casefold() != "private"
        assert any(creator in name for creator in creators), (
            f"private display name {name!r} missing creators {list(creators)!r}"
        )
