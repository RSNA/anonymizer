"""Tests for shared OCR noise filtering and batch removal modes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from anonymizer.controller.ai.ocr_whitelist_match import (
    OcrWhitelistMatchMode,
    OcrWhitelistMatchSettings,
    resolve_whitelist_match,
)
from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    _apply_frame_removal_mask,
    _map_ocr_texts_to_source_coordinates,
    blackout_ocr_text_areas,
    detect_text,
    filter_ocr_detections,
    filter_ocr_whitelist_only,
    load_modality_whitelist,
    remove_pixel_phi,
)
from anonymizer.controller.ai_batch_process import format_remove_pixel_phi_instance_detail
from anonymizer.controller.series_overlay import OCRText
from anonymizer.utils.memory import MemorySnapshot, format_memory_snapshot_label


def _ocr(text: str, *, prob: float = 0.9, box: tuple[int, int, int, int] = (0, 0, 20, 20)) -> OCRText:
    x1, y1, x2, y2 = box
    return OCRText(text=text, top_left=(x1, y1), bottom_right=(x2, y2), prob=prob)


def test_filter_ocr_detections_rejects_short_numeric_small_box() -> None:
    detections = [_ocr("008", prob=0.95, box=(0, 0, 28, 14))]
    assert filter_ocr_detections(detections) == []


def test_filter_ocr_detections_keeps_short_numeric_large_box() -> None:
    detections = [_ocr("2024", prob=0.95, box=(0, 0, 40, 20))]
    assert len(filter_ocr_detections(detections)) == 1


def test_filter_ocr_detections_rejects_tiny_area_per_character() -> None:
    detections = [_ocr("008", prob=0.95, box=(0, 0, 10, 10))]
    assert filter_ocr_detections(detections) == []


def test_filter_ocr_detections_rejects_noise_hits() -> None:
    detections = [
        _ocr(";", prob=0.95),
        _ocr("8", prob=0.95),
        _ocr("g", prob=0.95),
        _ocr(":", prob=0.95),
        _ocr("x", prob=0.4),
    ]
    assert filter_ocr_detections(detections) == []


def test_filter_ocr_detections_keeps_alphanumeric_above_threshold() -> None:
    detections = [_ocr("SMITH^JOHN", prob=0.92), _ocr("AXIAL", prob=0.88)]
    assert len(filter_ocr_detections(detections)) == 2


def test_filter_ocr_detections_whitelist_fuzzy_match() -> None:
    detections = [_ocr("AXIAL", prob=0.9), _ocr("PATIENT NAME", prob=0.9)]
    filtered = filter_ocr_detections(detections, whitelist=["AXIL"])
    assert [item.text for item in filtered] == ["PATIENT NAME"]


def test_filter_ocr_whitelist_only_table_does_not_match_portable() -> None:
    """TABLE fuzzy-similarity to PORTABLE must not hide Portable when PORTABLE is removed."""
    detections = [_ocr("Portable"), _ocr("DAVIDSON")]
    filtered = filter_ocr_whitelist_only(detections, whitelist=["TABLE", "CHEST"])
    assert [item.text for item in filtered] == ["Portable", "DAVIDSON"]


def test_filter_ocr_detections_whitelist_filters_portable(caplog) -> None:
    detections = [_ocr("Portable", prob=0.9), _ocr("DAVIDSON", prob=0.9)]
    import logging

    with caplog.at_level(logging.INFO, logger="anonymizer.controller.ai.remove_pixel_phi"):
        filtered = filter_ocr_detections(detections, whitelist=["PORTABLE"])
    assert [item.text for item in filtered] == ["DAVIDSON"]
    assert "OCR whitelist hid 'Portable'" in caplog.text


def test_filter_ocr_detections_empty_whitelist_keeps_portable() -> None:
    detections = [_ocr("Portable", prob=0.9), _ocr("DAVIDSON", prob=0.9)]
    filtered = filter_ocr_detections(detections, whitelist=[])
    assert [item.text for item in filtered] == ["Portable", "DAVIDSON"]


def test_load_modality_whitelist_cr_includes_portable(monkeypatch: pytest.MonkeyPatch) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    whitelist = load_modality_whitelist(None, "CR")
    assert "PORTABLE" in whitelist


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
    from anonymizer.utils.storage import load_default_whitelist

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


@patch("anonymizer.controller.ai.remove_pixel_phi._easyocr_readtext")
def test_detect_text_applies_noise_filter(mock_readtext: MagicMock) -> None:
    mock_readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], ";", 0.95),
        ([(0, 0), (40, 0), (40, 20), (0, 20)], "SMITH", 0.92),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    results = detect_text(pixels, MagicMock())
    assert results is not None
    assert [item.text for item in results] == ["SMITH"]


@patch("anonymizer.controller.ai.remove_pixel_phi._easyocr_readtext")
def test_detect_text_ct_drops_single_char_spurious(mock_readtext: MagicMock) -> None:
    mock_readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "0", 0.95),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "U", 0.92),
        ([(0, 0), (80, 0), (80, 20), (0, 20)], "SMITH", 0.92),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    results = detect_text(pixels, MagicMock(), modality="CT", apply_noise_filter=False)
    assert results is not None
    assert [item.text for item in results] == ["SMITH"]


@patch("anonymizer.controller.ai.remove_pixel_phi._easyocr_readtext")
def test_detect_text_ct_drops_short_numeric_and_symbol_noise(mock_readtext: MagicMock) -> None:
    """Series View CT detect (no noise filter) still drops slice/HU-style false positives."""
    mock_readtext.return_value = [
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
    results = detect_text(pixels, MagicMock(), modality="CT", apply_noise_filter=False)
    assert results is not None
    assert [item.text for item in results] == ["01.09.2012", "SMITH", "12345"]


@patch("anonymizer.controller.ai.remove_pixel_phi._easyocr_readtext")
def test_detect_text_us_keeps_single_char_detections(mock_readtext: MagicMock) -> None:
    """US behavior unchanged: single-character hits are not dropped by CT veracity filter."""
    mock_readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "0", 0.95),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "U", 0.92),
        ([(0, 0), (80, 0), (80, 20), (0, 20)], "SMITH", 0.92),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    results = detect_text(pixels, MagicMock(), modality="US", apply_noise_filter=False)
    assert results is not None
    assert {item.text for item in results} == {"0", "U", "SMITH"}


@patch("anonymizer.controller.ai.remove_pixel_phi._easyocr_readtext")
def test_detect_text_us_keeps_short_numeric_without_ct_filter(mock_readtext: MagicMock) -> None:
    mock_readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "64", 0.95),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "9 <", 0.91),
        ([(0, 0), (80, 0), (80, 20), (0, 20)], "SMITH", 0.92),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    results = detect_text(pixels, MagicMock(), modality="US", apply_noise_filter=False)
    assert results is not None
    assert [item.text for item in results] == ["64", "9 <", "SMITH"]


@patch("anonymizer.controller.ai.remove_pixel_phi.dcmread")
@patch("anonymizer.controller.ai.remove_pixel_phi._easyocr_readtext")
def test_remove_pixel_phi_all_noise_is_no_op(
    mock_readtext: MagicMock,
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

    mock_readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], ";", 0.95),
        ([(0, 0), (20, 0), (20, 20), (0, 20)], "8", 0.95),
    ]

    modified, texts, pixels_changed = remove_pixel_phi(Path("/tmp/test.dcm"), MagicMock(), whitelist=[])
    assert modified is False
    assert texts == []
    assert pixels_changed == 0
    ds.save_as.assert_not_called()


def test_blackout_ocr_text_areas_zeros_bounding_boxes() -> None:
    frame = np.full((8, 8), 100, dtype=np.uint8)
    texts = [OCRText(text="PHI", top_left=(2, 2), bottom_right=(5, 5), prob=0.9)]
    blackout_ocr_text_areas(frame, texts)
    assert frame[2:5, 2:5].max() == 0
    assert frame[0, 0] == 100


def test_map_ocr_texts_to_source_coordinates_removes_border() -> None:
    texts = [OCRText(text="PHI", top_left=(22, 22), bottom_right=(42, 42), prob=0.9)]
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


@patch("anonymizer.controller.ai.remove_pixel_phi.inpaint")
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
    assert "blacked out" in detail.lower()
    assert "PHI" in detail
    assert "412 px" in detail


def test_format_memory_snapshot_label_available_only() -> None:
    snapshot = MemorySnapshot(rss_mb=3000, available_mb=12800, total_mb=32768, percent_used=60)
    label = format_memory_snapshot_label(snapshot)
    assert "12.5 GB" in label
    assert "RSS" not in label
    assert "total" not in label.lower()


def test_series_view_display_filter_hides_whitelist_only_not_noise() -> None:
    """Overlay display must not re-apply OCR noise heuristics after detect-only."""
    detections = [
        _ocr("LEFT", box=(10, 10, 60, 30)),
        _ocr("CLIP", box=(70, 10, 120, 30)),
        _ocr("9", box=(130, 10, 150, 30)),
        _ocr("23889858", box=(160, 10, 260, 30)),
    ]
    us_wl = ["LEFT", "CLIP"]
    noise_filtered = [t.text for t in filter_ocr_detections(detections, whitelist=us_wl)]
    display_filtered = [t.text for t in filter_ocr_whitelist_only(detections, whitelist=us_wl)]

    assert "LEFT" not in display_filtered
    assert "CLIP" not in display_filtered
    assert "9" in display_filtered
    assert "23889858" in display_filtered
    assert "9" not in noise_filtered


def test_load_modality_whitelist_project_file_without_portable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    from anonymizer.utils.storage import load_default_whitelist

    project_dir = tmp_path / "project"
    defaults_without_portable = [term for term in load_default_whitelist("CR") if term != "PORTABLE"]
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("\n".join(defaults_without_portable) + "\n", encoding="utf-8")

    whitelist = load_modality_whitelist(project_dir, "CR")
    assert "PORTABLE" not in whitelist


def test_overlay_filter_includes_portable_when_defaults_omit_portable_and_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DX defaults without PORTABLE/PORT must still draw Portable (TABLE must not fuzzy-match)."""
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    from anonymizer.utils.storage import load_default_whitelist

    project_dir = tmp_path / "project"
    defaults_without_portable = [
        term for term in load_default_whitelist("CR") if term not in ("PORTABLE", "PORT")
    ]
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("\n".join(defaults_without_portable) + "\n", encoding="utf-8")

    detections = [_ocr("Portable"), _ocr("DAVIDSON")]
    effective_whitelist = load_modality_whitelist(project_dir, "CR")
    drawn = filter_ocr_whitelist_only(detections, whitelist=effective_whitelist)
    assert "Portable" in [item.text for item in drawn]


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
    # Saved project whitelist without PORTABLE or PORT (avoids fuzzy match on PORT).
    project_whitelist.write_text("AXIAL\nCHEST\n", encoding="utf-8")

    detections = [
        _ocr("Portable"),
        _ocr("DAVIDSON"),
        _ocr("Semi-Upright"),
    ]
    effective_whitelist = load_modality_whitelist(project_dir, "CR")
    drawn = filter_ocr_whitelist_only(detections, whitelist=effective_whitelist)
    drawn_texts = [item.text for item in drawn]

    assert "Portable" in drawn_texts
    assert "DAVIDSON" in drawn_texts


def test_overlay_filter_excludes_portable_when_on_whitelist() -> None:
    detections = [_ocr("Portable"), _ocr("DAVIDSON")]
    drawn = filter_ocr_whitelist_only(detections, whitelist=["PORTABLE", "DAVIDSON"])
    assert [item.text for item in drawn] == []


def test_resolve_whitelist_match_standard_preset() -> None:
    settings = OcrWhitelistMatchSettings(match_mode=OcrWhitelistMatchMode.STANDARD)
    similarity, length_ratio = resolve_whitelist_match(settings)
    assert similarity == 0.75
    assert length_ratio == 0.70


def test_resolve_whitelist_match_custom_preset() -> None:
    settings = OcrWhitelistMatchSettings(
        match_mode=OcrWhitelistMatchMode.CUSTOM,
        similarity=0.82,
        min_length_ratio=0.65,
    )
    similarity, length_ratio = resolve_whitelist_match(settings)
    assert similarity == 0.82
    assert length_ratio == 0.65


def test_lenient_match_mode_table_can_hide_portable() -> None:
    detections = [_ocr("Portable"), _ocr("DAVIDSON")]
    settings = OcrWhitelistMatchSettings(match_mode=OcrWhitelistMatchMode.LENIENT)
    drawn = filter_ocr_whitelist_only(
        detections,
        whitelist=["TABLE", "CHEST"],
        whitelist_match_settings=settings,
    )
    assert "Portable" not in [item.text for item in drawn]


def test_strict_match_mode_table_does_not_hide_portable() -> None:
    detections = [_ocr("Portable"), _ocr("DAVIDSON")]
    settings = OcrWhitelistMatchSettings(match_mode=OcrWhitelistMatchMode.STRICT)
    drawn = filter_ocr_whitelist_only(
        detections,
        whitelist=["TABLE", "CHEST"],
        whitelist_match_settings=settings,
    )
    assert "Portable" in [item.text for item in drawn]


def test_load_save_modality_whitelist_match_settings_round_trip(tmp_path: Path) -> None:
    from anonymizer.utils.storage import (
        load_modality_whitelist_match_settings,
        save_modality_whitelist_match_settings,
    )

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    settings = OcrWhitelistMatchSettings(
        match_mode=OcrWhitelistMatchMode.CUSTOM,
        similarity=0.88,
        min_length_ratio=0.75,
    )
    save_modality_whitelist_match_settings(project_dir, "CR", settings)
    loaded = load_modality_whitelist_match_settings(project_dir, "CR")
    assert loaded.match_mode == OcrWhitelistMatchMode.CUSTOM
    assert loaded.similarity == pytest.approx(0.88)
    assert loaded.min_length_ratio == pytest.approx(0.75)

