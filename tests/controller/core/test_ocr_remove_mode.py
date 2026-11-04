"""Shared OCR remove-target helpers — plan decide helpers at caller."""

from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import (
    PhiMatchMode,
    effective_phi_label,
    is_whitelisted,
    make_annotate_whitelist,
    phi_accepted,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import (
    OcrRemoveMode,
    ocr_remove_mode_from_legacy_whitelist,
    texts_for_remove_mode,
    whitelist_arg_for_ocr_remove_mode,
)
from anonymizer.controller.series.series_overlay import (
    NerEvidence,
    OCRText,
    OcrEvidence,
    WhitelistEvidence,
)
from anonymizer.view.ocr_ui import normalize_ocr_remove_mode


def _annotated(
    text: str,
    *,
    wl_score: float | None = None,
    wl_term: str | None = None,
    ner_score: float | None = None,
    ner_label: str | None = None,
) -> OCRText:
    term = wl_term if wl_term is not None else ("X" if wl_score else None)
    label = ner_label if ner_label is not None else ("NAME" if ner_score else None)
    return OCRText(
        text=text,
        top_left=(0, 0),
        bottom_right=(40, 20),
        ocr=OcrEvidence(prob=0.9),
        whitelist=WhitelistEvidence(term=term, score=wl_score),
        ner=NerEvidence(label=label, score=ner_score),
    )


def test_normalize_ocr_remove_mode_aliases() -> None:
    assert normalize_ocr_remove_mode("PHI only") is OcrRemoveMode.PHI_ONLY
    assert normalize_ocr_remove_mode("all_text") is OcrRemoveMode.ALL_TEXT
    assert normalize_ocr_remove_mode("Non-whitelisted text") is OcrRemoveMode.NON_WHITELISTED
    assert normalize_ocr_remove_mode(None) is OcrRemoveMode.NON_WHITELISTED


def test_legacy_whitelist_maps_to_remove_mode() -> None:
    assert ocr_remove_mode_from_legacy_whitelist(use_modality_whitelist=True) is OcrRemoveMode.NON_WHITELISTED
    assert ocr_remove_mode_from_legacy_whitelist(use_modality_whitelist=False) is OcrRemoveMode.ALL_TEXT


def test_whitelist_arg_for_modes() -> None:
    assert whitelist_arg_for_ocr_remove_mode(OcrRemoveMode.NON_WHITELISTED) is None
    assert whitelist_arg_for_ocr_remove_mode(OcrRemoveMode.ALL_TEXT) == []
    assert whitelist_arg_for_ocr_remove_mode(OcrRemoveMode.PHI_ONLY) is None


def test_texts_for_remove_mode_by_scope() -> None:
    boxes = [
        _annotated("PORTABLE", wl_score=0.95),
        _annotated("DAVIDSON", ner_score=0.9),
        _annotated("AXIAL", wl_score=0.2, ner_score=0.2),
    ]
    mode = PhiMatchMode.STANDARD
    non_wl = texts_for_remove_mode(boxes, OcrRemoveMode.NON_WHITELISTED, mode)
    assert [t.text for t in non_wl] == ["DAVIDSON", "AXIAL"]
    phi_only = texts_for_remove_mode(boxes, OcrRemoveMode.PHI_ONLY, mode)
    assert [t.text for t in phi_only] == ["DAVIDSON"]
    all_text = texts_for_remove_mode(boxes, OcrRemoveMode.ALL_TEXT, mode)
    assert len(all_text) == 3


def test_phi_only_uses_ner_not_whitelist_alone() -> None:
    whitelisted_no_ner = _annotated("LEFT", wl_score=0.99, ner_score=None)
    assert not phi_accepted(whitelisted_no_ner, PhiMatchMode.STANDARD)
    annotated = make_annotate_whitelist(["LEFT"])([_annotated("LEFT", wl_score=None)])
    assert not texts_for_remove_mode(annotated, OcrRemoveMode.PHI_ONLY, PhiMatchMode.STANDARD)


def test_whitelist_overrides_ner_name_for_phi_only_when_margin_met() -> None:
    """Whitelist chrome with NER below wl-0.1 is not PHI / not removed as PHI."""
    mode = PhiMatchMode.STANDARD
    axilla = _annotated(
        "AXILLA",
        wl_score=1.0,
        wl_term="AXILLA",
        ner_score=0.85,
        ner_label="NAME",
    )
    assert is_whitelisted(axilla, mode)
    assert axilla.ner.label == "NAME"
    assert not phi_accepted(axilla, mode)
    assert effective_phi_label(axilla, mode) is None
    assert texts_for_remove_mode([axilla], OcrRemoveMode.PHI_ONLY, mode) == []
    assert texts_for_remove_mode([axilla], OcrRemoveMode.NON_WHITELISTED, mode) == []
    assert texts_for_remove_mode([axilla], OcrRemoveMode.ALL_TEXT, mode) == [axilla]


def test_ner_name_beats_fuzzy_whitelist_for_phi_only() -> None:
    """Fuzzy whitelist within 0.1 of NER does not block PHI-only removal."""
    mode = PhiMatchMode.LENIENT
    bailey = _annotated(
        "Bailey",
        wl_score=0.70,
        wl_term="BILAT",
        ner_score=0.80,
        ner_label="NAME",
    )
    assert is_whitelisted(bailey, mode)
    assert phi_accepted(bailey, mode)
    assert texts_for_remove_mode([bailey], OcrRemoveMode.PHI_ONLY, mode) == [bailey]
    assert texts_for_remove_mode([bailey], OcrRemoveMode.NON_WHITELISTED, mode) == [
        bailey
    ]
