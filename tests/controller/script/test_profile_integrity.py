"""Integrity of Basic vs retain-option compiles over the E.1-1 catalog ∩ script."""

from pathlib import Path

import pytest

from anonymizer.controller.dates import is_date_delta_operation
from anonymizer.controller.script.compile import (
    DEVICE_IDENTITY_TAGS,
    INSTITUTION_IDENTITY_TAGS,
    PATIENT_CHARACTERISTICS_TAGS,
    basic_strip_ok,
    compile_script,
    normalize_script_operation,
    script_operations_by_tag,
)
from anonymizer.controller.script.date_rules import mismatched_date_rules
from anonymizer.controller.script.document import load_script_rules
from anonymizer.controller.script.operands import is_remove_operation
from anonymizer.controller.script.options import infer_options_from_script
from anonymizer.controller.script.retain_option_tags import (
    load_e1_1_retain_catalog,
    patient_age_tag,
    tags_in_script,
)
from anonymizer.model.project import BASIC_OPTIONS, RETAIN_OPTIONS
from anonymizer.utils.dicom import DeidMethodCode

_DEFAULT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "anonymizer"
    / "assets"
    / "scripts"
    / "default-anonymizer.script"
)


def _ops(options: frozenset[DeidMethodCode]) -> dict[str, str]:
    return script_operations_by_tag(compile_script(options, _DEFAULT))


def _delta(a: dict[str, str], b: dict[str, str]) -> dict[str, tuple[str, str]]:
    return {
        tag: (a[tag], b[tag])
        for tag in sorted(set(a) & set(b))
        if normalize_script_operation(a[tag]) != normalize_script_operation(b[tag])
    }


def _script_tags() -> set[str]:
    return {r.tag.upper() for r in load_script_rules(_DEFAULT).rules}


def _device_in_script() -> list[str]:
    return list(tags_in_script(DEVICE_IDENTITY_TAGS, _script_tags()))


def _institution_in_script() -> list[str]:
    return list(tags_in_script(INSTITUTION_IDENTITY_TAGS, _script_tags()))


def _patient_in_script() -> list[str]:
    return list(tags_in_script(PATIENT_CHARACTERISTICS_TAGS, _script_tags()))


def test_basic_matches_packaged_default() -> None:
    basic = _ops(BASIC_OPTIONS)
    packaged = script_operations_by_tag(load_script_rules(_DEFAULT))
    assert basic == packaged


@pytest.mark.parametrize(
    "family,tag_list",
    [
        ("device", DEVICE_IDENTITY_TAGS),
        ("institution", INSTITUTION_IDENTITY_TAGS),
        ("patient_characteristics", PATIENT_CHARACTERISTICS_TAGS),
    ],
)
def test_catalog_family_tags_cover_script_intersection(family: str, tag_list: tuple[str, ...]) -> None:
    """Compile lists include every catalog∩script tag for the family."""
    catalog = load_e1_1_retain_catalog()[family]
    expected = tags_in_script([e.tag for e in catalog], _script_tags())
    assert set(expected) <= set(tag_list)


@pytest.mark.parametrize("tag", _device_in_script())
def test_basic_strips_device_identity_tags(tag: str) -> None:
    op = _ops(BASIC_OPTIONS)[tag]
    assert basic_strip_ok(op), f"{tag} under Basic should strip, got {op!r}"


@pytest.mark.parametrize("tag", _institution_in_script())
def test_basic_strips_institution_identity_tags(tag: str) -> None:
    op = _ops(BASIC_OPTIONS)[tag]
    assert basic_strip_ok(op), f"{tag} under Basic should strip, got {op!r}"


@pytest.mark.parametrize("tag", [t for t in _patient_in_script() if t != patient_age_tag()])
def test_basic_strips_patient_characteristics_tags(tag: str) -> None:
    op = _ops(BASIC_OPTIONS)[tag]
    assert is_remove_operation(op) or op.startswith("@empty"), f"{tag} under Basic: {op!r}"


def test_basic_patient_age_stays_rounded() -> None:
    assert _ops(BASIC_OPTIONS)[patient_age_tag()].startswith("@round")


def test_device_identity_overlay_keeps_and_flips_manufacturer() -> None:
    basic = _ops(BASIC_OPTIONS)
    with_opt = _ops(BASIC_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY})
    delta = _delta(basic, with_opt)
    assert "00080070" in delta
    assert delta["00080070"][1] == "@safe()"
    for tag in _device_in_script():
        assert with_opt[tag] == "@safe()"
    assert delta, "DEVICE_IDENTITY must change at least one operand vs Basic"


def test_institution_identity_overlay_keeps_all() -> None:
    basic = _ops(BASIC_OPTIONS)
    with_opt = _ops(BASIC_OPTIONS | {DeidMethodCode.INSTITUTION_IDENTITY})
    delta = _delta(basic, with_opt)
    assert delta
    for tag in _institution_in_script():
        assert with_opt[tag] == "@keep"


def test_patient_characteristics_overlay_keeps_non_age() -> None:
    basic = _ops(BASIC_OPTIONS)
    with_opt = _ops(BASIC_OPTIONS | {DeidMethodCode.PATIENT_CHARACTERISTICS})
    delta = _delta(basic, with_opt)
    assert delta
    assert "00100040" in delta
    assert with_opt["00100040"] == "@keep"
    assert with_opt[patient_age_tag()].startswith("@round")


def test_full_dates_clears_date_deltas() -> None:
    with_opt = _ops(BASIC_OPTIONS | {DeidMethodCode.FULL_DATES})
    assert not any(is_date_delta_operation(op) for op in with_opt.values())
    assert with_opt["00080020"] == "@keep"


def test_modified_dates_one_strategy() -> None:
    doc = compile_script(BASIC_OPTIONS | {DeidMethodCode.MODIFIED_DATES}, _DEFAULT)
    assert mismatched_date_rules(doc) == []


def test_retain_preset_public_delta_includes_patient_chars() -> None:
    delta = _delta(_ops(BASIC_OPTIONS), _ops(RETAIN_OPTIONS))
    assert "00100040" in delta
    assert delta["00100040"][1] == "@keep"


@pytest.mark.parametrize(
    "option",
    [
        DeidMethodCode.DEVICE_IDENTITY,
        DeidMethodCode.INSTITUTION_IDENTITY,
        DeidMethodCode.PATIENT_CHARACTERISTICS,
        DeidMethodCode.FULL_DATES,
        DeidMethodCode.MODIFIED_DATES,
        DeidMethodCode.RETAIN_UIDS,
    ],
)
def test_infer_round_trip_option(option: DeidMethodCode) -> None:
    compiled = compile_script(BASIC_OPTIONS | {option}, _DEFAULT)
    if option is DeidMethodCode.MODIFIED_DATES:
        # Packaged StudyDate is already @hashdate; Modified Dates leaves the same
        # operand. Use a non-default delta so infer can see the Modified Dates strategy.
        study = compiled.get_rule("00080020")
        assert study is not None
        study.operation = "@incrementdate(this,7)"
    inferred = infer_options_from_script(compiled)
    assert option in inferred
    assert DeidMethodCode.BASIC in inferred


def test_basic_infer_excludes_safe_private_and_clean_options() -> None:
    inferred = infer_options_from_script(compile_script(BASIC_OPTIONS, _DEFAULT))
    assert inferred == BASIC_OPTIONS
    for option in (
        DeidMethodCode.SAFE_PRIVATE,
        DeidMethodCode.CLEAN_PIXEL_DATA,
        DeidMethodCode.CLEAN_VISUAL_FEATURES,
        DeidMethodCode.CLEAN_GRAPHICS,
        DeidMethodCode.CLEAN_STRUCTURED_CONTENT,
        DeidMethodCode.CLEAN_DESCRIPTORS,
    ):
        assert option not in inferred


@pytest.mark.parametrize(
    "option",
    [
        DeidMethodCode.CLEAN_PIXEL_DATA,
        DeidMethodCode.CLEAN_VISUAL_FEATURES,
        DeidMethodCode.CLEAN_GRAPHICS,
        DeidMethodCode.CLEAN_STRUCTURED_CONTENT,
        DeidMethodCode.CLEAN_DESCRIPTORS,
        DeidMethodCode.SAFE_PRIVATE,
    ],
)
def test_non_overlay_options_do_not_change_compile(option: DeidMethodCode) -> None:
    basic = _ops(BASIC_OPTIONS)
    assert _ops(BASIC_OPTIONS | {option}) == basic
