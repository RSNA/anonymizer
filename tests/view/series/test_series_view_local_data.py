"""Local Series View layout tests against developer MRI_TEST fixtures (not run in CI)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import tkinter as tk

from anonymizer.controller.series_io import load_series_frames
from anonymizer.view.series import series as series_mod
from anonymizer.view.series.image import ImageViewer
from anonymizer.view.series.series import SeriesView

pytestmark = pytest.mark.view_dev

_THEME_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "anonymizer" / "assets" / "themes" / "rsna_theme.json"
)

MRI_TEST_STUDY = Path(
    "/Users/michaelevans/Documents/RSNA Anonymizer/MRI_TEST/public/"
    "993241-000003/1.2.826.0.1.3680043.10.474.2.993241.2.87153661778703757233353464"
)
SEGMENTED_SERIES = MRI_TEST_STUDY / "1.2.826.0.1.3680043.10.474.2.993241.2.45986319822060102567882005"
UNSEGMENTED_SERIES = MRI_TEST_STUDY / "1.2.826.0.1.3680043.10.474.2.993241.2.57891753487013526847167725"


@pytest.fixture(scope="module", autouse=True)
def _require_local_study() -> None:
    if not SEGMENTED_SERIES.is_dir() or not UNSEGMENTED_SERIES.is_dir():
        pytest.skip(f"local MRI_TEST study not found under {MRI_TEST_STUDY}")


@pytest.fixture(scope="module", autouse=True)
def _init_customtkinter_theme() -> None:
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme(str(_THEME_PATH))


@pytest.fixture
def tk_root() -> tk.Tk:
    root = tk.Tk()
    root.withdraw()
    yield root
    with contextlib.suppress(tk.TclError):
        root.destroy()


@pytest.fixture(autouse=True)
def _stub_viewer_icon_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    from anonymizer.view.series import image as image_mod
    from PIL import Image

    icon = Image.new("RGB", (28, 28), color=(0, 0, 0))
    monkeypatch.setattr(image_mod.Image, "open", lambda _path: icon)


@pytest.fixture
def mock_controller() -> MagicMock:
    controller = MagicMock()
    controller.get_phi_by_anon_patient_id.return_value = None
    controller.get_series_processing_status.return_value = None
    controller.series_has_face_blur.return_value = False
    controller.series_is_harmonized.return_value = True
    controller.format_series_processing_status.return_value = ""
    return controller


def _pump(root: tk.Misc, *, steps: int = 80) -> None:
    for _ in range(steps):
        root.update_idletasks()
        root.update()


def _open_series(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    series_path: Path,
) -> SeriesView:
    loaded = load_series_frames(series_path)
    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_path,
        preloaded=loaded,
    )
    _pump(tk_root)
    return view


@pytest.mark.parametrize(
    ("series_path", "expect_segmentation"),
    [
        (SEGMENTED_SERIES, True),
        (UNSEGMENTED_SERIES, False),
    ],
    ids=["segmented", "unsegmented"],
)
def test_local_study_player_visible_after_startup(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    series_path: Path,
    expect_segmentation: bool,
) -> None:
    view = _open_series(tk_root, mock_controller, series_path)
    viewer = view.image_viewer
    assert viewer.toggle_button is not None
    assert viewer.player_fits_data_panel()
    layout = viewer._compute_data_panel_layout()
    if panel_h := viewer.data_frame.winfo_height():
        if panel_h >= ImageViewer.DATA_PANEL_MIN_HEIGHT:
            assert layout.histogram_height >= ImageViewer.HISTOGRAM_CANVAS_MIN_HEIGHT
    if expect_segmentation and viewer.data_frame.winfo_height() >= 360:
        assert layout.show_segmentation_buttons
    view.destroy()
    _pump(tk_root)


@pytest.mark.parametrize(
    "series_path",
    [SEGMENTED_SERIES, UNSEGMENTED_SERIES],
    ids=["segmented", "unsegmented"],
)
def test_local_study_player_visible_at_minimum_window_size(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    series_path: Path,
) -> None:
    view = _open_series(tk_root, mock_controller, series_path)
    min_w, min_h = view._minimum_window_size()
    view.geometry(f"{min_w}x{min_h}")
    _pump(tk_root)
    viewer = view.image_viewer
    viewer._sync_data_panel_to_image_height()
    _pump(tk_root, steps=40)
    assert viewer.player_fits_data_panel(), (
        f"player clipped: control bottom="
        f"{viewer.control_frame.winfo_y() + viewer.control_frame.winfo_height()} "
        f"panel={viewer.data_frame.winfo_height()}"
    )
    view.destroy()
    _pump(tk_root)


def test_local_segmented_series_loads_segmentation_buttons(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
) -> None:
    view = _open_series(tk_root, mock_controller, SEGMENTED_SERIES)
    view._load_segmentation_chrome()
    _pump(tk_root, steps=120)
    viewer = view.image_viewer
    assert len(viewer._segmentation_buttons) > 0
    assert viewer.player_fits_data_panel()
    layout = viewer._compute_data_panel_layout()
    if viewer.data_frame.winfo_height() >= 360:
        assert layout.show_segmentation_buttons
        assert layout.histogram_height >= ImageViewer.HISTOGRAM_CANVAS_MIN_HEIGHT
    view.destroy()
    _pump(tk_root)
