"""Ingest stamp matrix and retain-option anonymize smokes for de-id options."""

from pydicom import dcmread
from pydicom.data import get_testdata_file

import pytest

from anonymizer.controller.project import ProjectController
from anonymizer.controller.script.document import load_script_rules, write_script_rules
from anonymizer.model.project import AT_INGEST, BASIC_OPTIONS, NOT_EXECUTED, RETAIN_OPTIONS
from anonymizer.utils.dicom import DeidMethodCode
from tests.controller.dicom.support.test_files import ct_small_filename
from tests.controller.dicom.support.test_nodes import LocalSCU
from tests.controller.private_tags.support_private_ds import (
    apply_private_specs,
    find_private_element,
    ingest_fixture_specs,
)


def _codes_on(ds) -> set[str]:
    seq = getattr(ds, "DeidentificationMethodCodeSequence", None)
    if not seq:
        return set()
    return {str(item.CodeValue) for item in seq}


@pytest.mark.parametrize("code", sorted(AT_INGEST, key=int), ids=lambda c: c.name)
def test_at_ingest_option_stamped_in_method_sequence(
    controller: ProjectController, code: DeidMethodCode
) -> None:
    """Each AT_INGEST code selected with Basic appears in (0012,0064)."""
    selected = BASIC_OPTIONS | {code}
    controller.apply_confidentiality_options(selected)
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = f"STAMP-{int(code)}"
    ds.StudyDate = "20200115"
    ds.PatientSex = "F"
    ds.PatientAge = "045Y"
    ds.Manufacturer = "ACME"
    ds.InstitutionName = "General Hospital"
    ds.SOPInstanceUID = f"1.2.840.10008.stamp.{int(code)}"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    codes = _codes_on(ds)
    assert str(int(DeidMethodCode.BASIC)) in codes
    assert str(int(code)) in codes


@pytest.mark.parametrize(
    "clean_code",
    [
        DeidMethodCode.CLEAN_PIXEL_DATA,
        DeidMethodCode.CLEAN_VISUAL_FEATURES,
        DeidMethodCode.CLEAN_GRAPHICS,
        DeidMethodCode.CLEAN_STRUCTURED_CONTENT,
        DeidMethodCode.CLEAN_DESCRIPTORS,
    ],
)
def test_clean_options_not_stamped_at_ingest(
    controller: ProjectController, clean_code: DeidMethodCode
) -> None:
    """Clean* options are not in AT_INGEST; selecting them does not stamp at import."""
    assert clean_code not in AT_INGEST
    controller.apply_confidentiality_options(BASIC_OPTIONS | {clean_code})
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = f"CLEAN-STAMP-{int(clean_code)}"
    ds.StudyDate = "20200115"
    ds.SOPInstanceUID = f"1.2.840.10008.cleanstamp.{int(clean_code)}"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert _codes_on(ds) == {str(int(DeidMethodCode.BASIC))}


def test_device_identity_keeps_manufacturer(controller: ProjectController) -> None:
    controller.apply_confidentiality_options(
        BASIC_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY}
    )
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "DEVICE-KEEP"
    ds.StudyDate = "20200115"
    ds.Manufacturer = "ACME-SCANNER"
    ds.SOPInstanceUID = "1.2.840.10008.device.keep.1"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.Manufacturer == "ACME-SCANNER"


def test_institution_identity_keeps_institution_name(controller: ProjectController) -> None:
    controller.apply_confidentiality_options(
        BASIC_OPTIONS | {DeidMethodCode.INSTITUTION_IDENTITY}
    )
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "INST-KEEP"
    ds.StudyDate = "20200115"
    ds.InstitutionName = "General Hospital"
    ds.SOPInstanceUID = "1.2.840.10008.inst.keep.1"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.InstitutionName == "General Hospital"


def test_patient_characteristics_keeps_sex_and_rounds_age(
    controller: ProjectController,
) -> None:
    controller.apply_confidentiality_options(
        BASIC_OPTIONS | {DeidMethodCode.PATIENT_CHARACTERISTICS}
    )
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "CHARS-KEEP"
    ds.StudyDate = "20200115"
    ds.PatientSex = "F"
    ds.PatientAge = "043Y"
    ds.SOPInstanceUID = "1.2.840.10008.chars.keep.1"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.PatientSex == "F"
    # @round(this,5): 43 → nearest 5-year band 45.
    assert str(ds.PatientAge) == "045Y"


def test_full_dates_keeps_study_date(controller: ProjectController) -> None:
    controller.apply_confidentiality_options(BASIC_OPTIONS | {DeidMethodCode.FULL_DATES})
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "FULL-DATES"
    ds.StudyDate = "20200115"
    ds.SOPInstanceUID = "1.2.840.10008.fulldates.1"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.StudyDate == "20200115"


def test_retain_uids_keeps_study_instance_uid(controller: ProjectController) -> None:
    controller.apply_confidentiality_options(BASIC_OPTIONS | {DeidMethodCode.RETAIN_UIDS})
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "UID-KEEP"
    ds.StudyDate = "20200115"
    study_uid = "1.2.840.10008.1.2.3.retain.study"
    ds.StudyInstanceUID = study_uid
    ds.SOPInstanceUID = "1.2.840.10008.uid.keep.1"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.StudyInstanceUID == study_uid


def test_safe_private_keeps_kb_keep_and_drops_unknown(
    controller: ProjectController,
) -> None:
    controller.apply_confidentiality_options(
        BASIC_OPTIONS | {DeidMethodCode.SAFE_PRIVATE}
    )
    specs = ingest_fixture_specs()
    keep_spec = specs[0]
    unknown_spec = specs[-1]
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "SAFE-PRIV-SMOKE"
    ds.StudyDate = "20200115"
    ds.SOPInstanceUID = "1.2.840.10008.safepriv.smoke.1"
    apply_private_specs(ds, specs)
    keep_tag = find_private_element(ds, keep_spec).tag
    unknown_tag = find_private_element(ds, unknown_spec).tag
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert keep_tag in ds
    assert ds[keep_tag].value == "KEEPME"
    assert unknown_tag not in ds


def test_modified_dates_shifts_study_and_series_date(
    controller: ProjectController,
) -> None:
    """
    Modified Dates via apply_confidentiality_options shifts DA tags.

    Uses a fixed @incrementdate fingerprint (not bare @hashdate) so the
    expected calendar shift is deterministic.
    """
    controller.apply_confidentiality_options(
        BASIC_OPTIONS | {DeidMethodCode.MODIFIED_DATES}
    )
    script_path = controller.model.anonymizer_script_path
    document = load_script_rules(script_path)
    for tag in ("00080020", "00080021"):
        rule = document.get_rule(tag)
        if rule is not None:
            rule.operation = "@incrementdate(this,-7)"
    write_script_rules(script_path, document)
    controller.anonymizer.reload_script(script_path)

    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "MOD-DATES-SMOKE"
    ds.StudyDate = "20200115"
    ds.SeriesDate = "20200116"
    ds.SOPInstanceUID = "1.2.840.10008.moddates.smoke.1"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.StudyDate == "20200108"
    assert ds.SeriesDate == "20200109"
    assert str(int(DeidMethodCode.MODIFIED_DATES)) in _codes_on(ds)
    assert getattr(ds, "LongitudinalTemporalInformationModified", None) == "MODIFIED"


def test_retain_plus_device_combination_smoke(controller: ProjectController) -> None:
    """Retain preset + Device Identity: demographics/private keep + Manufacturer @safe."""
    selected = RETAIN_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY}
    controller.apply_confidentiality_options(selected)
    specs = ingest_fixture_specs()
    keep_spec = specs[0]
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "RETAIN-DEVICE"
    ds.PatientName = "DOE^JANE"
    ds.StudyDate = "20200115"
    ds.PatientSex = "F"
    ds.Manufacturer = "ACME-SCANNER"
    ds.SOPInstanceUID = "1.2.840.10008.retain.device.1"
    apply_private_specs(ds, [keep_spec])
    keep_tag = find_private_element(ds, keep_spec).tag
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.Manufacturer == "ACME-SCANNER"
    assert ds.PatientSex == "F"
    assert keep_tag in ds
    assert ds[keep_tag].value == "KEEPME"
    # Basic still remaps Patient ID / strips name identity.
    assert str(ds.PatientID) != "RETAIN-DEVICE"
    assert "DOE" not in str(ds.PatientName or "")
    codes = _codes_on(ds)
    assert str(int(DeidMethodCode.BASIC)) in codes
    assert str(int(DeidMethodCode.DEVICE_IDENTITY)) in codes
    assert str(int(DeidMethodCode.SAFE_PRIVATE)) in codes


def test_clean_graphics_is_not_executed() -> None:
    """Clean Graphics stays on NOT_EXECUTED; never stamped at ingest."""
    assert DeidMethodCode.CLEAN_GRAPHICS in NOT_EXECUTED

