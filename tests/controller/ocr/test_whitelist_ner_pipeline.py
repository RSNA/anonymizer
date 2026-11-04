"""Controller tests: whitelist × NER permutations (Series View annotate vs batch filter)."""

from unittest.mock import MagicMock, patch

import numpy as np

from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import build_series_view_ocr_pixels
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import (
    PhiMatchMode,
    annotate_ner,
    detect_text,
    filter_ocr_noise,
    make_annotate_whitelist,
    pipe,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrRemoveMode, texts_for_remove_mode
from anonymizer.controller.series.series_overlay import OCRText, OcrEvidence

_DAVIDSON_TEXTS = (
    "DAVIDSON DOUGLAS [M]",
    "01.09.2012",
    "DOB: 06.16.1976",
    "Semi-Upright",
    "Portable",
    "L",
)


def _ocr(text: str, *, prob: float = 0.95) -> OCRText:
    return OCRText(text=text, top_left=(0, 0), bottom_right=(40, 20), ocr=OcrEvidence(prob=prob))


def _davidson_detections() -> list[OCRText]:
    return [_ocr(t) for t in _DAVIDSON_TEXTS]


def _fake_detect_phi(text: str, *, locale: str = "en_US", include_time: bool = False) -> list[Entity]:
    del include_time  # pixel annotate_ner always passes True; metadata fakes ignore it
    ents: list[Entity] = []
    for needle, label, score in (
        ("DAVIDSON", "FIRST_NAME", 0.99),
        ("DOUGLAS", "FIRST_NAME", 0.98),
        ("01.09.2012", "DATE", 0.95),
        ("06.16.1976", "DATE", 0.95),
    ):
        idx = text.find(needle)
        if idx >= 0:
            ents.append(Entity(label, idx, idx + len(needle), score=score))
    if "@" in text:
        idx = text.find("@")
        ents.append(Entity("EMAIL", max(0, idx - 2), idx + 3, score=0.9))
    return sorted(ents, key=lambda e: e.start)


def _annotate_pipeline(terms: list[str] | None, detections: list[OCRText]) -> list[OCRText]:
    wl = list(terms) if terms is not None else []
    return pipe(make_annotate_whitelist(wl), annotate_ner)(detections)


def _drawn_non_whitelisted(detections: list[OCRText], terms: list[str]) -> list[OCRText]:
    annotated = make_annotate_whitelist(terms)(detections)
    return texts_for_remove_mode(annotated, OcrRemoveMode.NON_WHITELISTED, PhiMatchMode.STANDARD)


# --- Whitelist annotate + overlay filter ------------------------------------------------


def test_empty_whitelist_keeps_all_davidson_overlay_text() -> None:
    dets = _davidson_detections()
    drawn = _drawn_non_whitelisted(dets, [])
    assert [t.text for t in drawn] == list(_DAVIDSON_TEXTS)


def test_none_whitelist_terms_treated_as_empty_for_display() -> None:
    dets = _davidson_detections()
    drawn = _drawn_non_whitelisted(dets, [])
    assert [t.text for t in drawn] == list(_DAVIDSON_TEXTS)


def test_portable_whitelist_hides_portable_keeps_semi_upright() -> None:
    dets = _davidson_detections()
    drawn = _drawn_non_whitelisted(dets, ["PORTABLE"])
    texts = [t.text for t in drawn]
    assert "Portable" not in texts
    assert "Semi-Upright" in texts
    assert "DAVIDSON DOUGLAS [M]" in texts


def test_whitelist_preserves_ner_label() -> None:
    labeled = _ocr("Portable")
    name = _ocr("DAVIDSON")
    name = annotate_ner(
        [name],
        detect_fn=lambda body: [Entity("FIRST_NAME", 0, len(body), score=0.99)],
    )[0]
    kept = _drawn_non_whitelisted([labeled, name], ["PORTABLE"])
    assert [t.text for t in kept] == ["DAVIDSON"]
    assert kept[0].ner.label == "NAME"


# --- NER annotate (Series View) -------------------------------------------------------


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_entities",
    side_effect=_fake_detect_phi,
)
def test_annotate_labels_phi_without_dropping_overlay(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    dets = _davidson_detections()
    out = annotate_ner(dets)
    by_text = {t.text: t.ner.label for t in out}
    assert len(out) == len(dets)
    assert by_text["DAVIDSON DOUGLAS [M]"] == "NAME"
    assert by_text["01.09.2012"] == "DATE"
    assert by_text["DOB: 06.16.1976"] == "DATE"
    assert by_text["Portable"] is None
    assert by_text["Semi-Upright"] is None


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
def test_annotate_one_contextual_call_and_box_entities(
    _mock_ready: MagicMock, _mock_locale: MagicMock, caplog
) -> None:
    seen: list[str] = []

    def detect(body: str, *, locale: str = "en_US", include_time: bool = False) -> list[Entity]:
        seen.append(body)
        return _fake_detect_phi(body, locale=locale, include_time=include_time)

    name = _ocr("DAVIDSON")
    dob = _ocr("DOB: 06.16.1976")
    portable = _ocr("Portable")
    with caplog.at_level("INFO"):
        out = annotate_ner([name, dob, portable], detect_fn=detect)
    assert seen == ["DAVIDSON, DOB: 06.16.1976, Portable"]
    by_text = {t.text: t for t in out}
    assert by_text["DAVIDSON"].ner.label == "NAME"
    assert by_text["DAVIDSON"].ner.entities == (("NAME", "DAVIDSON"),)
    assert by_text["DOB: 06.16.1976"].ner.label == "DATE"
    assert by_text["DOB: 06.16.1976"].ner.entities == (("DATE", "06.16.1976"),)
    assert by_text["Portable"].ner.label is None
    assert by_text["Portable"].ner.entities == ()


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
def test_annotate_entity_spanning_two_boxes_labels_both(
    _mock_ready: MagicMock, _mock_locale: MagicMock
) -> None:
    def detect(body: str, *, locale: str = "en_US", include_time: bool = False) -> list[Entity]:
        del locale, include_time
        return [Entity("FIRST_NAME", 0, len(body), score=0.9)]

    left = _ocr("Olivia")
    right = _ocr("Diaz")
    out = annotate_ner([left, right], detect_fn=detect)
    assert [t.ner.label for t in out] == ["NAME", "NAME"]
    assert out[0].ner.entities == (("NAME", "Olivia"),)
    assert out[1].ner.entities == (("NAME", "Diaz"),)


def _name_split_detect_phi(
    text: str, *, locale: str = "en_US", include_time: bool = False
) -> list[Entity]:
    del locale, include_time
    idx = text.find("Olivia")
    if idx < 0:
        return []
    return [Entity("FIRST_NAME", idx, idx + 6, score=0.99)]


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_entities",
    side_effect=_name_split_detect_phi,
)
def test_annotate_does_not_propagate_name_to_adjacent_unlabeled_box(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    olivia = _ocr("Olivia")
    diaz = _ocr("Diaz")
    left = _ocr("LEFT")
    out = annotate_ner([olivia, diaz, left])
    by_text = {t.text: t.ner.label for t in out}
    assert by_text["Olivia"] == "NAME"
    assert by_text["Diaz"] is None
    assert by_text["LEFT"] is None


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_entities",
    side_effect=_name_split_detect_phi,
)
def test_annotate_does_not_label_adjacent_overlay_when_span_is_first_name_only(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    olivia = _ocr("Olivia")
    left = _ocr("LEFT")
    out = annotate_ner([olivia, left])
    by_text = {t.text: t.ner.label for t in out}
    assert by_text["Olivia"] == "NAME"
    assert by_text["LEFT"] is None


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_entities",
    side_effect=_name_split_detect_phi,
)
def test_phi_only_remove_keeps_only_labeled_boxes(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    olivia = _ocr("Olivia")
    diaz = _ocr("Diaz")
    portable = _ocr("Portable")
    annotated = annotate_ner([olivia, diaz, portable])
    kept = texts_for_remove_mode(annotated, OcrRemoveMode.PHI_ONLY, PhiMatchMode.STANDARD)
    assert {t.text: t.ner.label for t in kept} == {"Olivia": "NAME"}


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=False)
def test_annotate_when_ner_missing_keeps_all_unlabeled(
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    dets = _davidson_detections()
    out = annotate_ner(dets)
    assert len(out) == len(dets)
    assert all(t.ner.label is None for t in out)


# --- PHI-only remove (batch) ----------------------------------------------------------


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_entities",
    side_effect=_fake_detect_phi,
)
def test_phi_only_remove_drops_portable_keeps_name_date(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    annotated = _annotate_pipeline([], _davidson_detections())
    kept = texts_for_remove_mode(annotated, OcrRemoveMode.PHI_ONLY, PhiMatchMode.STANDARD)
    texts = [t.text for t in kept]
    assert "Portable" not in texts
    assert "Semi-Upright" not in texts
    assert "DAVIDSON DOUGLAS [M]" in texts
    assert "01.09.2012" in texts
    assert all(t.ner.label in {"NAME", "DATE"} for t in kept)


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_entities",
    side_effect=_fake_detect_phi,
)
def test_whitelist_then_phi_only_hides_portable_before_classify(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    annotated = _annotate_pipeline(["PORTABLE"], _davidson_detections())
    drawn = texts_for_remove_mode(annotated, OcrRemoveMode.NON_WHITELISTED, PhiMatchMode.STANDARD)
    assert not any("portable" in t.text.lower() for t in drawn)
    kept = texts_for_remove_mode(annotated, OcrRemoveMode.PHI_ONLY, PhiMatchMode.STANDARD)
    texts = [t.text for t in kept]
    assert "Portable" not in texts
    assert "DAVIDSON DOUGLAS [M]" in texts


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=False)
def test_phi_only_remove_empty_when_ner_missing(
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    annotated = annotate_ner(_davidson_detections())
    assert texts_for_remove_mode(annotated, OcrRemoveMode.PHI_ONLY, PhiMatchMode.STANDARD) == []


# --- detect_text + pipe wiring (mocked EasyOCR) -----------------------------------------


def _easyocr_davidson_results():
    out = []
    for i, text in enumerate(_DAVIDSON_TEXTS):
        y = i * 30
        box = [[0, y], [100, y], [100, y + 20], [0, y + 20]]
        out.append((box, text, 0.95))
    return out


def _series_view_process(reader: MagicMock, *, whitelist: list[str]) -> list[OCRText]:
    pixels = np.zeros((200, 200), dtype=np.uint8)
    detected = detect_text(pixels, reader, modality="CR")
    return pipe(make_annotate_whitelist(whitelist), annotate_ner)(detected)


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_entities",
    side_effect=_fake_detect_phi,
)
def test_series_view_detect_pipeline_keeps_portable_and_labels_phi(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    reader = MagicMock()
    reader.readtext.return_value = _easyocr_davidson_results()
    results = _series_view_process(reader, whitelist=[])
    texts = [t.text for t in results]
    assert "Portable" in texts
    assert "Semi-Upright" in texts
    by_text = {t.text: t.ner.label for t in results}
    assert by_text.get("DAVIDSON DOUGLAS [M]") == "NAME"
    assert by_text.get("Portable") is None


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_entities",
    side_effect=_fake_detect_phi,
)
def test_series_view_stores_all_whitelist_filters_on_display(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    reader = MagicMock()
    reader.readtext.return_value = _easyocr_davidson_results()
    stored = _series_view_process(reader, whitelist=[])
    drawn = texts_for_remove_mode(
        make_annotate_whitelist(["PORTABLE"])(stored),
        OcrRemoveMode.NON_WHITELISTED,
        PhiMatchMode.STANDARD,
    )
    texts = [t.text for t in drawn]
    assert "Portable" not in texts
    assert "Semi-Upright" in texts
    assert any(t.ner.label == "NAME" for t in stored)


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_entities",
    side_effect=_fake_detect_phi,
)
def test_batch_pipeline_noise_then_phi_only(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    reader = MagicMock()
    reader.readtext.return_value = _easyocr_davidson_results()
    pixels = np.zeros((200, 200), dtype=np.uint8)
    detected = detect_text(pixels, reader, modality="CR")
    processed = pipe(
        lambda texts: filter_ocr_noise(texts, modality="CR"),
        make_annotate_whitelist([]),
        annotate_ner,
    )(detected)
    results = texts_for_remove_mode(processed, OcrRemoveMode.PHI_ONLY, PhiMatchMode.STANDARD)
    texts = [t.text for t in results]
    assert "Portable" not in texts
    assert "Semi-Upright" not in texts
    assert any("DAVIDSON" in t for t in texts)
    assert all(t.ner.label for t in results)


def test_series_view_store_all_then_display_whitelist() -> None:
    from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import load_default_whitelist

    stored = _davidson_detections()
    assert any(t.text == "Portable" for t in stored)
    assert any(t.text == "Semi-Upright" for t in stored)

    cr_wl = [t.upper() for t in load_default_whitelist("CR")]
    drawn = _drawn_non_whitelisted(stored, cr_wl)
    drawn_texts = [t.text for t in drawn]
    assert "Portable" not in drawn_texts
    assert "Semi-Upright" not in drawn_texts
    assert "DAVIDSON DOUGLAS [M]" in drawn_texts
    assert "01.09.2012" in drawn_texts


def test_build_series_view_ocr_pixels_importable() -> None:
    """Guard against accidental removal of Series View OCR prep helper."""
    assert callable(build_series_view_ocr_pixels)
