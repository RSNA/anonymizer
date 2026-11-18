"""Unit tests for SeriesWorkspace.save_series_view_edits (no Tk)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from pydicom import Dataset

from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import PhiMatchMode
from anonymizer.controller.series.workspace import (
    SeriesViewSaveRequest,
    SeriesWorkspace,
    exclude_rects_fingerprint,
)


def _request(
    tmp_path: Path,
    *,
    frames: np.ndarray | None,
    pixel_dirty: bool,
    exclude_dirty: bool = False,
    exclude_rects: list[dict] | None = None,
    match_mode: PhiMatchMode | None = None,
    ocr_transcript: dict[int, list[str]] | None = None,
) -> SeriesViewSaveRequest:
    ds = Dataset()
    ds.Modality = "CT"
    ds.SeriesInstanceUID = "1.2.3.4"
    return SeriesViewSaveRequest(
        series_path=tmp_path / "series",
        frames=frames,
        dataset=ds,
        slice_paths=(tmp_path / "a.dcm",),
        project_dir=tmp_path,
        anon_model=MagicMock(),
        pixel_dirty=pixel_dirty,
        exclude_dirty=exclude_dirty,
        exclude_rects_normalized=list(exclude_rects or []),
        whitelist_items=None,
        match_mode=match_mode,
        texts_by_frame={},
        ocr_transcript_by_frame=ocr_transcript or {},
    )


def test_save_pixel_dirty_missing_frames_fails(tmp_path: Path) -> None:
    (tmp_path / "series").mkdir()
    ws = SeriesWorkspace(MagicMock(), tmp_path / "series")
    result = ws.save_series_view_edits(_request(tmp_path, frames=None, pixel_dirty=True))
    assert result.ok is False
    assert result.should_close is False
    assert result.error_message


def test_save_pixel_dirty_save_frames_false(tmp_path: Path) -> None:
    (tmp_path / "series").mkdir()
    ws = SeriesWorkspace(MagicMock(), tmp_path / "series")
    frames = np.zeros((1, 8, 8), dtype=np.float32)
    with patch(
        "anonymizer.controller.series.workspace.save_series_frames",
        return_value=False,
    ):
        result = ws.save_series_view_edits(_request(tmp_path, frames=frames, pixel_dirty=True))
    assert result.ok is False
    assert result.should_close is False


def test_save_pixel_success_closes_and_invalidates(tmp_path: Path) -> None:
    (tmp_path / "series").mkdir()
    ws = SeriesWorkspace(MagicMock(), tmp_path / "series")
    frames = np.zeros((1, 8, 8), dtype=np.float32)
    with (
        patch(
            "anonymizer.controller.series.workspace.save_series_frames",
            return_value=True,
        ),
        patch(
            "anonymizer.controller.series.workspace.invalidate_projection_cache"
        ) as invalidate,
        patch(
            "anonymizer.controller.series.workspace._promote_ocr_report_note",
            return_value=("", False),
        ),
    ):
        result = ws.save_series_view_edits(_request(tmp_path, frames=frames, pixel_dirty=True))
    assert result.ok is True
    assert result.should_close is True
    invalidate.assert_called_once()


def test_save_match_mode_persisted(tmp_path: Path) -> None:
    (tmp_path / "series").mkdir()
    ws = SeriesWorkspace(MagicMock(), tmp_path / "series")
    with patch(
        "anonymizer.controller.series.workspace.save_modality_phi_match_mode",
        return_value=tmp_path / "mode.json",
    ) as save_mode:
        result = ws.save_series_view_edits(
            _request(
                tmp_path,
                frames=None,
                pixel_dirty=False,
                match_mode=PhiMatchMode.LENIENT,
            )
        )
    assert result.ok is True
    save_mode.assert_called_once()
    assert save_mode.call_args.args[2] is PhiMatchMode.LENIENT


def test_save_cleared_exclude_rects_note(tmp_path: Path) -> None:
    (tmp_path / "series").mkdir()
    ws = SeriesWorkspace(MagicMock(), tmp_path / "series")
    with patch(
        "anonymizer.controller.series.workspace.save_project_exclude_rects"
    ) as save_excl:
        result = ws.save_series_view_edits(
            _request(
                tmp_path,
                frames=None,
                pixel_dirty=False,
                exclude_dirty=True,
                exclude_rects=[],
            )
        )
    assert result.ok is True
    assert "cleared" in result.exclude_note.lower()
    assert result.saved_exclude_fingerprint == ()
    save_excl.assert_called_once()
    assert exclude_rects_fingerprint([]) == ()


def test_save_ocr_report_sr_note(tmp_path: Path) -> None:
    (tmp_path / "series").mkdir()
    ws = SeriesWorkspace(MagicMock(), tmp_path / "series")
    frames = np.zeros((1, 8, 8), dtype=np.float32)
    with (
        patch(
            "anonymizer.controller.series.workspace.save_series_frames",
            return_value=True,
        ),
        patch("anonymizer.controller.series.workspace.invalidate_projection_cache"),
        patch(
            "anonymizer.controller.series.workspace._promote_ocr_report_note",
            return_value=(" — Basic Text SR written for research use", True),
        ),
    ):
        result = ws.save_series_view_edits(
            _request(
                tmp_path,
                frames=frames,
                pixel_dirty=True,
                ocr_transcript={0: ["line"]},
            )
        )
    assert result.ok is True
    assert "Basic Text SR" in result.ocr_sr_note
