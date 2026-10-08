"""Shared OCR remove-target helpers."""

from __future__ import annotations

from anonymizer.controller.runner import (
    OcrRemoveMode,
    apply_phi_ner_filter_for_ocr_remove_mode,
    normalize_ocr_remove_mode,
    ocr_remove_mode_from_legacy_whitelist,
    whitelist_arg_for_ocr_remove_mode,
)


def test_normalize_ocr_remove_mode_aliases() -> None:
    assert normalize_ocr_remove_mode("PHI only") is OcrRemoveMode.PHI_ONLY
    assert normalize_ocr_remove_mode("all_text") is OcrRemoveMode.ALL_TEXT
    assert normalize_ocr_remove_mode("Non-whitelisted text") is OcrRemoveMode.NON_WHITELISTED
    assert normalize_ocr_remove_mode(None) is OcrRemoveMode.NON_WHITELISTED


def test_legacy_whitelist_maps_to_remove_mode() -> None:
    assert ocr_remove_mode_from_legacy_whitelist(use_modality_whitelist=True) is OcrRemoveMode.NON_WHITELISTED
    assert ocr_remove_mode_from_legacy_whitelist(use_modality_whitelist=False) is OcrRemoveMode.ALL_TEXT


def test_whitelist_and_ner_kwargs_for_modes() -> None:
    assert whitelist_arg_for_ocr_remove_mode(OcrRemoveMode.NON_WHITELISTED) is None
    assert whitelist_arg_for_ocr_remove_mode(OcrRemoveMode.ALL_TEXT) == []
    assert whitelist_arg_for_ocr_remove_mode(OcrRemoveMode.PHI_ONLY) == []
    assert apply_phi_ner_filter_for_ocr_remove_mode(OcrRemoveMode.PHI_ONLY) is True
    assert apply_phi_ner_filter_for_ocr_remove_mode(OcrRemoveMode.NON_WHITELISTED) is False
