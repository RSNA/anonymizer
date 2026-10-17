"""TCIA private disposition → operand + Retain Safe XX collapse."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.assets.scripts.diff_clinical_table1 import diff_vs_table1
from anonymizer.controller.ai.embedded_phi.metadata.process_private_tags_tcia import (
    collapse_retain_safe_action,
    tcia_disposition_to_operand,
)
from anonymizer.controller.ai.embedded_phi.metadata.tcia_kb import match_tcia_private
from anonymizer.controller.anonymizer import AnonymizerController
from anonymizer.model.project import AnonymizationPolicy, ProjectModel

_REPO = Path(__file__).resolve().parents[2]
_CLINICAL = _REPO / "src/anonymizer/assets/scripts/clinical-anonymizer.script"
_TABLE1 = _REPO / "src/anonymizer/assets/anonymization_policy/tcia_table1_ctp_ops.csv"


def test_disposition_vr_gates() -> None:
    from anonymizer.controller.ai.embedded_phi.metadata.process_private_tags_tcia import (
        clinical_dateinc_days,
        incrementdate_operand,
    )

    clinical_dateinc_days.cache_clear()
    date_op = incrementdate_operand()
    assert date_op == "@incrementdate(this,-3670)"
    assert tcia_disposition_to_operand("k") == ""
    assert tcia_disposition_to_operand("d") == "@remove()"
    assert tcia_disposition_to_operand("o", vr="DT") == date_op
    assert tcia_disposition_to_operand("o", vr="SL") == "@remove()"
    assert tcia_disposition_to_operand("h", vr="UI") == "@uid"
    assert tcia_disposition_to_operand("h", vr="LO") == "@remove()"
    assert tcia_disposition_to_operand("h", note="Some UID") == "@uid"


def test_collapse_keep_beats_delete() -> None:
    assert collapse_retain_safe_action({"k", "d"}) == "k"
    assert collapse_retain_safe_action({"d"}) == "d"
    assert collapse_retain_safe_action({"d", "d"}) == "d"
    assert collapse_retain_safe_action({"o", "k", "d"}) == "o"
    assert collapse_retain_safe_action({"h", "k"}) == "h"


def test_clinical_script_fine_tunes_vs_table1() -> None:
    """Clinical diverges from the Table 1 CSV in known product ways."""
    msgs = diff_vs_table1(_CLINICAL, _TABLE1)
    joined = "\n".join(msgs)
    assert "00102180" in joined  # Occupation kept vs Table 1 @remove
    assert "00120051" in joined  # ClinicalTrialTimePointDescription removed
    # @safe() equipment tags are mostly absent from Table 1 (defer-keep + product op).
    root = ET.parse(_CLINICAL).getroot()
    by = {e.attrib["t"].upper(): (e.text or "").strip() for e in root.findall("e")}
    assert by.get("00081090") in ("@safe()", "@safe")


def test_clinical_script_code_meaning_and_process() -> None:
    root = ET.parse(_CLINICAL).getroot()
    by = {e.attrib["t"].upper(): (e.text or "").strip() for e in root.findall("e")}
    assert by.get("00080104") in ("", "@keep", "@keep()")
    assert by.get("00080100") in ("", "@keep", "@keep()")  # CodeValue — not in Table 1
    assert by.get("0040A160") in ("", "@keep", "@keep()")
    assert by.get("0040A730") == "@process()"
    assert by.get("00081010") == "@remove()"  # Station Name — no Retain Device
    assert by.get("00181000") == "@remove()"  # Device Serial Number
    # PET science tags absent from Table 1 must not inherit default @remove().
    assert by.get("00541201") in ("", "@keep", "@keep()")  # AxialMash
    assert by.get("00540016") in ("", "@keep", "@keep()")  # RadiopharmaceuticalInformationSeq
    assert by.get("00081032") in ("", "@keep", "@keep()")  # ProcedureCodeSeq
    # Gold-keep default overrides Table 1 @remove for Occupation (and siblings).
    assert by.get("00102180") in ("", "@keep", "@keep()")
    assert by.get("00204000") in ("", "@keep", "@keep()")  # ImageComments
    assert by.get("00181200", "").startswith("@incrementdate")  # DateOfLastCalibration (MIDI date_shifted)
    assert by.get("00181201") in ("", "@keep", "@keep()")  # TimeOfLastCalibration
    assert by.get("0018700C") == "@remove()"  # DateOfLastDetectorCalibration (Table 1 / PseudoPHI gold)
    assert by.get("00082111") in ("", "@keep", "@keep()")  # DerivationDescription
    assert by.get("00104000") in ("", "@keep", "@keep()")  # PatientComments
    assert by.get("00380500") in ("", "@keep", "@keep()")  # PatientState
    assert by.get("00400009") in ("", "@keep", "@keep()")  # SPSID


def test_clinical_script_has_no_private_rows() -> None:
    root = ET.parse(_CLINICAL).getroot()
    for e in root.findall("e"):
        tag = (e.attrib.get("t") or "").upper()
        assert "XX" not in tag, tag
        if len(tag) >= 4:
            assert int(tag[:4], 16) % 2 == 0, tag


def test_match_creator_aware_same_xx() -> None:
    """Same XX slot: creator A keep vs B delete — match is creator-specific."""
    from anonymizer.controller.ai.embedded_phi.metadata.tcia_kb import load_tcia_private_kb

    any_k = None
    any_d = None
    for e in load_tcia_private_kb():
        if e.group_element.upper() != "0009XX01":
            continue
        if e.action.lower() == "k" and any_k is None:
            any_k = e
        if e.action.lower() == "d" and any_d is None:
            any_d = e
    assert any_k is not None and any_d is not None
    hit_k = match_tcia_private("00091001", creator=any_k.creator)
    hit_d = match_tcia_private("00091001", creator=any_d.creator)
    assert hit_k is not None and hit_k.action.lower() == "k"
    assert hit_d is not None and hit_d.action.lower() == "d"
    assert match_tcia_private("00091001", creator="NoSuchCreator_XYZ") is None


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


def test_clinical_ingest_leaves_private_tags_untouched(tmp_path: Path) -> None:
    """Clinical walk skips private tags (flag set once; Embedded PHI owns cleanup)."""
    from anonymizer.controller.ai.embedded_phi.metadata.tcia_kb import load_tcia_private_kb
    from anonymizer.model.anonymizer import AnonymizerModel

    del_creator = None
    for e in load_tcia_private_kb():
        if e.group_element.upper() == "0009XX01" and e.action.lower() == "d":
            del_creator = e.creator
            break
    assert del_creator

    model = ProjectModel(
        storage_dir=tmp_path / "store",
        anonymization_policy=AnonymizationPolicy.CLINICAL,  # type: ignore[arg-type]
    )
    model.anonymizer_script_path = _CLINICAL
    ctrl = AnonymizerController.__new__(AnonymizerController)
    ctrl._active = False
    ctrl.project_model = model
    ctrl.model = AnonymizerModel(
        model.site_id,
        model.uid_root,
        _CLINICAL,
        f"sqlite:///{tmp_path / 'a.db'}",
    )
    ctrl._preserve_private_tags = True
    ctrl._clean_tag_translate_table = str.maketrans("", "", "() ,")

    ds = _sc_ds()
    ds.private_block(0x0009, del_creator, create=True).add_new(0x01, "LO", "leave-me")
    elem = next(e for e in ds if e.tag.is_private and int(e.tag.element) & 0xFF == 0x01)
    ctrl._anonymize_element(ds, elem, "phi", "anon", None, 0, None)
    assert elem.value == "leave-me"
    assert elem.tag in ds
