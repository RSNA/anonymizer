"""Named exclude zones and remove-mode overlay filtering."""

from pathlib import Path

from anonymizer.controller.ai.embedded_phi.pixel.exclude_zones import (
    filter_ocr_for_remove_mode,
    modality_exclude_rects_for_series,
    normalize_user_rects,
    user_rects_from_normalized,
)
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import PhiMatchMode, make_annotate_whitelist
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrRemoveMode
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import (
    load_project_exclude_rects,
    save_project_exclude_rects,
)
from anonymizer.controller.series.series_overlay import NerEvidence, OCRText, OcrEvidence, UserRectangle, WhitelistEvidence


def _ocr(
    text: str,
    *,
    ner_label: str | None = None,
    ner_score: float = 0.95,
    wl_term: str | None = None,
    wl_score: float | None = None,
    box: tuple[int, int, int, int] = (0, 0, 10, 10),
) -> OCRText:
    x1, y1, x2, y2 = box
    entities = (("NAME", text),) if ner_label else ()
    return OCRText(
        text=text,
        top_left=(x1, y1),
        bottom_right=(x2, y2),
        ocr=OcrEvidence(prob=0.9),
        whitelist=WhitelistEvidence(term=wl_term, score=wl_score),
        ner=NerEvidence(
            label=ner_label,
            entities=entities,
            score=ner_score if ner_label else 0.0,
        ),
    )


def _with_whitelist(detections: list[OCRText], terms: list[str]) -> list[OCRText]:
    return make_annotate_whitelist(terms)(detections)


def test_normalize_and_scale_rects_round_trip() -> None:
    rects = [UserRectangle(top_left=(50, 25), bottom_right=(100, 75))]
    normalized = normalize_user_rects(rects, width=200, height=100)
    assert normalized == [{"x1": 0.25, "y1": 0.25, "x2": 0.5, "y2": 0.75}]
    scaled = user_rects_from_normalized(normalized, width=400, height=200)
    assert scaled[0].get_bounding_box() == (100, 50, 200, 150)


def test_save_and_load_exclude_rects(tmp_path: Path) -> None:
    save_project_exclude_rects(
        tmp_path,
        "US",
        [{"x1": 0.75, "y1": 0.69, "x2": 1.0, "y2": 1.0}],
    )
    stored = load_project_exclude_rects(tmp_path, "us")
    assert stored == [{"x1": 0.75, "y1": 0.69, "x2": 1.0, "y2": 1.0}]
    scaled = modality_exclude_rects_for_series(tmp_path, "US", width=1000, height=1000)
    assert scaled[0].get_bounding_box() == (750, 690, 1000, 1000)


def test_save_empty_exclude_rects_removes_file(tmp_path: Path) -> None:
    save_project_exclude_rects(
        tmp_path,
        "US",
        [{"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4}],
    )
    path = tmp_path / "whitelists" / "us.exclude.json"
    assert path.is_file()
    save_project_exclude_rects(tmp_path, "US", [])
    assert not path.is_file()
    assert load_project_exclude_rects(tmp_path, "US") == []


def test_load_legacy_named_zones_file(tmp_path: Path) -> None:
    path = tmp_path / "whitelists" / "us.exclude.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"zones": [{"name": "panel", "rects": [{"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4}]}]}\n',
        encoding="utf-8",
    )
    assert load_project_exclude_rects(tmp_path, "US") == [{"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4}]


def test_filter_ocr_for_remove_mode_phi_only_and_all_text() -> None:
    detections = _with_whitelist(
        [
            _ocr("DAVIDSON", ner_label="NAME", box=(0, 0, 20, 20)),
            _ocr("Portable", box=(30, 0, 50, 20)),
            _ocr("VEL", box=(100, 100, 140, 120)),
        ],
        ["PORTABLE"],
    )
    panel = [UserRectangle(top_left=(90, 90), bottom_right=(200, 200))]
    phi_only = filter_ocr_for_remove_mode(
        detections,
        remove_mode=OcrRemoveMode.PHI_ONLY,
        match_mode=PhiMatchMode.STANDARD,
        exclude_rects=panel,
    )
    assert [t.text for t in phi_only] == ["DAVIDSON"]
    all_text = filter_ocr_for_remove_mode(
        detections,
        remove_mode=OcrRemoveMode.ALL_TEXT,
        match_mode=PhiMatchMode.STANDARD,
        exclude_rects=panel,
    )
    assert [t.text for t in all_text] == ["DAVIDSON", "Portable"]
    non_wl = filter_ocr_for_remove_mode(
        detections,
        remove_mode=OcrRemoveMode.NON_WHITELISTED,
        match_mode=PhiMatchMode.STANDARD,
        exclude_rects=panel,
    )
    assert [t.text for t in non_wl] == ["DAVIDSON"]


def test_filter_phi_only_whitelist_vetoes_labeled_keeper() -> None:
    """A whitelist score above 0.8 wins even when NER is within 0.1."""
    detections = _with_whitelist(
        [
            _ocr("DAVIDSON", ner_label="NAME", box=(0, 0, 20, 20)),
            # Exact AXILLA (wl=1.0); NER 0.92 is within 0.1 and still loses.
            _ocr("AXILLA", ner_label="NAME", ner_score=0.92, box=(30, 0, 50, 20)),
            _ocr("Portable", box=(60, 0, 80, 20)),
        ],
        ["AXILLA"],
    )
    phi_only = filter_ocr_for_remove_mode(
        detections,
        remove_mode=OcrRemoveMode.PHI_ONLY,
        match_mode=PhiMatchMode.STANDARD,
    )
    assert [t.text for t in phi_only] == ["DAVIDSON"]
    all_text = filter_ocr_for_remove_mode(
        detections,
        remove_mode=OcrRemoveMode.ALL_TEXT,
        match_mode=PhiMatchMode.STANDARD,
    )
    assert [t.text for t in all_text] == ["DAVIDSON", "AXILLA", "Portable"]
    non_wl = filter_ocr_for_remove_mode(
        detections,
        remove_mode=OcrRemoveMode.NON_WHITELISTED,
        match_mode=PhiMatchMode.STANDARD,
    )
    assert [t.text for t in non_wl] == ["DAVIDSON", "Portable"]
