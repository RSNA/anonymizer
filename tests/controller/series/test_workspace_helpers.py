"""Unit tests for SeriesWorkspace OCR/head helpers (no Tk)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from pydicom import Dataset

from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import PhiMatchMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrEditContext, OcrRemoveMode
from anonymizer.controller.ai.tseg.head_signals import CachedRegionSignal, MetadataSignal
from anonymizer.controller.jobs.work_state import WorkState
from anonymizer.controller.series.series_overlay import (
    NerEvidence,
    OCRText,
    OcrEvidence,
    UserRectangle,
    WhitelistEvidence,
)
from anonymizer.controller.series.workspace import (
    SeriesWorkspace,
    exclude_rects_fingerprint,
    filter_series_view_ocr_overlay,
)


def _box(
    text: str,
    *,
    x1: int = 0,
    y1: int = 0,
    x2: int = 40,
    y2: int = 20,
    wl_score: float | None = None,
    ner_score: float | None = None,
) -> OCRText:
    return OCRText(
        text=text,
        top_left=(x1, y1),
        bottom_right=(x2, y2),
        ocr=OcrEvidence(prob=0.9),
        whitelist=WhitelistEvidence(term="X" if wl_score else None, score=wl_score),
        ner=NerEvidence(label="NAME" if ner_score else None, score=ner_score),
    )


def test_filter_series_view_ocr_overlay_phi_only_and_non_whitelisted() -> None:
    boxes = [
        _box("PORTABLE", wl_score=0.95),
        _box("DAVIDSON", ner_score=0.9),
        _box("AXIAL", wl_score=0.2, ner_score=0.2),
    ]
    phi = filter_series_view_ocr_overlay(
        boxes, remove_mode=OcrRemoveMode.PHI_ONLY, match_mode=PhiMatchMode.STANDARD
    )
    assert [t.text for t in phi] == ["DAVIDSON"]
    non_wl = filter_series_view_ocr_overlay(
        boxes, remove_mode=OcrRemoveMode.NON_WHITELISTED, match_mode=PhiMatchMode.STANDARD
    )
    assert [t.text for t in non_wl] == ["DAVIDSON", "AXIAL"]


def test_filter_series_view_ocr_overlay_exclude_rect() -> None:
    boxes = [
        _box("INSIDE", x1=2, y1=2, x2=8, y2=8, ner_score=0.9),
        _box("OUTSIDE", x1=50, y1=50, x2=60, y2=60, ner_score=0.9),
    ]
    exclude = [UserRectangle(top_left=(0, 0), bottom_right=(20, 20))]
    kept = filter_series_view_ocr_overlay(
        boxes,
        remove_mode=OcrRemoveMode.PHI_ONLY,
        match_mode=PhiMatchMode.STANDARD,
        exclude_rects=exclude,
    )
    assert [t.text for t in kept] == ["OUTSIDE"]


def test_exclude_rects_fingerprint_sorts_and_rounds() -> None:
    rects = [
        {"x1": 0.20004, "y1": 0.1, "x2": 0.3, "y2": 0.4},
        {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2},
    ]
    fp = exclude_rects_fingerprint(rects)
    assert fp[0] == (0.1, 0.1, 0.2, 0.2)
    assert fp[1][0] == 0.2
    assert exclude_rects_fingerprint(list(reversed(rects))) == fp


def test_is_head_series_uses_cache_then_metadata(tmp_path: Path) -> None:
    series_dir = tmp_path / "ser"
    series_dir.mkdir()
    ws = SeriesWorkspace(MagicMock(), series_dir)
    ds = Dataset()
    with patch(
        "anonymizer.controller.series.workspace.cached_region_signal",
        return_value=CachedRegionSignal.HEAD,
    ):
        assert ws.is_head_series(ds) is True
    with (
        patch(
            "anonymizer.controller.series.workspace.cached_region_signal",
            return_value=CachedRegionSignal.NON_HEAD,
        ),
        patch(
            "anonymizer.controller.series.workspace.metadata_signal",
            return_value=MetadataSignal.HEAD,
        ),
    ):
        assert ws.is_head_series(ds) is True
    with (
        patch(
            "anonymizer.controller.series.workspace.cached_region_signal",
            return_value=CachedRegionSignal.UNAVAILABLE,
        ),
        patch(
            "anonymizer.controller.series.workspace.metadata_signal",
            return_value=MetadataSignal.AMBIGUOUS,
        ),
    ):
        assert ws.is_head_series(ds) is False


def test_prepare_ocr_job_frame_sets_index_series_resets(tmp_path: Path) -> None:
    series_dir = tmp_path / "ser"
    series_dir.mkdir()
    project = MagicMock()
    project.model.storage_dir = tmp_path
    ws = SeriesWorkspace(project, series_dir)
    ds = Dataset()
    ds.SeriesInstanceUID = "1.2.3"
    frames = np.zeros((2, 4, 4), dtype=np.uint8)
    paths = (tmp_path / "a.dcm", tmp_path / "b.dcm")
    work = WorkState()

    opts = ws.prepare_ocr_job(
        work,
        ds=ds,
        frames=frames,
        slice_paths=paths,
        default_window=(0.0, 1.0),
        single_frame=False,
        edit_context=OcrEditContext.FRAME,
        frame_index=1,
        ocr_source_images=None,
    )
    assert work.frame_index == 1
    assert opts.edit_context is OcrEditContext.FRAME
    assert opts.project_dir == tmp_path

    opts2 = ws.prepare_ocr_job(
        work,
        ds=ds,
        frames=frames,
        slice_paths=paths,
        default_window=(0.0, 1.0),
        single_frame=False,
        edit_context=OcrEditContext.SERIES,
        frame_index=1,
        ocr_source_images=None,
    )
    assert work.frame_index == 0
    assert opts2.edit_context is OcrEditContext.SERIES


def test_remove_ocr_from_frame_excluded_all_returns_none(tmp_path: Path) -> None:
    ws = SeriesWorkspace(MagicMock(), tmp_path / "ser")
    texts = [_box("PHI", x1=1, y1=1, x2=5, y2=5, ner_score=0.9)]
    exclude = [UserRectangle(top_left=(0, 0), bottom_right=(10, 10))]
    raw = np.ones((20, 20), dtype=np.uint8)
    windowed = np.zeros((20, 20, 3), dtype=np.uint8)
    assert (
        ws.remove_ocr_from_frame(
            raw_frame=raw,
            windowed_frame=windowed,
            ocr_texts=texts,
            exclude_rects=exclude,
            removal_mode=MagicMock(),
        )
        is None
    )
    assert texts == []


def test_remove_ocr_from_frame_success_clears_boxes(tmp_path: Path) -> None:
    ws = SeriesWorkspace(MagicMock(), tmp_path / "ser")
    texts = [_box("NAME", ner_score=0.9)]
    raw = np.ones((20, 20), dtype=np.uint8)
    windowed = np.zeros((20, 20, 3), dtype=np.uint8)
    new_frame = np.zeros_like(raw)
    with patch(
        "anonymizer.controller.series.workspace.remove_ocr_text_from_frame",
        return_value=new_frame,
    ) as remover:
        result = ws.remove_ocr_from_frame(
            raw_frame=raw,
            windowed_frame=windowed,
            ocr_texts=texts,
            exclude_rects=None,
            removal_mode=MagicMock(),
        )
    assert result is not None
    assert result.frame is new_frame
    assert result.removed_labels == ("NAME",)
    assert texts == []
    remover.assert_called_once()
