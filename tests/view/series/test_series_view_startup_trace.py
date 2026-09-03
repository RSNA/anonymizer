"""Assert SeriesView startup load trace order and sizes across synthetic modalities."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydicom import dcmread

from anonymizer.controller.series_io import load_series_frames
from anonymizer.view.series.image import ImageViewer
from anonymizer.view.series.series import SeriesView
from tests.controller.ocr.conftest import assert_dcm_dir
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR
from tests.controller.tseg.fixtures import ensure_synthetic_ct_assets
from tests.controller.tseg.support.synthetic_ct import (
    FALCON_MIN_SLICES,
    build_synthetic_chest_ct_series,
    build_synthetic_wide_ct_series,
)
from tests.view.series.support.layout_probes import pump, settle, wait_for_viewer
from tests.view.series.support.startup_trace import (
    EXPECTED_MODALITIES,
    STARTUP_TRACE_FIXTURES,
    assert_startup_trace,
    build_startup_trace_series,
    parse_series_view_load_trace,
)

DAVIDSON_CXR_SERIES_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "davidson_cxr"

STARTUP_PAINT_PROFILES = {
    "native_ct": ("chest", None),
    "upscale_64": ("tiny", None),
    "downscale_davidson": ("davidson", "committed"),
    "seg_reserved": ("chest_seg", "seg_cache"),
}


def _seed_seg_cache(series_dir: Path, *, num_slices: int = FALCON_MIN_SLICES) -> None:
    import numpy as np
    import SimpleITK as sitk
    from anonymizer.controller.ai.tseg.seg_retention import write_primary_segment_voxels

    cache_dir = series_dir / "0_TS_SEG"
    seg_dir = cache_dir / "seg"
    seg_dir.mkdir(parents=True, exist_ok=True)
    write_primary_segment_voxels(cache_dir, {"brain": 5000})
    array = np.ones((num_slices, 256, 256), dtype=np.uint8)
    sitk.WriteImage(sitk.GetImageFromArray(array), str(seg_dir / "brain.nii.gz"))


def _seed_seg_nii_only(series_dir: Path, *, num_slices: int = FALCON_MIN_SLICES) -> None:
    import numpy as np
    import SimpleITK as sitk

    seg_dir = series_dir / "0_TS_SEG" / "seg"
    seg_dir.mkdir(parents=True, exist_ok=True)
    array = np.ones((num_slices, 256, 256), dtype=np.uint8)
    sitk.WriteImage(sitk.GetImageFromArray(array), str(seg_dir / "liver.nii.gz"))


def _build_paint_profile_series(profile_id: str, tmp_path: Path) -> Path:
    name, kind = STARTUP_PAINT_PROFILES[profile_id]
    if kind == "committed":
        assert_dcm_dir(DAVIDSON_CXR_SERIES_DIR)
        return DAVIDSON_CXR_SERIES_DIR
    if name == "tiny":
        series_dir = build_synthetic_wide_ct_series(
            tmp_path / name,
            num_slices=FALCON_MIN_SLICES,
            rows=64,
            cols=64,
        )
    else:
        series_dir = build_synthetic_chest_ct_series(tmp_path / name, num_slices=FALCON_MIN_SLICES)
    if kind == "seg_cache":
        _seed_seg_cache(series_dir)
    return series_dir


def _open_and_capture_display(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    series_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> tuple[tuple[int, int], tuple[int, int]]:
    loaded = load_series_frames(series_dir)
    native_size = (int(loaded.frames.shape[2]), int(loaded.frames.shape[1]))
    with caplog.at_level(logging.INFO, logger="anonymizer.view.series.series"):
        view = SeriesView(
            tk_root,
            controller=mock_controller,
            series_path=series_dir,
            preloaded=loaded,
        )
        settle(view)
        display_size = view.image_viewer.current_size
        view.destroy()
        pump(tk_root)
    return native_size, display_size


@pytest.mark.parametrize("fixture_id", sorted(STARTUP_TRACE_FIXTURES), ids=sorted(STARTUP_TRACE_FIXTURES))
def test_startup_trace_sequence_and_sizes(
    fixture_id: str,
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_dir, modality = build_startup_trace_series(fixture_id, tmp_path)
    if fixture_id in EXPECTED_MODALITIES:
        assert modality == EXPECTED_MODALITIES[fixture_id]

    native_size, display_size = _open_and_capture_display(tk_root, mock_controller, series_dir, caplog)
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
    )


def test_startup_trace_reserves_segmentation_chrome(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest_seg", num_slices=FALCON_MIN_SLICES)
    _seed_seg_cache(series_dir)
    native_size, display_size = _open_and_capture_display(tk_root, mock_controller, series_dir, caplog)
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
        expect_segmentation_reserved=True,
    )


def test_startup_trace_no_segmentation_reserved_without_seg_dir(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    native_size, display_size = _open_and_capture_display(tk_root, mock_controller, series_dir, caplog)
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
        expect_segmentation_reserved=False,
    )


def test_startup_trace_seg_reserved_from_nii_only(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest_nii", num_slices=FALCON_MIN_SLICES)
    _seed_seg_nii_only(series_dir)
    native_size, display_size = _open_and_capture_display(tk_root, mock_controller, series_dir, caplog)
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
        expect_segmentation_reserved=True,
    )


def test_startup_segmentation_chrome_does_not_refit_image(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest_seg", num_slices=FALCON_MIN_SLICES)
    _seed_seg_cache(series_dir)
    loaded = load_series_frames(series_dir)
    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
        preloaded=loaded,
    )
    wait_for_viewer(view)
    before = view.image_viewer.current_size
    view._load_segmentation_chrome()
    pump(view, steps=40)
    assert view.image_viewer.current_size == before
    view.destroy()
    pump(tk_root)


def test_startup_display_unchanged_after_idle_pump(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
) -> None:
    assert_dcm_dir(DAVIDSON_CXR_SERIES_DIR)
    loaded = load_series_frames(DAVIDSON_CXR_SERIES_DIR)
    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=DAVIDSON_CXR_SERIES_DIR,
        preloaded=loaded,
    )
    wait_for_viewer(view)
    after_startup = view.image_viewer.current_size
    pump(view, steps=80)
    assert view.image_viewer.current_size == after_startup
    view.destroy()
    pump(tk_root)


def test_startup_viewer_ready_after_settle(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
        preloaded=loaded,
    )
    viewer = wait_for_viewer(view)
    assert viewer._startup_complete
    assert viewer.view_matches_actual()
    assert not view._startup_layout
    view.destroy()
    pump(tk_root)


@pytest.mark.parametrize("profile_id", sorted(STARTUP_PAINT_PROFILES), ids=sorted(STARTUP_PAINT_PROFILES))
def test_startup_paints_slice_once(
    profile_id: str,
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_dir = _build_paint_profile_series(profile_id, tmp_path)
    load_counts: list[int] = []
    original_load = ImageViewer.load_and_display_image

    def _counting_load(self, frame_ndx: int) -> None:
        load_counts.append(frame_ndx)
        original_load(self, frame_ndx)

    monkeypatch.setattr(ImageViewer, "load_and_display_image", _counting_load)

    loaded = load_series_frames(series_dir)
    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
        preloaded=loaded,
    )
    settle(view)
    view.destroy()
    pump(tk_root)

    assert load_counts.count(0) == 1, load_counts


def test_startup_trace_seg_chrome_before_deiconify(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    _open_and_capture_display(tk_root, mock_controller, series_dir, caplog)
    steps = [record.step for record in parse_series_view_load_trace(caplog)]
    painted_index = steps.index("startup_painted")
    seg_index = steps.index("seg_chrome")
    deiconify_index = steps.index("deiconify")
    assert painted_index < seg_index < deiconify_index


@pytest.mark.parametrize("asset_key", ["head", "chest", "abdomen"])
def test_startup_trace_committed_phantom_assets(
    asset_key: str,
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    asset_dirs = ensure_synthetic_ct_assets()
    series_dir = asset_dirs[f"synthetic_CT_{asset_key}"]
    modality = str(dcmread(next(series_dir.glob("*.dcm")), stop_before_pixels=True).Modality)
    assert modality == "CT"

    native_size, display_size = _open_and_capture_display(tk_root, mock_controller, series_dir, caplog)
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
    )


def test_startup_display_native_for_standard_ct(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    native_size, display_size = _open_and_capture_display(tk_root, mock_controller, series_dir, caplog)
    assert display_size == native_size
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
    )


def test_startup_display_upscales_small_ct(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_dir = build_synthetic_wide_ct_series(
        tmp_path / "tiny",
        num_slices=FALCON_MIN_SLICES,
        rows=64,
        cols=64,
    )
    native_size, display_size = _open_and_capture_display(tk_root, mock_controller, series_dir, caplog)
    assert native_size == (64, 64)
    assert display_size[0] > native_size[0]
    assert display_size[1] > native_size[1]
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
    )


def test_startup_display_downscales_davidson_cxr(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert_dcm_dir(DAVIDSON_CXR_SERIES_DIR)
    native_size, display_size = _open_and_capture_display(
        tk_root,
        mock_controller,
        DAVIDSON_CXR_SERIES_DIR,
        caplog,
    )
    assert native_size == (2140, 1760)
    assert display_size[0] < native_size[0]
    assert display_size[1] < native_size[1]
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
    )


def test_startup_davidson_paints_once_before_deiconify(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_dcm_dir(DAVIDSON_CXR_SERIES_DIR)
    loaded = load_series_frames(DAVIDSON_CXR_SERIES_DIR)
    load_counts: list[int] = []
    original_load = ImageViewer.load_and_display_image

    def _counting_load(self, frame_ndx: int) -> None:
        load_counts.append(frame_ndx)
        original_load(self, frame_ndx)

    monkeypatch.setattr(ImageViewer, "load_and_display_image", _counting_load)

    with caplog.at_level(logging.INFO, logger="anonymizer.view.series.series"):
        view = SeriesView(
            tk_root,
            controller=mock_controller,
            series_path=DAVIDSON_CXR_SERIES_DIR,
            preloaded=loaded,
        )
        settle(view)
        view.destroy()
        pump(tk_root)

    assert load_counts.count(0) == 1


def test_startup_async_hidden_load_trace(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "async", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    native_size = (int(loaded.frames.shape[2]), int(loaded.frames.shape[1]))
    with caplog.at_level(logging.INFO, logger="anonymizer.view.series.series"):
        view = SeriesView(
            tk_root,
            controller=mock_controller,
            series_path=series_dir,
        )
        wait_for_viewer(view)
        display_size = view.image_viewer.current_size
        view.destroy()
        pump(tk_root)
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
        expect_preloaded=False,
    )


def test_startup_async_load_paints_slice_once(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "async_paint", num_slices=FALCON_MIN_SLICES)
    load_counts: list[int] = []
    original_load = ImageViewer.load_and_display_image

    def _counting_load(self, frame_ndx: int) -> None:
        load_counts.append(frame_ndx)
        original_load(self, frame_ndx)

    monkeypatch.setattr(ImageViewer, "load_and_display_image", _counting_load)

    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
    )
    wait_for_viewer(view)
    view.destroy()
    pump(tk_root)

    assert load_counts.count(0) == 1, load_counts


def test_startup_loading_shell_trace(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SeriesView, "PROGRESS_SLICE_THRESHOLD", 1)
    series_dir = build_synthetic_chest_ct_series(tmp_path / "shell", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    native_size = (int(loaded.frames.shape[2]), int(loaded.frames.shape[1]))
    with caplog.at_level(logging.INFO, logger="anonymizer.view.series.series"):
        view = SeriesView(
            tk_root,
            controller=mock_controller,
            series_path=series_dir,
        )
        wait_for_viewer(view)
        display_size = view.image_viewer.current_size
        view.destroy()
        pump(tk_root)
    assert_startup_trace(
        parse_series_view_load_trace(caplog),
        native_size=native_size,
        expected_display_size=display_size,
        expect_preloaded=False,
    )
