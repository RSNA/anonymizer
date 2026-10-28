"""SR/PDF modality selection auto-enables Clean Structured Content."""

from anonymizer.controller.script.options import (
    REPORT_MODALITIES_FOR_CLEAN_STRUCTURED,
    clean_structured_auto_enable_message,
    enable_clean_structured_for_report_modalities,
    newly_enabled_report_modalities,
)
from anonymizer.utils.dicom import DeidMethodCode


def test_report_modalities_are_sr_and_pdf_not_sc() -> None:
    assert REPORT_MODALITIES_FOR_CLEAN_STRUCTURED == frozenset({"SR", "PDF"})


def test_newly_enabled_report_modalities() -> None:
    assert newly_enabled_report_modalities(["CT", "MR"], ["CT", "MR", "SR"]) == frozenset({"SR"})
    assert newly_enabled_report_modalities(["CT"], ["CT", "SC"]) == frozenset()
    assert newly_enabled_report_modalities(["SR"], ["SR", "PDF"]) == frozenset({"PDF"})
    assert newly_enabled_report_modalities(["SR"], ["SR"]) == frozenset()


def test_enable_clean_structured_when_sr_newly_selected() -> None:
    previous = ["CT", "MR"]
    selected = ["CT", "MR", "SR"]
    updated = enable_clean_structured_for_report_modalities(
        frozenset({DeidMethodCode.BASIC}),
        previous_modalities=previous,
        selected_modalities=selected,
    )
    assert updated is not None
    assert DeidMethodCode.BASIC in updated
    assert DeidMethodCode.CLEAN_STRUCTURED_CONTENT in updated


def test_enable_clean_structured_noop_when_already_on() -> None:
    options = frozenset({DeidMethodCode.BASIC, DeidMethodCode.CLEAN_STRUCTURED_CONTENT})
    assert (
        enable_clean_structured_for_report_modalities(
            options,
            previous_modalities=["CT"],
            selected_modalities=["CT", "PDF"],
        )
        is None
    )


def test_enable_clean_structured_noop_for_secondary_capture() -> None:
    assert (
        enable_clean_structured_for_report_modalities(
            frozenset({DeidMethodCode.BASIC}),
            previous_modalities=["CT"],
            selected_modalities=["CT", "SC"],
        )
        is None
    )


def test_clean_structured_auto_enable_message() -> None:
    message = clean_structured_auto_enable_message()
    assert "Clean Structured Content" in message
    assert "SR" in message and "PDF" in message
