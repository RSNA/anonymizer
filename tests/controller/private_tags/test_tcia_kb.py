"""TCIA private-tag KB_OPERATION + Retain Safe XX collapse."""

import xml.etree.ElementTree as ET
from pathlib import Path

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
from tests.controller.private_tags.support_private_ds import (
    KbSample,
    apply_private_specs,
    find_private_element,
    minimal_sc_dataset,
    placeholder_value,
    sample_kb_entries,
    spec_from_kb,
    unknown_private_spec,
)
from tests.opened_anonymizer_model import load_model_script
from tests.paths import DEFAULT_ANONYMIZER_SCRIPT

_DEFAULT = DEFAULT_ANONYMIZER_SCRIPT


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
    assert collapse_retain_safe_action(set()) is None


def test_default_script_has_no_private_rows() -> None:
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


def test_private_tag_operation_kb_samples() -> None:
    """KB-sourced KEEP / REMOVE / DATE_DELTA / unknown resolve to the right operands."""
    dateinc_days.cache_clear()
    date_op = incrementdate_operand()
    assert date_op == "@incrementdate(this,-3670)"

    keep = sample_kb_entries(
        PrivateTagAction.KEEP, vr_in=frozenset({"LO", "ST", "CS"}), limit=1
    )[0]
    remove = sample_kb_entries(
        PrivateTagAction.REMOVE, vr_in=frozenset({"LO", "ST", "CS"}), limit=1
    )[0]
    date = sample_kb_entries(
        PrivateTagAction.DATE_DELTA, vr_in=frozenset({"DA", "DT"}), limit=1
    )[0]
    specs = [
        spec_from_kb(keep, value="scan"),
        spec_from_kb(remove, value="gone"),
        spec_from_kb(date),
        unknown_private_spec(),
    ]
    ds = apply_private_specs(minimal_sc_dataset(), specs)

    assert (
        private_tag_operation(
            ds, find_private_element(ds, specs[0]), retain_uids=False, date_delta=-1
        )
        == "@keep"
    )
    assert (
        private_tag_operation(
            ds, find_private_element(ds, specs[1]), retain_uids=False, date_delta=-1
        )
        == "@remove()"
    )
    assert (
        private_tag_operation(
            ds,
            find_private_element(ds, specs[2]),
            retain_uids=False,
            date_delta=-3670,
        )
        == date_op
    )
    assert (
        private_tag_operation(
            ds,
            find_private_element(ds, specs[2]),
            retain_uids=False,
            date_delta=None,
        )
        == "@remove()"
    )
    assert (
        private_tag_operation(
            ds, find_private_element(ds, specs[3]), retain_uids=False, date_delta=-1
        )
        == "@remove()"
    )


def test_private_tag_operation_unknown_numeric_vr_kept() -> None:
    """Unknown private slots with numeric VR are kept (not free-text PHI)."""
    specs = [
        unknown_private_spec(creator="Eigen, Inc", group=0x1129, suffix=0x08, vr="DS", value="0.0"),
        unknown_private_spec(creator="Eigen, Inc", group=0x1129, suffix=0x16, vr="LO", value="secret"),
    ]
    ds = apply_private_specs(minimal_sc_dataset(), specs)
    assert (
        private_tag_operation(
            ds, find_private_element(ds, specs[0]), retain_uids=False, date_delta=None
        )
        == "@keep"
    )
    assert (
        private_tag_operation(
            ds, find_private_element(ds, specs[1]), retain_uids=False, date_delta=None
        )
        == "@remove()"
    )


def test_private_tag_operation_uid_and_retain_uids() -> None:
    """UID disposition: @uid / @keep under Retain UIDs / @remove for non-UID VRs."""
    uid_ui = sample_kb_entries(PrivateTagAction.UID, vr_in=frozenset({"UI"}), limit=1)[0]
    uid_non = None
    for sample in sample_kb_entries(PrivateTagAction.UID, vr_in=None, limit=50):
        note_u = sample.entry.note.upper()
        if sample.entry.vr.upper() != "UI" and "UID" not in note_u:
            uid_non = sample
            break
    assert uid_non is not None

    specs = [spec_from_kb(uid_ui), spec_from_kb(uid_non)]
    ds = apply_private_specs(minimal_sc_dataset(), specs)
    ui_elem = find_private_element(ds, specs[0])
    non_elem = find_private_element(ds, specs[1])

    assert private_tag_operation(ds, ui_elem, retain_uids=False, date_delta=None) == "@uid"
    assert private_tag_operation(ds, ui_elem, retain_uids=True, date_delta=None) == "@keep"
    assert private_tag_operation(ds, non_elem, retain_uids=False, date_delta=None) == "@remove()"
    assert private_tag_operation(ds, non_elem, retain_uids=True, date_delta=None) == "@keep"


def test_private_tag_operation_keeps_group_0013_and_creators() -> None:
    """App private group and private-creator elements always keep."""
    ds = minimal_sc_dataset()
    block = ds.private_block(0x0013, "RSNA", create=True)
    block.add_new(0x01, "SH", "site")
    data_elem = find_private_element(
        ds,
        unknown_private_spec(creator="RSNA", group=0x0013, suffix=0x01, vr="SH", value="site"),
    )
    assert private_tag_operation(ds, data_elem, retain_uids=False, date_delta=None) == "@keep"

    creator_elem = next(e for e in ds if e.tag.is_private_creator and e.tag.group == 0x0013)
    assert private_tag_operation(ds, creator_elem, retain_uids=False, date_delta=None) == "@keep"


def test_private_kb_entries_yield_legal_operands() -> None:
    """Every plantable PRIVATE_KB row resolves to a known operand for entry.vr."""
    dateinc_days.cache_clear()
    date_op = incrementdate_operand(-3670)
    legal = {date_op, "@keep", "@remove()", "@uid"}
    checked = 0
    skipped = 0
    for (_creator_cf, group, suffix), entry in PRIVATE_KB.items():
        if group == 0x0013 or not (entry.creator or "").strip():
            skipped += 1
            continue
        vr = (entry.vr or "LO").upper()
        if vr in {"SQ", "OW", "OB", "OF", "OD", "UN"}:
            if entry.action is PrivateTagAction.DATE_DELTA:
                skipped += 1
                continue
            vr = "LO"
        sample = KbSample(creator=entry.creator, group=group, suffix=suffix, entry=entry)
        spec = spec_from_kb(sample, value=placeholder_value(vr), vr=vr)
        try:
            ds = apply_private_specs(minimal_sc_dataset(patient_id=f"P{checked}"), [spec])
            elem = find_private_element(ds, spec)
        except Exception:
            skipped += 1
            continue
        op = private_tag_operation(ds, elem, retain_uids=False, date_delta=-3670)
        assert op in legal or op.startswith("@incrementdate("), (sample, op)
        checked += 1
    assert checked > 1000, f"expected broad KB coverage, checked={checked} skipped={skipped}"


def test_safe_private_walk_applies_kb_operations(tmp_path: Path) -> None:
    """With Retain Safe Private the walk removes KB-delete privates and keeps KB-keep ones."""
    remove = sample_kb_entries(
        PrivateTagAction.REMOVE, vr_in=frozenset({"LO", "ST", "CS"}), limit=1
    )[0]
    keep = sample_kb_entries(
        PrivateTagAction.KEEP, vr_in=frozenset({"LO", "ST", "CS"}), limit=1
    )[0]

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
    load_model_script(ctrl.model, _DEFAULT)
    ctrl._clean_tag_translate_table = str.maketrans("", "", "() ,")

    del_spec = spec_from_kb(remove, value="delete-me")
    keep_spec = spec_from_kb(keep, value="keep-me")
    ds = apply_private_specs(minimal_sc_dataset(), [del_spec])
    elem = find_private_element(ds, del_spec)
    ctrl._anonymize_element(ds, elem, "phi", "anon", None, 0)
    assert elem.tag not in ds

    ds = apply_private_specs(minimal_sc_dataset(), [keep_spec])
    keep_elem = find_private_element(ds, keep_spec)
    ctrl._anonymize_element(ds, keep_elem, "phi", "anon", None, 0)
    assert keep_elem.value == "keep-me"
    assert keep_elem.tag in ds
