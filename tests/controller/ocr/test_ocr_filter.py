"""Tests for shared OCR noise filtering and batch removal modes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from anonymizer.controller.ai.batch_process import format_remove_pixel_phi_instance_detail
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import (
    PhiMatchMode,
    annotate_ner,
    detect_text,
    filter_ocr_noise,
    is_whitelisted,
    make_annotate_whitelist,
    normalize_clock_text_for_ner,
    pipe,
    thresholds_for,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import (
    PixelPhiRemovalMode,
    _apply_frame_removal_mask,
    _map_ocr_texts_to_source_coordinates,
    blackout_ocr_text_areas,
    remove_pixel_phi,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrRemoveMode, texts_for_remove_mode
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import (
    load_modality_phi_match_mode,
    load_modality_whitelist,
    save_modality_phi_match_mode,
)
from anonymizer.controller.series.series_overlay import OCRText, OcrEvidence
from anonymizer.utils.memory import MemorySnapshot, format_memory_snapshot_label


def _ocr(text: str, *, prob: float = 0.9, box: tuple[int, int, int, int] = (0, 0, 20, 20)) -> OCRText:
    x1, y1, x2, y2 = box
    return OCRText(text=text, top_left=(x1, y1), bottom_right=(x2, y2), ocr=OcrEvidence(prob=prob))


def _detect_with_noise_filter(
    pixels: np.ndarray,
    reader: MagicMock,
    *,
    modality: str | None = None,
) -> list[OCRText]:
    return filter_ocr_noise(detect_text(pixels, reader, modality=modality), modality=modality)


def test_detect_text_tilted_quad_uses_aabb() -> None:
    """Free-form / diagonal EasyOCR quads must not assume corner 0/2 are TL/BR."""
    tilted = (
        [[48.0, 296.0], [460.0, 235.0], [470.0, 250.0], [58.0, 311.0]],
        "FTA",
        0.91,
    )
    reader = MagicMock()
    reader.readtext.return_value = [tilted]
    results = detect_text(np.zeros((600, 800, 3), dtype=np.uint8), reader)
    assert len(results) == 1
    assert results[0].text == "FTA"
    assert results[0].top_left == (48, 235)
    assert results[0].bottom_right == (470, 311)


def test_filter_ocr_noise_rejects_short_numeric_small_box() -> None:
    detections = [_ocr("008", prob=0.95, box=(0, 0, 28, 14))]
    assert filter_ocr_noise(detections) == []


def test_filter_ocr_noise_keeps_short_numeric_large_box() -> None:
    detections = [_ocr("2024", prob=0.95, box=(0, 0, 40, 20))]
    assert len(filter_ocr_noise(detections)) == 1


def test_filter_ocr_noise_rejects_tiny_area_per_character() -> None:
    detections = [_ocr("008", prob=0.95, box=(0, 0, 10, 10))]
    assert filter_ocr_noise(detections) == []


def test_filter_ocr_noise_rejects_noise_hits() -> None:
    detections = [
        _ocr(";", prob=0.95),
        _ocr("8", prob=0.95),
        _ocr("g", prob=0.95),
        _ocr(":", prob=0.95),
        _ocr("x", prob=0.4),
    ]
    assert filter_ocr_noise(detections) == []


def test_filter_ocr_noise_keeps_weak_but_usable_prob() -> None:
    """min_prob is low (0.25): whitelist/NER decide; do not cull weak PHI hits."""
    detections = [
        _ocr("23859853", prob=0.3, box=(0, 0, 80, 20)),
        _ocr("12 /Mar / 1991", prob=0.5, box=(0, 30, 120, 50)),
    ]
    kept = filter_ocr_noise(detections)
    assert [t.text for t in kept] == ["23859853", "12 /Mar / 1991"]


def test_filter_ocr_noise_keeps_long_low_prob_overlay_text() -> None:
    """Long low-prob strings (blacked-out overlay OCR) skip min_prob; short junk does not."""
    detections = [
        _ocr("18:18:EÉfT", prob=0.2, box=(0, 0, 100, 24)),
        _ocr(",", prob=0.2, box=(0, 30, 20, 50)),
        _ocr("ab", prob=0.2, box=(0, 60, 40, 80)),
        _ocr("4", prob=1.0, box=(0, 90, 20, 110)),
    ]
    kept = filter_ocr_noise(detections)
    assert [t.text for t in kept] == ["18:18:EÉfT"]


def test_filter_ocr_noise_keeps_single_letter_for_cr_dx_mg() -> None:
    """XR laterality markers are one character on CR/DX/MG; CT still requires min length 2."""
    detections = [_ocr("R", box=(0, 0, 24, 24))]
    assert filter_ocr_noise(detections, modality="CT") == []
    assert len(filter_ocr_noise(detections, modality="CR")) == 1
    assert len(filter_ocr_noise(detections, modality="DX")) == 1
    assert len(filter_ocr_noise(detections, modality="MG")) == 1


def test_detect_text_cr_noise_filter_keeps_laterality_r() -> None:
    reader = MagicMock()
    reader.readtext.return_value = [
        ([(0, 0), (24, 0), (24, 24), (0, 24)], "R", 0.92),
    ]
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    results = _detect_with_noise_filter(pixels, reader, modality="CR")
    assert [item.text for item in results] == ["R"]


def test_filter_ocr_noise_keeps_alphanumeric_above_threshold() -> None:
    detections = [_ocr("SMITH^JOHN", prob=0.92), _ocr("AXIAL", prob=0.88)]
    assert len(filter_ocr_noise(detections)) == 2


def test_is_whitelisted_fuzzy_match() -> None:
    detections = [_ocr("AXIAL", prob=0.9), _ocr("PATIENT NAME", prob=0.9)]
    annotated = make_annotate_whitelist(["AXIL"])(detections)
    assert is_whitelisted(annotated[0], PhiMatchMode.STANDARD)
    assert not is_whitelisted(annotated[1], PhiMatchMode.STANDARD)


def test_is_whitelisted_word_basis_on_merged_phrase() -> None:
    """Merged OCR boxes still match single-word whitelist terms."""
    detections = [_ocr("LEFT TRANS AXILLA", prob=0.9)]
    annotated = make_annotate_whitelist(["LEFT", "TRANS", "AXILLA"])(detections)
    assert annotated[0].whitelist.score == pytest.approx(1.0)
    assert annotated[0].whitelist.term == "LEFT"
    assert is_whitelisted(annotated[0], PhiMatchMode.EXACT)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20:28:31", "20:28:31"),
        ("20:28.31", "20:28:31"),
        ("7 05 09", "07:05:09"),
        ("20-28-31", "20:28:31"),
        ("06.16.1976", "06.16.1976"),
        ("LEFT", "LEFT"),
        ("16.60.27", "16.60.27"),  # invalid minutes — not normalized
        ("25:00:00", "25:00:00"),  # invalid hour — not normalized
        # Digit 8 as ':' (any OCR confidence) when groups form a valid clock.
        ("23853853", "23:53:53"),
        ("23859853", "23:59:53"),
        ("01819814", "01:19:14"),
        ("01,819814", "01:19:14"),  # mixed ',' + '8' separators
        ("01:819:14", "01:19:14"),
        ("99859853", "99859853"),  # invalid hour
        ("23859953", "23859953"),  # invalid seconds
    ],
)
def test_normalize_clock_text_for_ner(raw: str, expected: str) -> None:
    assert normalize_clock_text_for_ner(raw) == expected


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
def test_annotate_ner_normalizes_us_clocks_and_keeps_time(
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    from anonymizer.controller.ai.embedded_phi.ner.engine import Entity

    seen: list[str] = []

    def detect(body: str):
        seen.append(body)
        start = body.index("20:28:31")
        return [Entity("TIME", start, start + 8, score=0.9, raw_label="time")]

    out = annotate_ner(
        [_ocr("20:28.31"), _ocr("LEFT")],
        modality="US",
        detect_fn=detect,
    )
    assert seen == ["20:28:31, LEFT"]
    assert out[0].text == "20:28:31"
    assert out[0].ner.label == "TIME"
    assert out[1].text == "LEFT"


@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.detect_locale_supported", return_value=True)
@patch("anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline.ner_ready", return_value=True)
def test_annotate_ner_skips_clock_normalize_for_ct(
    _mock_ready: MagicMock,
    _mock_locale: MagicMock,
) -> None:
    seen: list[str] = []

    def detect(body: str):
        seen.append(body)
        return []

    out = annotate_ner([_ocr("20:28.31")], modality="CT", detect_fn=detect)
    assert seen == ["20:28.31"]
    assert out[0].text == "20:28.31"


def test_is_whitelisted_table_does_not_match_portable() -> None:
    """TABLE fuzzy-similarity to PORTABLE must not hide Portable when PORTABLE is removed."""
    detections = [_ocr("Portable"), _ocr("DAVIDSON")]
    annotated = make_annotate_whitelist(["TABLE", "CHEST"])(detections)
    assert not is_whitelisted(annotated[0], PhiMatchMode.STANDARD)
    assert not is_whitelisted(annotated[1], PhiMatchMode.STANDARD)


def test_is_whitelisted_portable_on_effective_list() -> None:
    detections = [_ocr("Portable", prob=0.9), _ocr("DAVIDSON", prob=0.9)]
    annotated = make_annotate_whitelist(["PORTABLE"])(detections)
    assert is_whitelisted(annotated[0], PhiMatchMode.STANDARD)
    assert not is_whitelisted(annotated[1], PhiMatchMode.STANDARD)


def test_empty_whitelist_leaves_portable_unmarked() -> None:
    detections = [_ocr("Portable", prob=0.9), _ocr("DAVIDSON", prob=0.9)]
    annotated = make_annotate_whitelist([])(detections)
    assert not is_whitelisted(annotated[0], PhiMatchMode.STANDARD)
    assert not is_whitelisted(annotated[1], PhiMatchMode.STANDARD)


def test_load_modality_whitelist_cr_includes_portable(monkeypatch: pytest.MonkeyPatch) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    whitelist = load_modality_whitelist(None, "CR")
    assert "PORTABLE" in whitelist


def test_load_modality_whitelist_mg_includes_view_abbreviations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MG has its own list (not DX); burnt-in views like LMCC must be whitelisted."""
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    whitelist = load_modality_whitelist(None, "MG")
    for term in ("CC", "MLO", "LMCC", "RMLO", "XCCL", "L", "R", "M", "S"):
        assert term in whitelist


def test_load_modality_whitelist_uses_project_file_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    project_dir = tmp_path / "project"
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("CUSTOMTERM\n", encoding="utf-8")

    whitelist = load_modality_whitelist(project_dir, "CR")
    assert "CUSTOMTERM" in whitelist
    assert "PORTABLE" not in whitelist


def test_load_modality_whitelist_project_file_replaces_defaults_without_removed_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import load_default_whitelist

    project_dir = tmp_path / "project"
    defaults_without_bilateral = [
        term for term in load_default_whitelist("CR") if term != "BILATERAL"
    ]
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("\n".join(defaults_without_bilateral) + "\n", encoding="utf-8")

    whitelist = load_modality_whitelist(project_dir, "CR")
    assert "PORTABLE" in whitelist
    assert "BILATERAL" not in whitelist


def test_detect_text_then_noise_filter_drops_symbol_noise() -> None:
    reader = MagicMock()
    reader.readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], ";", 0.95),
        ([(0, 0), (40, 0), (40, 20), (0, 20)], "SMITH", 0.92),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    results = _detect_with_noise_filter(pixels, reader)
    assert [item.text for item in results] == ["SMITH"]


def test_noise_filter_ct_drops_single_char_spurious() -> None:
    reader = MagicMock()
    reader.readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "0", 0.95),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "U", 0.92),
        ([(0, 0), (80, 0), (80, 20), (0, 20)], "SMITH", 0.92),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    results = _detect_with_noise_filter(pixels, reader, modality="CT")
    assert [item.text for item in results] == ["SMITH"]


def test_noise_filter_ct_drops_short_numeric_and_symbol_noise() -> None:
    """CT noise filter drops slice/HU-style false positives in small boxes."""
    reader = MagicMock()
    reader.readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "64", 0.95),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "04", 0.94),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "229", 0.93),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "9 <", 0.91),
        ([(0, 0), (40, 0), (40, 20), (0, 20)], ">>", 0.90),
        ([(0, 0), (100, 0), (100, 20), (0, 20)], "01.09.2012", 0.92),
        ([(0, 0), (80, 0), (80, 20), (0, 20)], "SMITH", 0.92),
        ([(0, 0), (60, 0), (60, 20), (0, 20)], "12345", 0.91),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    results = _detect_with_noise_filter(pixels, reader, modality="CT")
    assert [item.text for item in results] == ["9 <", "01.09.2012", "SMITH", "12345"]


def test_detect_text_us_returns_single_chars_before_noise_filter() -> None:
    """Raw detect keeps US single-character hits; noise filter may drop them separately."""
    reader = MagicMock()
    reader.readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "0", 0.95),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "U", 0.92),
        ([(0, 0), (80, 0), (80, 20), (0, 20)], "SMITH", 0.92),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    raw = detect_text(pixels, reader, modality="US")
    assert {item.text for item in raw} == {"0", "U", "SMITH"}


def test_noise_filter_us_drops_short_tokens_with_default_min_len() -> None:
    reader = MagicMock()
    reader.readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "64", 0.95),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "9 <", 0.91),
        ([(0, 0), (80, 0), (80, 20), (0, 20)], "SMITH", 0.92),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    results = _detect_with_noise_filter(pixels, reader, modality="US")
    assert [item.text for item in results] == ["9 <", "SMITH"]


@patch("anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi.dcmread")
def test_remove_pixel_phi_all_noise_is_no_op(
    mock_dcmread: MagicMock,
) -> None:
    pixels = np.zeros((64, 64), dtype=np.uint8)
    ds = MagicMock()
    ds.get.side_effect = lambda key, default=None: {
        "PhotometricInterpretation": "MONOCHROME2",
        "Modality": "CT",
        "SamplesPerPixel": 1,
        "Rows": 64,
        "Columns": 64,
        "BitsAllocated": 8,
        "BitsStored": 8,
        "HighBit": 7,
        "PixelRepresentation": 0,
        "NumberOfFrames": 1,
    }.get(key, default)
    ds.pixel_array = pixels
    ds.PixelData = b"\x00"
    ds.file_meta.TransferSyntaxUID.is_compressed = False
    mock_dcmread.return_value = ds

    reader = MagicMock()
    reader.readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], ";", 0.95),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "8", 0.95),
    ]

    modified, texts, pixels_changed = remove_pixel_phi(Path("/tmp/test.dcm"), reader, whitelist=[])
    assert modified is False
    assert texts == []
    assert pixels_changed == 0
    ds.save_as.assert_not_called()


def test_blackout_ocr_text_areas_zeros_bounding_boxes() -> None:
    frame = np.full((8, 8), 100, dtype=np.uint8)
    texts = [
        OCRText(text="PHI", top_left=(2, 2), bottom_right=(5, 5), ocr=OcrEvidence(prob=0.9)),
    ]
    blackout_ocr_text_areas(frame, texts)
    assert frame[2:5, 2:5].max() == 0
    assert frame[0, 0] == 100


def test_map_ocr_texts_to_source_coordinates_removes_border() -> None:
    texts = [
        OCRText(text="PHI", top_left=(22, 22), bottom_right=(42, 42), ocr=OcrEvidence(prob=0.9)),
    ]
    mapped = _map_ocr_texts_to_source_coordinates(
        texts,
        border_size=20,
        scale_factor=1.0,
        source_cols=100,
        source_rows=100,
    )
    assert len(mapped) == 1
    assert mapped[0].top_left == (2, 2)
    assert mapped[0].bottom_right == (22, 22)


def test_apply_frame_removal_blackout_requires_series_view_routine() -> None:
    frame = np.full((8, 8), 100, dtype=np.uint8)
    mask = np.zeros((8, 8), dtype=np.uint8)
    with pytest.raises(ValueError, match="blackout_ocr_text_areas"):
        _apply_frame_removal_mask(
            frame,
            mask,
            bits_allocated=8,
            pixel_representation=0,
            removal_mode=PixelPhiRemovalMode.BLACKOUT,
        )


@patch("anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi.inpaint")
def test_apply_frame_removal_inpaint_uses_cv2(mock_inpaint: MagicMock) -> None:
    frame = np.full((8, 8), 100, dtype=np.uint8)
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[2:5, 2:5] = 255
    mock_inpaint.return_value = frame.copy()
    _apply_frame_removal_mask(
        frame,
        mask,
        bits_allocated=8,
        pixel_representation=0,
        removal_mode=PixelPhiRemovalMode.INPAINT,
    )
    mock_inpaint.assert_called_once()


def test_format_remove_pixel_phi_instance_detail_blackout() -> None:
    detail = format_remove_pixel_phi_instance_detail(
        instance_index=1,
        instance_total=10,
        modified=True,
        texts=["PHI"],
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
        pixels_changed=412,
    )
    assert "Non-whitelisted text" in detail
    assert "blackout" in detail
    assert "1 PHI removed" in detail
    assert "pixels" not in detail
    assert "text region" not in detail
    assert "PHI" not in detail.replace("PHI removed", "")


def test_format_memory_snapshot_label_available_only() -> None:
    snapshot = MemorySnapshot(rss_mb=3000, available_mb=12800, total_mb=32768, percent_used=60)
    label = format_memory_snapshot_label(snapshot)
    assert "12.5 GB" in label
    assert "RSS" not in label
    assert "total" not in label.lower()


def test_series_view_display_filter_hides_whitelist_only_not_noise() -> None:
    """Overlay WYSIWYG: noise filter drops junk; Remove Scope hides whitelist matches."""
    detections = [
        _ocr("LEFT", box=(10, 10, 60, 30)),
        _ocr("CLIP", box=(70, 10, 120, 30)),
        _ocr("9", box=(130, 10, 150, 30)),
        _ocr("23889858", box=(160, 10, 260, 30)),
    ]
    us_wl = ["LEFT", "CLIP"]
    noise_filtered = filter_ocr_noise(detections)
    annotated = make_annotate_whitelist(us_wl)(detections)
    display_filtered = texts_for_remove_mode(
        annotated,
        OcrRemoveMode.NON_WHITELISTED,
        PhiMatchMode.STANDARD,
    )

    assert "LEFT" not in [t.text for t in display_filtered]
    assert "CLIP" not in [t.text for t in display_filtered]
    assert "9" in [t.text for t in display_filtered]
    assert "23889858" in [t.text for t in display_filtered]
    assert "9" not in [t.text for t in noise_filtered]


def test_load_modality_whitelist_project_file_without_portable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import load_default_whitelist

    project_dir = tmp_path / "project"
    defaults_without_portable = [term for term in load_default_whitelist("CR") if term != "PORTABLE"]
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("\n".join(defaults_without_portable) + "\n", encoding="utf-8")

    whitelist = load_modality_whitelist(project_dir, "CR")
    assert "PORTABLE" not in whitelist


def test_overlay_filter_includes_portable_when_not_on_effective_whitelist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Series View draw path: Portable shown when removed from saved project whitelist."""
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)

    project_dir = tmp_path / "project"
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("AXIAL\nCHEST\n", encoding="utf-8")

    detections = [
        _ocr("Portable"),
        _ocr("DAVIDSON"),
        _ocr("Semi-Upright"),
    ]
    effective_whitelist = load_modality_whitelist(project_dir, "CR")
    annotated = make_annotate_whitelist(effective_whitelist)(detections)
    drawn = texts_for_remove_mode(annotated, OcrRemoveMode.NON_WHITELISTED, PhiMatchMode.STANDARD)
    drawn_texts = [item.text for item in drawn]

    assert "Portable" in drawn_texts
    assert "DAVIDSON" in drawn_texts


def test_overlay_filter_excludes_portable_when_on_whitelist() -> None:
    detections = [_ocr("Portable"), _ocr("DAVIDSON")]
    annotated = make_annotate_whitelist(["PORTABLE", "DAVIDSON"])(detections)
    drawn = texts_for_remove_mode(annotated, OcrRemoveMode.NON_WHITELISTED, PhiMatchMode.STANDARD)
    assert [item.text for item in drawn] == []


def test_thresholds_for_standard_preset() -> None:
    preset = thresholds_for(PhiMatchMode.STANDARD)
    assert preset.whitelist_similarity == 0.85
    assert preset.ner_score == 0.50


def test_lenient_match_mode_table_can_hide_portable() -> None:
    detections = [_ocr("Portable"), _ocr("DAVIDSON")]
    annotated = make_annotate_whitelist(["TABLE", "CHEST"])(detections)
    drawn = texts_for_remove_mode(annotated, OcrRemoveMode.NON_WHITELISTED, PhiMatchMode.LENIENT)
    assert "Portable" not in [item.text for item in drawn]


def test_strict_match_mode_table_does_not_hide_portable() -> None:
    detections = [_ocr("Portable"), _ocr("DAVIDSON")]
    annotated = make_annotate_whitelist(["TABLE", "CHEST"])(detections)
    drawn = texts_for_remove_mode(annotated, OcrRemoveMode.NON_WHITELISTED, PhiMatchMode.STRICT)
    assert "Portable" in [item.text for item in drawn]


def test_load_save_modality_phi_match_mode_round_trip(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    save_modality_phi_match_mode(project_dir, "CR", PhiMatchMode.LENIENT)
    loaded = load_modality_phi_match_mode(project_dir, "CR")
    assert loaded is PhiMatchMode.LENIENT


def test_pipe_runs_stages_in_order() -> None:
    calls: list[str] = []

    def stage_a(texts: list[OCRText]) -> list[OCRText]:
        calls.append("a")
        return texts

    def stage_b(texts: list[OCRText]) -> list[OCRText]:
        calls.append("b")
        return texts

    process = pipe(stage_a, stage_b)
    process([_ocr("X")])
    assert calls == ["a", "b"]
