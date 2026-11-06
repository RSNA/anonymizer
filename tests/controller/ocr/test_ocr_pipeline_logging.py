"""Stage-local OCR pipeline log formatting."""

from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import (
    PhiMatchMode,
    annotate_ner,
    effective_phi_label,
    format_ocr_texts_for_log,
    is_whitelisted,
    make_annotate_whitelist,
    phi_accepted,
)
from anonymizer.controller.series.series_overlay import (
    NerEvidence,
    OCRText,
    OcrEvidence,
    WhitelistEvidence,
)


def _box(
    text: str,
    *,
    prob: float = 1.0,
    wl_score: float | None = None,
    wl_term: str | None = None,
    ner_label: str | None = None,
    ner_score: float | None = None,
) -> OCRText:
    return OCRText(
        text=text,
        top_left=(0, 0),
        bottom_right=(10, 10),
        ocr=OcrEvidence(prob=prob),
        whitelist=WhitelistEvidence(term=wl_term, score=wl_score),
        ner=NerEvidence(label=ner_label, score=ner_score),
    )


def test_format_detect_text_stage_local_prob_one_decimal() -> None:
    texts = [_box("M", prob=1.0), _box("SAWYER", prob=1.0), _box("S", prob=0.4)]
    body = format_ocr_texts_for_log("detect_text", texts)
    lines = body.splitlines()
    assert lines[0] == "=== detect_text  3 boxes ==="
    assert lines[1] == "  'M' | 1.0"
    assert lines[2] == "  'SAWYER' | 1.0"
    assert lines[3] == "  'S' | 0.4"
    assert len(lines) == 4
    assert "prob=" not in body


def test_format_noise_header_includes_dropped() -> None:
    texts = [_box("M"), _box("SAWYER")]
    body = format_ocr_texts_for_log("filter_ocr_noise", texts, dropped=1)
    assert body.splitlines()[0] == "=== filter_ocr_noise  2 boxes (dropped 1) ==="
    assert " | " in body
    assert "prob=" not in body
    assert "score=" not in body


def test_format_whitelist_annotate_uses_em_dash_when_no_term() -> None:
    texts = [
        _box("M", wl_score=1.0, wl_term="M"),
        _box("SAWYER", wl_score=0.0, wl_term=None),
    ]
    body = format_ocr_texts_for_log("annotate_whitelist", texts)
    lines = body.splitlines()
    assert lines[0] == "=== annotate_whitelist  2 boxes ==="
    assert lines[1] == "  'M' | 1.00 | 'M'"
    assert lines[2] == "  'SAWYER' | 0.00 | —"
    assert "prob=" not in body
    assert "score=" not in body


def test_format_ner_annotate_stage_local() -> None:
    texts = [
        _box("M", ner_label=None, ner_score=0.0),
        _box("SAWYER", ner_label="NAME", ner_score=0.62),
    ]
    body = format_ocr_texts_for_log("annotate_ner", texts)
    lines = body.splitlines()
    assert lines[0] == "=== annotate_ner  2 boxes ==="
    assert lines[1] == "  'M' | 0.00 | —"
    assert lines[2] == "  'SAWYER' | 0.62 | NAME"
    assert "score=" not in body


def test_format_decisions_outcomes() -> None:
    texts = make_annotate_whitelist(["M"])(
        [
            _box("M"),
            _box("SAWYER", ner_label="NAME", ner_score=0.62),
        ]
    )
    # Preserve NER on Sawyer after whitelist annotate (factory copies ner).
    texts[1] = OCRText(
        text=texts[1].text,
        top_left=texts[1].top_left,
        bottom_right=texts[1].bottom_right,
        ocr=texts[1].ocr,
        whitelist=texts[1].whitelist,
        ner=NerEvidence(label="NAME", score=0.62),
    )
    mode = PhiMatchMode.STANDARD
    assert is_whitelisted(texts[0], mode)
    assert phi_accepted(texts[1], mode)
    body = format_ocr_texts_for_log("decisions", texts, mode=mode)
    lines = body.splitlines()
    assert lines[0].startswith("=== decisions  mode=STANDARD  wl>=0.85  ner>=0.30  2 boxes ===")
    assert lines[1] == "  'M' | whitelisted"
    assert lines[2] == "  'SAWYER' | phi_accepted"
    with_scope = format_ocr_texts_for_log(
        "decisions", texts, mode=mode, remove_mode="non_whitelisted"
    )
    assert "remove=non_whitelisted" in with_scope.splitlines()[0]


def test_annotate_ner_without_model_stamps_zero_scores() -> None:
    texts = [_box("SAWYER")]
    out = annotate_ner(texts, detect_fn=lambda *_a, **_k: [])
    assert out[0].ner.score == 0.0
    assert out[0].ner.label is None


def test_caller_decide_whitelist_overrides_ner_when_margin_met() -> None:
    """A whitelist score above 0.8 wins even when NER is within 0.1."""
    mode = PhiMatchMode.STANDARD
    # Exact whitelist hit at 1.0; NER NAME 0.92 is within 0.1 and still loses.
    axilla = make_annotate_whitelist(["AXILLA"])(
        [_box("AXILLA", ner_label="NAME", ner_score=0.92)]
    )[0]
    axilla = OCRText(
        text=axilla.text,
        top_left=axilla.top_left,
        bottom_right=axilla.bottom_right,
        ocr=axilla.ocr,
        whitelist=axilla.whitelist,
        ner=NerEvidence(label="NAME", score=0.92),
    )
    assert axilla.ner.label == "NAME"
    assert is_whitelisted(axilla, mode)
    assert axilla.whitelist.score == 1.0
    assert not phi_accepted(axilla, mode)
    assert effective_phi_label(axilla, mode) is None
    body = format_ocr_texts_for_log("decisions", [axilla], mode=mode)
    assert " | whitelisted" in body
    assert "phi_accepted" not in body

    name = _box("SAWYER", ner_label="NAME", ner_score=0.95)
    assert phi_accepted(name, mode)
    assert effective_phi_label(name, mode) == "NAME"


def test_caller_decide_ner_beats_fuzzy_whitelist_within_margin() -> None:
    """Lenient fuzzy whitelist must not veto a close NER name score."""
    mode = PhiMatchMode.LENIENT
    bailey = _box(
        "Bailey",
        ner_label="NAME",
        ner_score=0.80,
        wl_term="BILAT",
        wl_score=0.70,
    )
    assert is_whitelisted(bailey, mode)
    # 0.80 >= 0.70 - 0.1 → NER wins
    assert phi_accepted(bailey, mode)
    assert effective_phi_label(bailey, mode) == "NAME"
    body = format_ocr_texts_for_log("decisions", [bailey], mode=mode)
    assert " | phi_accepted" in body
