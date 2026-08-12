"""Tests for shared OCR noise filtering and batch removal modes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from anonymizer.controller.ai_batch_process import format_remove_pixel_phi_instance_detail
from anonymizer.controller.remove_pixel_phi import (
    OCRText,
    PixelPhiRemovalMode,
    _apply_frame_removal_mask,
    _map_ocr_texts_to_source_coordinates,
    blackout_ocr_text_areas,
    detect_text,
    filter_ocr_detections,
    load_modality_whitelist,
    remove_pixel_phi,
)
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


def test_filter_ocr_detections_whitelist_filters_portable(caplog) -> None:
    detections = [_ocr("Portable", prob=0.9), _ocr("DAVIDSON", prob=0.9)]
    import logging

    with caplog.at_level(logging.DEBUG, logger="anonymizer.controller.remove_pixel_phi"):
        filtered = filter_ocr_detections(detections, whitelist=["PORTABLE"])
    assert [item.text for item in filtered] == ["DAVIDSON"]
    assert "OCR whitelist filtered 1 detection(s): ['Portable']" in caplog.text


def test_filter_ocr_detections_empty_whitelist_keeps_portable() -> None:
    detections = [_ocr("Portable", prob=0.9), _ocr("DAVIDSON", prob=0.9)]
    filtered = filter_ocr_detections(detections, whitelist=[])
    assert [item.text for item in filtered] == ["Portable", "DAVIDSON"]


def test_load_modality_whitelist_cr_includes_portable(monkeypatch: pytest.MonkeyPatch) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    whitelist = load_modality_whitelist(None, "CR")
    assert "PORTABLE" in whitelist


def test_load_modality_whitelist_merges_project_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    project_dir = tmp_path / "project"
    project_whitelist = project_dir / "whitelists" / "CR.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("CUSTOMTERM\n", encoding="utf-8")

    whitelist = load_modality_whitelist(project_dir, "CR")
    assert "PORTABLE" in whitelist
    assert "CUSTOMTERM" in whitelist


@patch("anonymizer.controller.remove_pixel_phi._easyocr_readtext")
def test_detect_text_applies_noise_filter(mock_readtext: MagicMock) -> None:
    mock_readtext.return_value = [
        ([(0, 0), (20, 0), (20, 20), (0, 20)], ";", 0.95),
        ([(0, 0), (40, 0), (40, 20), (0, 20)], "SMITH", 0.92),
    ]
    pixels = np.zeros((64, 64), dtype=np.uint8)
    results = detect_text(pixels, MagicMock())
    assert results is not None
    assert [item.text for item in results] == ["SMITH"]


@patch("anonymizer.controller.remove_pixel_phi.dcmread")
@patch("anonymizer.controller.remove_pixel_phi._easyocr_readtext")
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


@patch("anonymizer.controller.remove_pixel_phi.inpaint")
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
