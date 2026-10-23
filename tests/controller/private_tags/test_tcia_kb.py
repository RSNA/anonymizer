"""TCIA private-tag KB_OPERATION + Retain Safe XX collapse."""

from __future__ import annotations

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.anonymizer import AnonymizerController
from anonymizer.controller.dates import dateinc_days, incrementdate_operand
from anonymizer.controller.private_tags import (
    PrivateTagAction,
    collapse_retain_safe_action,
    lookup_private_tag,
    private_tag_operation,
)
from anonymizer.controller.private_tags.tcia_kb_data import PRIVATE_KB
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.model.project import RETAIN_OPTIONS, ProjectModel
from tests.paths import DEFAULT_ANONYMIZER_SCRIPT

_DEFAULT = DEFAULT_ANONYMIZER_SCRIPT


def test_private_tag_operation_branches() -> None:
    dateinc_days.cache_clear()
    date_op = incrementdate_operand()
    assert date_op == "@incrementdate(this,-3670)"

    ds = Dataset()
    keep = lookup_private_tag(creator="GEMS_PETD_01", group=0x0009, element_suffix=0x0F)
    assert keep is not None and keep.action is PrivateTagAction.KEEP
    block = ds.private_block(0x0009, "GEMS_PETD_01", create=True)
    block.add_new(0x0F, "ST", "scan")
    elem = next(e for e in ds if e.tag.is_private and (e.tag.element & 0xFF) == 0x0F)
    assert private_tag_operation(ds, elem, retain_uids=False, date_delta=-1) == "@keep"

    block.add_new(0x05, "DA", "20200115")
    date_elem = next(e for e in ds if e.tag.is_private and (e.tag.element & 0xFF) == 0x05)
    assert (
        private_tag_operation(ds, date_elem, retain_uids=False, date_delta=-3670)
        == date_op
    )
    assert (
        private_tag_operation(ds, date_elem, retain_uids=False, date_delta=None)
        == "@remove()"
    )

    other = Dataset()
    ob = other.private_block(0x7777, "NoSuch", create=True)
    ob.add_new(0x10, "LO", "x")
    unk = next(e for e in other if e.tag.is_private and not e.tag.is_private_creator)
    assert private_tag_operation(other, unk, retain_uids=False, date_delta=-1) == "@remove()"


def test_collapse_keep_beats_delete() -> None:
    assert (
        collapse_retain_safe_action({PrivateTagAction.KEEP, PrivateTagAction.REMOVE})
        is PrivateTagAction.KEEP
    )
    assert collapse_retain_safe_action({PrivateTagAction.REMOVE}) is PrivateTagAction.REMOVE
    assert (
        collapse_retain_safe_action(
            {PrivateTagAction.DATE_DELTA, PrivateTagAction.KEEP, PrivateTagAction.REMOVE}
        )
        is PrivateTagAction.DATE_DELTA
    )
    assert (
        collapse_retain_safe_action({PrivateTagAction.UID, PrivateTagAction.KEEP})
        is PrivateTagAction.UID
    )


def test_default_script_has_no_private_rows() -> None:
    import xml.etree.ElementTree as ET

    root = ET.parse(_DEFAULT).getroot()
    for e in root.findall("e"):
        tag = (e.attrib.get("t") or "").upper()
        assert "XX" not in tag, tag
        if len(tag) >= 4:
            assert int(tag[:4], 16) % 2 == 0, tag


def test_match_creator_aware_same_xx() -> None:
    """Same XX slot: creator A keep vs B delete — lookup is creator-specific."""
    any_k = any_d = None
    for (_c, group, suffix), entry in PRIVATE_KB.items():
        if group != 0x0009 or suffix != 0x01:
            continue
        if entry.action is PrivateTagAction.KEEP and any_k is None:
            any_k = entry
        if entry.action is PrivateTagAction.REMOVE and any_d is None:
            any_d = entry
    assert any_k is not None and any_d is not None
    hit_k = lookup_private_tag(creator=any_k.creator, group=0x0009, element_suffix=0x01)
    hit_d = lookup_private_tag(creator=any_d.creator, group=0x0009, element_suffix=0x01)
    assert hit_k is not None and hit_k.action is PrivateTagAction.KEEP
    assert hit_d is not None and hit_d.action is PrivateTagAction.REMOVE
    assert lookup_private_tag(creator="NoSuchCreator_XYZ", group=0x0009, element_suffix=0x01) is None


def _sc_ds() -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientID = "TCIA-CREATOR-TEST"
    ds.StudyDate = "20200101"
    ds.Modality = "OT"
    return ds


def test_safe_private_walk_applies_kb_operations(tmp_path: Path) -> None:
    """With Retain Safe Private the walk removes KB-delete privates and keeps KB-keep ones."""
    del_creator = None
    for (_c, group, suffix), entry in PRIVATE_KB.items():
        if group == 0x0009 and suffix == 0x01 and entry.action is PrivateTagAction.REMOVE:
            del_creator = entry.creator
            break
    assert del_creator

    model = ProjectModel(
        storage_dir=tmp_path / "store",
        confidentiality_options=RETAIN_OPTIONS,
    )
    model.anonymizer_script_path = _DEFAULT
    ctrl = AnonymizerController.__new__(AnonymizerController)
    ctrl._active = False
    ctrl.project_model = model
    ctrl.model = AnonymizerModel(
        model.site_id,
        model.uid_root,
        _DEFAULT,
        f"sqlite:///{tmp_path / 'a.db'}",
    )
    from tests.opened_anonymizer_model import load_model_script

    load_model_script(ctrl.model, _DEFAULT)
    ctrl._clean_tag_translate_table = str.maketrans("", "", "() ,")

    ds = _sc_ds()
    ds.private_block(0x0009, del_creator, create=True).add_new(0x01, "LO", "delete-me")
    elem = next(e for e in ds if e.tag.is_private and int(e.tag.element) & 0xFF == 0x01)
    ctrl._anonymize_element(ds, elem, "phi", "anon", None, 0)
    assert elem.tag not in ds

    ds.private_block(0x0009, "GEMS_PETD_01", create=True).add_new(0x0F, "LO", "keep-me")
    keep_elem = next(e for e in ds if e.tag.is_private and int(e.tag.element) & 0xFF == 0x0F)
    ctrl._anonymize_element(ds, keep_elem, "phi", "anon", None, 0)
    assert keep_elem.value == "keep-me"
    assert keep_elem.tag in ds
