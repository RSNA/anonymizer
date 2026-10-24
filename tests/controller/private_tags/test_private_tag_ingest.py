"""Ingest walk: Retain Safe Private applies KB operands; strip when option is off."""

from pydicom import dcmread
from pydicom.data import get_testdata_file

from anonymizer.controller.anonymizer import AnonymizerController
from anonymizer.controller.dates import apply_day_delta, resolve_date_delta
from anonymizer.controller.private_tags import PrivateTagAction
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import RETAIN_OPTIONS
from anonymizer.utils.dicom import DeidMethodCode
from tests.controller.dicom.support.test_files import ct_small_filename
from tests.controller.dicom.support.test_nodes import LocalSCU
from tests.controller.private_tags.support_private_ds import (
    apply_private_specs,
    find_private_element,
    ingest_fixture_specs,
    sample_kb_entries,
    spec_from_kb,
)


def _private_data_tags(ds) -> set[int]:
    """Tag ints for non-creator private elements."""
    return {
        int(elem.tag)
        for elem in ds
        if elem.tag.is_private and not elem.tag.is_private_creator
    }


def test_ingest_retain_safe_private_applies_kb_dispositions(
    controller: ProjectController,
) -> None:
    """SAFE_PRIVATE on: keep/date/uid/unknown match KB; creators kept; 0x0013 stamped."""
    controller.model.confidentiality_options = RETAIN_OPTIONS
    specs = ingest_fixture_specs()
    keep_spec, remove_spec, uid_spec, date_spec, unknown_spec = specs

    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "SAFE-PRIV-INGEST"
    ds.StudyDate = "20200101"
    ds.SOPInstanceUID = "1.2.840.10008.safepriv.ingest.1"
    apply_private_specs(ds, specs)

    planted = {
        "keep": find_private_element(ds, keep_spec),
        "remove": find_private_element(ds, remove_spec),
        "uid": find_private_element(ds, uid_spec),
        "date": find_private_element(ds, date_spec),
        "unknown": find_private_element(ds, unknown_spec),
    }
    keep_tag = planted["keep"].tag
    remove_tag = planted["remove"].tag
    uid_tag = planted["uid"].tag
    date_tag = planted["date"].tag
    unknown_tag = planted["unknown"].tag
    keep_creator_tag = next(
        e.tag
        for e in ds
        if e.tag.is_private_creator
        and e.tag.group == keep_spec.group
        and str(e.value).strip() == keep_spec.creator
    )
    phi_uid = str(planted["uid"].value)
    phi_date = str(planted["date"].value)

    delta = resolve_date_delta(
        controller.anonymizer.model._tag_keep.get("00080020") or None,
        patient_id="SAFE-PRIV-INGEST",
        days_from_lookup=0,
        base_date=None,
    )
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None

    assert keep_tag in ds
    assert ds[keep_tag].value == "KEEPME"
    assert keep_creator_tag in ds
    assert remove_tag not in ds
    assert unknown_tag not in ds
    assert uid_tag in ds
    assert str(ds[uid_tag].value) != phi_uid
    assert str(ds[uid_tag].value).startswith(controller.model.uid_root)
    assert date_tag in ds
    assert str(ds[date_tag].value) == apply_day_delta(phi_date, delta)

    # App private block stamped and kept.
    assert ds.private_block(0x0013, AnonymizerController.PRIVATE_BLOCK_NAME)
    rsna = ds.private_block(0x0013, AnonymizerController.PRIVATE_BLOCK_NAME)
    assert rsna[0x01].value == controller.model.site_id
    assert rsna[0x03].value == controller.model.project_name


def test_ingest_without_safe_private_strips_vendor_privates(
    controller: ProjectController,
) -> None:
    """SAFE_PRIVATE off: remove_private_tags before walk; only app 0x0013 remains."""
    controller.model.confidentiality_options = frozenset(
        c for c in RETAIN_OPTIONS if c is not DeidMethodCode.SAFE_PRIVATE
    )
    assert not controller.anonymizer.safe_private_enabled

    specs = ingest_fixture_specs()
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "NO-SAFE-PRIV"
    ds.StudyDate = "20200101"
    ds.SOPInstanceUID = "1.2.840.10008.nosafepriv.1"
    apply_private_specs(ds, specs)
    vendor_tags = _private_data_tags(ds)
    assert vendor_tags

    assert controller.anonymizer.anonymize(LocalSCU, ds) is None

    remaining = _private_data_tags(ds)
    for tag in vendor_tags:
        assert tag not in remaining
    # Only RSNA block data elements (site/project) should remain as private data.
    for elem in ds:
        if not elem.tag.is_private or elem.tag.is_private_creator:
            continue
        assert elem.tag.group == 0x0013


def test_ingest_date_operand_non_da_dt_is_deleted(controller: ProjectController) -> None:
    """Walk deletes private elements that resolve to a date operand but are not DA/DT."""
    controller.model.confidentiality_options = RETAIN_OPTIONS
    date_sample = sample_kb_entries(
        PrivateTagAction.DATE_DELTA, vr_in=frozenset({"DA", "DT"}), limit=1
    )[0]
    # Same KB slot, but plant as TM so operation is @incrementdate and apply deletes.
    tm_spec = spec_from_kb(date_sample, value="120000", vr="TM")
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "PRIV-DATE-TM"
    ds.StudyDate = "20200101"
    ds.SOPInstanceUID = "1.2.840.10008.privdate.tm.1"
    apply_private_specs(ds, [tm_spec])
    planted = find_private_element(ds, tm_spec)
    planted_tag = planted.tag

    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert planted_tag not in ds
