"""Controller tests: whitelist × NER permutations (Series View annotate vs batch filter)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    annotate_ocr_phi_labels,
    detect_text,
    filter_ocr_phi_ner,
    filter_ocr_whitelist_only,
)
from anonymizer.controller.series_overlay import OCRText

# Davidson-like overlay corpus (controller-level, no EasyOCR).
_DAVIDSON_TEXTS = (
    "DAVIDSON DOUGLAS [M]",
    "01.09.2012",
    "DOB: 06.16.1976",
    "Semi-Upright",
    "Portable",
    "L",
)


def _ocr(text: str, *, prob: float = 0.95) -> OCRText:
    return OCRText(text=text, top_left=(0, 0), bottom_right=(40, 20), prob=prob)


def _davidson_detections() -> list[OCRText]:
    return [_ocr(t) for t in _DAVIDSON_TEXTS]


def _fake_detect_phi(text: str, *, locale: str = "en_US") -> list[Entity]:
    """Deterministic PHI labels for Davidson-like strings (no model)."""
    t = text.strip()
    upper = t.upper()
    if "DAVIDSON" in upper or "DOUGLAS" in upper:
        return [Entity("NAME", 0, len(t), score=0.99)]
    if "DOB" in upper or (t.count(".") == 2 and any(ch.isdigit() for ch in t)):
        return [Entity("DATE", 0, len(t), score=0.95)]
    if "@" in t:
        return [Entity("EMAIL", 0, len(t), score=0.9)]
    return []


# --- Whitelist only -----------------------------------------------------------------


def test_empty_whitelist_keeps_all_davidson_overlay_text(caplog) -> None:
    dets = _davidson_detections()
    with caplog.at_level("INFO"):
        kept = filter_ocr_whitelist_only(dets, whitelist=[])
    assert [t.text for t in kept] == list(_DAVIDSON_TEXTS)
    assert "OCR whitelist: empty" in caplog.text


def test_none_whitelist_keeps_all() -> None:
    dets = _davidson_detections()
    assert [t.text for t in filter_ocr_whitelist_only(dets, whitelist=None)] == list(_DAVIDSON_TEXTS)


def test_portable_whitelist_hides_portable_keeps_semi_upright(caplog) -> None:
    dets = _davidson_detections()
    with caplog.at_level("INFO"):
        kept = filter_ocr_whitelist_only(dets, whitelist=["PORTABLE"])
    texts = [t.text for t in kept]
    assert "Portable" not in texts
    assert "Semi-Upright" in texts
    assert "DAVIDSON DOUGLAS [M]" in texts
    assert "OCR whitelist hid 1 detection(s)" in caplog.text


def test_whitelist_preserves_phi_label() -> None:
    labeled = OCRText(
        text="Portable",
        top_left=(0, 0),
        bottom_right=(10, 10),
        prob=0.9,
        phi_label=None,
    )
    name = OCRText(
        text="DAVIDSON",
        top_left=(0, 0),
        bottom_right=(10, 10),
        prob=0.9,
        phi_label="NAME",
    )
    kept = filter_ocr_whitelist_only([labeled, name], whitelist=["PORTABLE"])
    assert [t.text for t in kept] == ["DAVIDSON"]
    assert kept[0].phi_label == "NAME"


# --- NER annotate (Series View) -------------------------------------------------------


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_fake_detect_phi,
)
def test_annotate_labels_phi_without_dropping_overlay(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
    caplog,
) -> None:
    dets = filter_ocr_whitelist_only(_davidson_detections(), whitelist=[])
    with caplog.at_level("INFO"):
        out = annotate_ocr_phi_labels(dets)
    by_text = {t.text: t.phi_label for t in out}
    assert len(out) == len(dets)
    assert by_text["DAVIDSON DOUGLAS [M]"] == "NAME"
    assert by_text["01.09.2012"] == "DATE"
    assert by_text["DOB: 06.16.1976"] == "DATE"
    assert by_text["Portable"] is None
    assert by_text["Semi-Upright"] is None
    assert "OCR→NER classify: 3 labeled" in caplog.text


def _name_split_detect_phi(text: str, *, locale: str = "en_US") -> list[Entity]:
    """Olivia is NAME alone; Diaz is not; the full phrase is NAME covering both tokens."""
    t = text.strip()
    if t == "Olivia Diaz":
        return [Entity("NAME", 0, len(t), score=0.99)]
    if t == "Olivia":
        start = t.find("Olivia")
        return [Entity("NAME", start, start + 6, score=0.99)]
    if t.startswith("Olivia ") and t != "Olivia Diaz":
        start = t.find("Olivia")
        return [Entity("NAME", start, start + 6, score=0.99)]
    return []


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_name_split_detect_phi,
)
def test_annotate_propagates_name_to_adjacent_unlabeled_surname(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    olivia = OCRText(text="Olivia", top_left=(100, 20), bottom_right=(160, 40), prob=0.95)
    diaz = OCRText(text="Diaz", top_left=(166, 20), bottom_right=(210, 40), prob=0.95)
    left = OCRText(text="LEFT", top_left=(120, 200), bottom_right=(180, 220), prob=0.95)
    out = annotate_ocr_phi_labels([olivia, diaz, left])
    by_text = {t.text: t.phi_label for t in out}
    assert by_text["Olivia"] == "NAME"
    assert by_text["Diaz"] == "NAME"
    assert by_text["LEFT"] is None


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_name_split_detect_phi,
)
def test_annotate_does_not_label_adjacent_overlay_when_span_is_first_name_only(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    olivia = OCRText(text="Olivia", top_left=(100, 20), bottom_right=(160, 40), prob=0.95)
    left = OCRText(text="LEFT", top_left=(166, 20), bottom_right=(210, 40), prob=0.95)
    out = annotate_ocr_phi_labels([olivia, left])
    by_text = {t.text: t.phi_label for t in out}
    assert by_text["Olivia"] == "NAME"
    assert by_text["LEFT"] is None


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_name_split_detect_phi,
)
def test_batch_ner_filter_keeps_adjacent_surname_after_context_pass(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    olivia = OCRText(text="Olivia", top_left=(100, 20), bottom_right=(160, 40), prob=0.95)
    diaz = OCRText(text="Diaz", top_left=(166, 20), bottom_right=(210, 40), prob=0.95)
    portable = OCRText(text="Portable", top_left=(10, 80), bottom_right=(90, 100), prob=0.95)
    kept = filter_ocr_phi_ner([olivia, diaz, portable])
    assert {t.text: t.phi_label for t in kept} == {"Olivia": "NAME", "Diaz": "NAME"}


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=False)
def test_annotate_when_ner_missing_keeps_all_unlabeled(
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    dets = _davidson_detections()
    out = annotate_ocr_phi_labels(dets)
    assert len(out) == len(dets)
    assert all(t.phi_label is None for t in out)


# --- NER filter (batch remove) --------------------------------------------------------


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_fake_detect_phi,
)
def test_batch_ner_filter_drops_portable_keeps_name_date(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    after_wl = filter_ocr_whitelist_only(_davidson_detections(), whitelist=[])
    kept = filter_ocr_phi_ner(after_wl)
    texts = [t.text for t in kept]
    assert "Portable" not in texts
    assert "Semi-Upright" not in texts
    assert "DAVIDSON DOUGLAS [M]" in texts
    assert "01.09.2012" in texts
    assert all(t.phi_label in {"NAME", "DATE"} for t in kept)


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_fake_detect_phi,
)
def test_batch_whitelist_then_ner_hides_portable_before_classify(
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    """PORTABLE never reaches NER when whitelisted; PHI still kept."""
    after_wl = filter_ocr_whitelist_only(_davidson_detections(), whitelist=["PORTABLE"])
    assert not any("portable" in t.text.lower() for t in after_wl)
    kept = filter_ocr_phi_ner(after_wl)
    texts = [t.text for t in kept]
    assert "Portable" not in texts
    assert "DAVIDSON DOUGLAS [M]" in texts


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=False)
def test_batch_ner_filter_drops_all_when_ner_missing(
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    assert filter_ocr_phi_ner(_davidson_detections()) == []


# --- detect_text mode wiring (mocked EasyOCR) -----------------------------------------


def _easyocr_davidson_results():
    """Minimal EasyOCR-shaped results for detect_text."""
    out = []
    for i, text in enumerate(_DAVIDSON_TEXTS):
        y = i * 30
        box = [[0, y], [100, y], [100, y + 20], [0, y + 20]]
        out.append((box, text, 0.95))
    return out


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_fake_detect_phi,
)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text._easyocr_readtext",
    return_value=_easyocr_davidson_results(),
)
def test_series_view_detect_mode_keeps_portable_and_labels_phi(
    _mock_ocr: MagicMock,
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    import numpy as np

    pixels = np.zeros((200, 200), dtype=np.uint8)
    results = detect_text(
        pixels,
        MagicMock(),
        modality="CR",
        apply_noise_filter=False,
        apply_phi_ner_filter=False,
        annotate_phi_labels=True,
        whitelist=[],
    )
    assert results is not None
    texts = [t.text for t in results]
    assert "Portable" in texts
    assert "Semi-Upright" in texts
    by_text = {t.text: t.phi_label for t in results}
    assert by_text.get("DAVIDSON DOUGLAS [M]") == "NAME"
    assert by_text.get("Portable") is None


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_fake_detect_phi,
)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text._easyocr_readtext",
    return_value=_easyocr_davidson_results(),
)
def test_series_view_detect_with_portable_whitelist_hides_before_classify(
    _mock_ocr: MagicMock,
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    import numpy as np

    pixels = np.zeros((200, 200), dtype=np.uint8)
    results = detect_text(
        pixels,
        MagicMock(),
        modality="CR",
        apply_noise_filter=False,
        apply_phi_ner_filter=False,
        annotate_phi_labels=True,
        whitelist=["PORTABLE"],
    )
    assert results is not None
    texts = [t.text for t in results]
    assert "Portable" not in texts
    assert "Semi-Upright" in texts
    assert any(t.phi_label == "NAME" for t in results)


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_fake_detect_phi,
)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text._easyocr_readtext",
    return_value=_easyocr_davidson_results(),
)
def test_batch_detect_mode_filters_to_phi_only(
    _mock_ocr: MagicMock,
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    """Opt-in NER keep-filter: batch may request PHI-only after noise+whitelist."""
    import numpy as np

    pixels = np.zeros((200, 200), dtype=np.uint8)
    results = detect_text(
        pixels,
        MagicMock(),
        modality="CR",
        apply_noise_filter=True,
        apply_phi_ner_filter=True,
        annotate_phi_labels=False,
        whitelist=[],
    )
    assert results is not None
    texts = [t.text for t in results]
    assert "Portable" not in texts
    assert "Semi-Upright" not in texts
    assert any("DAVIDSON" in t for t in texts)
    assert all(t.phi_label for t in results)


def test_series_view_store_all_then_display_whitelist() -> None:
    """Series View contract: detect stores all; display filter applies whitelist."""
    from anonymizer.utils.storage import load_default_whitelist

    stored = _davidson_detections()
    assert any(t.text == "Portable" for t in stored)
    assert any(t.text == "Semi-Upright" for t in stored)

    cr_wl = [t.upper() for t in load_default_whitelist("CR")]
    drawn = filter_ocr_whitelist_only(stored, whitelist=cr_wl)
    drawn_texts = [t.text for t in drawn]
    assert "Portable" not in drawn_texts
    assert "Semi-Upright" not in drawn_texts
    assert "DAVIDSON DOUGLAS [M]" in drawn_texts
    assert "01.09.2012" in drawn_texts


@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_locale_supported",
    return_value=True,
)
@patch("anonymizer.controller.ai.embedded_phi.pixel.detect_text.ner_ready", return_value=True)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text.detect_entities",
    side_effect=_fake_detect_phi,
)
@patch(
    "anonymizer.controller.ai.embedded_phi.pixel.detect_text._easyocr_readtext",
    return_value=_easyocr_davidson_results(),
)
def test_both_ner_flags_prefers_batch_filter(
    _mock_ocr: MagicMock,
    _mock_detect: MagicMock,
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
    caplog,
) -> None:
    import numpy as np

    pixels = np.zeros((200, 200), dtype=np.uint8)
    with caplog.at_level("WARNING"):
        results = detect_text(
            pixels,
            MagicMock(),
            modality="CR",
            apply_noise_filter=True,
            apply_phi_ner_filter=True,
            annotate_phi_labels=True,
            whitelist=[],
        )
    assert results is not None
    assert "using filter (batch) mode" in caplog.text
    texts = [t.text for t in results]
    assert "Portable" not in texts
    assert any("DAVIDSON" in t for t in texts)
