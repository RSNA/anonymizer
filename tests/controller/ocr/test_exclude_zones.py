"""Named exclude zones and remove-mode overlay filtering."""

from __future__ import annotations

from pathlib import Path

from anonymizer.controller.ai.embedded_phi.pixel.exclude_zones import (
    filter_ocr_for_remove_mode,
    modality_exclude_rects_for_series,
    normalize_user_rects,
    user_rects_from_normalized,
)
from anonymizer.controller.jobs.runner import OcrRemoveMode
from anonymizer.controller.series.series_overlay import OCRText, UserRectangle
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import (
    load_project_exclude_rects,
    save_project_exclude_rects,
)


def _ocr(text: str, *, phi: str | None = None, box: tuple[int, int, int, int] = (0, 0, 10, 10)) -> OCRText:
    x1, y1, x2, y2 = box
    return OCRText(text=text, top_left=(x1, y1), bottom_right=(x2, y2), prob=0.9, phi_label=phi)


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
    detections = [
        _ocr("DAVIDSON", phi="NAME", box=(0, 0, 20, 20)),
        _ocr("Portable", box=(30, 0, 50, 20)),
        _ocr("VEL", box=(100, 100, 140, 120)),
    ]
    panel = [UserRectangle(top_left=(90, 90), bottom_right=(200, 200))]
    phi_only = filter_ocr_for_remove_mode(
        detections,
        remove_mode=OcrRemoveMode.PHI_ONLY,
        whitelist=["PORTABLE"],
        exclude_rects=panel,
    )
    assert [t.text for t in phi_only] == ["DAVIDSON"]
    all_text = filter_ocr_for_remove_mode(
        detections,
        remove_mode=OcrRemoveMode.ALL_TEXT,
        whitelist=["PORTABLE"],
        exclude_rects=panel,
    )
    assert [t.text for t in all_text] == ["DAVIDSON", "Portable"]
    non_wl = filter_ocr_for_remove_mode(
        detections,
        remove_mode=OcrRemoveMode.NON_WHITELISTED,
        whitelist=["PORTABLE"],
        exclude_rects=panel,
    )
    assert [t.text for t in non_wl] == ["DAVIDSON"]
