"""Unit tests for de-identification option explanation catalog and status lines."""

from pathlib import Path

import pytest

from anonymizer.controller.private_tags.private_tags import (
    TCIA_PRIVATE_TAG_KB_ASSET_RELPATH,
    TCIA_PRIVATE_TAG_KB_PAGE_URL,
)
from anonymizer.controller.script.compile import compile_script
from anonymizer.controller.script.document import load_script_rules
from anonymizer.controller.script import option_explanations as option_explanations_mod
from anonymizer.controller.script.option_explanations import (
    deid_option_explanation,
    option_abbreviation,
    options_status_line,
    script_is_custom,
    script_status_line,
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


def test_every_deid_method_code_has_explanation() -> None:
    for code in DeidMethodCode:
        expl = deid_option_explanation(code)
        assert expl.title
        assert expl.summary
        assert expl.when_it_runs
        # RHS copy: direct actions only — no vague lists, hedges, or asides.
        assert "(" not in expl.summary and ")" not in expl.summary
        folded = expl.summary.casefold()
        assert "many workflow" not in folded
        assert "such as" not in folded
        assert "unless" not in folded


def test_basic_summary_states_primary_import_actions() -> None:
    summary = deid_option_explanation(DeidMethodCode.BASIC).summary.casefold()
    for needle in (
        "private tags",
        "curve and overlay",
        "patient name",
        "patient id",
        "accession",
        "uids",
        "calendar dates",
        "birth date",
        "physician",
        "institution",
        "manufacturer",
        "patient age",
    ):
        assert needle in summary, needle


def test_options_status_line_lists_abbreviations_not_custom() -> None:
    assert options_status_line(BASIC_OPTIONS) == "Basic"
    assert "Custom" not in options_status_line(RETAIN_OPTIONS)
    assert "Patient" in options_status_line(RETAIN_OPTIONS)
    assert "Modified Dates" in options_status_line(RETAIN_OPTIONS)
    device_only = BASIC_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY}
    assert options_status_line(device_only) == "Device"
    assert option_abbreviation(DeidMethodCode.DEVICE_IDENTITY) == "Device"


def test_script_status_custom_only_when_operands_diverge() -> None:
    selected = BASIC_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY}
    matched = compile_script(selected, _DEFAULT)
    assert not script_is_custom(matched, selected, base_script_path=_DEFAULT)
    assert script_status_line(matched, selected, base_script_path=_DEFAULT) == "Device"

    edited = load_script_rules(_DEFAULT)
    rule = edited.get_rule("00080070")
    assert rule is not None
    rule.operation = "@keep"
    # Basic alone with Manufacturer kept → Custom
    assert script_is_custom(edited, BASIC_OPTIONS, base_script_path=_DEFAULT)
    assert script_status_line(edited, BASIC_OPTIONS, base_script_path=_DEFAULT) == "Custom"


def test_option_abbreviations_unique_for_every_code() -> None:
    abbrevs = [option_abbreviation(code) for code in DeidMethodCode]
    assert all(abbrevs)
    assert len(abbrevs) == len(set(abbrevs))


@pytest.mark.parametrize(
    "code,feature_title",
    list(option_explanations_mod._AI_BATCH_FEATURE.items()),
    ids=lambda v: getattr(v, "name", str(v)),
)
def test_ai_batch_feature_options_mention_batch_and_title(
    code: DeidMethodCode, feature_title: str
) -> None:
    expl = deid_option_explanation(code)
    assert "AI Batch" in expl.when_it_runs
    assert feature_title in expl.when_it_runs


def test_safe_private_links_tcia_kb_release_and_assets() -> None:
    expl = deid_option_explanation(DeidMethodCode.SAFE_PRIVATE)
    assert "TCIA" in expl.summary
    assert "Cancer Imaging Archive" in expl.source_line
    assert TCIA_PRIVATE_TAG_KB_ASSET_RELPATH in expl.source_line
    assert "assets/tcia_kb/" in expl.source_line
    assert expl.link_label
    assert expl.link_url == TCIA_PRIVATE_TAG_KB_PAGE_URL
    assert "wiki.cancerimagingarchive.net" in expl.link_url
    assert "wiki.cancerimagingarchive.net" in expl.link_tooltip
    basic = deid_option_explanation(DeidMethodCode.BASIC)
    assert basic.source_line == ""
    assert basic.link_url == ""
