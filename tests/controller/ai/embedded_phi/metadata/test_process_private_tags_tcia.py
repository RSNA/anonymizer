"""Creator-aware TCIA private KB apply (process_private_tags_tcia)."""

from __future__ import annotations

import csv
from pathlib import Path

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from anonymizer.controller.ai.embedded_phi.metadata.process_private_tags_tcia import (
    process_private_tags_tcia,
)
from anonymizer.controller.ai.embedded_phi.metadata.tcia_kb import load_tcia_private_kb


def _private_data_elem(ds: Dataset, creator: str, elem_xx: int, vr: str, value: object):
    block = ds.private_block(0x0009, creator, create=True)
    block.add_new(elem_xx, vr, value)
    return next(
        e
        for e in ds
        if e.tag.is_private
        and not getattr(e.tag, "is_private_creator", False)
        and (int(e.tag.element) & 0xFF) == elem_xx
        and ds[e.tag.group, int(e.tag.element) >> 8].value == creator
    )


def test_k_kept_d_removed_same_xx_different_creators() -> None:
    keep_c = del_c = None
    for e in load_tcia_private_kb():
        if e.group_element.upper() != "0009XX01":
            continue
        if e.action.lower() == "k" and keep_c is None:
            keep_c = e.creator
        if e.action.lower() == "d" and del_c is None:
            del_c = e.creator
    assert keep_c and del_c and keep_c != del_c

    ds = Dataset()
    ds.SOPInstanceUID = "1.2.3.keep_d"
    keep_elem = _private_data_elem(ds, keep_c, 0x01, "LO", "keep-me")
    del_elem = _private_data_elem(ds, del_c, 0x01, "LO", "delete-me")
    keep_tag, del_tag = keep_elem.tag, del_elem.tag

    process_private_tags_tcia(ds, dateinc=-3670)
    assert keep_tag in ds
    assert ds[keep_tag].value == "keep-me"
    assert del_tag not in ds


def test_unknown_private_removed_creator_kept() -> None:
    ds = Dataset()
    ds.SOPInstanceUID = "1.2.3.unknown"
    block = ds.private_block(0x7777, "NoSuchCreatorXYZ", create=True)
    block.add_new(0x10, "LO", "gone")
    data_tag = next(
        e.tag
        for e in ds
        if e.tag.is_private and not getattr(e.tag, "is_private_creator", False)
    )
    creator_tag = next(
        e.tag for e in ds if getattr(e.tag, "is_private_creator", False)
    )
    process_private_tags_tcia(ds, dateinc=-1)
    assert data_tag not in ds
    assert creator_tag in ds
    assert ds[creator_tag].value == "NoSuchCreatorXYZ"


def test_skip_anonymizer_group_0013() -> None:
    ds = Dataset()
    ds.SOPInstanceUID = "1.2.3.anon"
    block = ds.private_block(0x0013, "ANONYMIZER", create=True)
    block.add_new(0x10, "LO", "site")
    data_tag = next(
        e.tag
        for e in ds
        if e.tag.is_private
        and int(e.tag.group) == 0x0013
        and not getattr(e.tag, "is_private_creator", False)
    )
    process_private_tags_tcia(ds, dateinc=-1)
    assert data_tag in ds
    assert ds[data_tag].value == "site"


def test_o_dateinc_and_h_uid(tmp_path: Path) -> None:
    kb = tmp_path / "kb.csv"
    with kb.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["group_element", "creator", "action", "note", "vr"]
        )
        w.writeheader()
        w.writerow(
            {
                "group_element": "0009XX20",
                "creator": "DateCreator",
                "action": "o",
                "note": "Some Date",
                "vr": "DA",
            }
        )
        w.writerow(
            {
                "group_element": "0009XX21",
                "creator": "UidCreator",
                "action": "h",
                "note": "Some UID",
                "vr": "UI",
            }
        )

    ds = Dataset()
    ds.SOPInstanceUID = "1.2.3.oh"
    date_elem = _private_data_elem(ds, "DateCreator", 0x20, "DA", "20200115")
    # Separate group block for second creator on same odd group needs own creator slot.
    uid_block = ds.private_block(0x0009, "UidCreator", create=True)
    uid_block.add_new(0x21, "UI", "1.2.3.4.5.old")
    uid_elem = next(
        e
        for e in ds
        if e.tag.is_private
        and (int(e.tag.element) & 0xFF) == 0x21
        and not getattr(e.tag, "is_private_creator", False)
    )
    uid_map: dict[str, str] = {}
    process_private_tags_tcia(ds, kb_path=kb, dateinc=-10, uid_map=uid_map)
    assert date_elem.tag in ds
    assert ds[date_elem.tag].value == "20200105"
    assert uid_elem.tag in ds
    assert ds[uid_elem.tag].value != "1.2.3.4.5.old"
    assert "1.2.3.4.5.old" in uid_map
    assert uid_map["1.2.3.4.5.old"] == ds[uid_elem.tag].value


def test_nested_sequence_private_disposition(tmp_path: Path) -> None:
    kb = tmp_path / "kb.csv"
    with kb.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["group_element", "creator", "action", "note", "vr"]
        )
        w.writeheader()
        w.writerow(
            {
                "group_element": "0009XX30",
                "creator": "NestCreator",
                "action": "d",
                "note": "nested",
                "vr": "LO",
            }
        )

    inner = Dataset()
    block = inner.private_block(0x0009, "NestCreator", create=True)
    block.add_new(0x30, "LO", "nested-phi")
    data_tag = next(
        e.tag
        for e in inner
        if e.tag.is_private and not getattr(e.tag, "is_private_creator", False)
    )

    ds = Dataset()
    ds.SOPInstanceUID = "1.2.3.nest"
    ds.ReferencedImageSequence = Sequence([inner])
    process_private_tags_tcia(ds, kb_path=kb, dateinc=-1)
    assert data_tag not in ds.ReferencedImageSequence[0]
