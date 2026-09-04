"""Harmonize dialog is Series View–scoped (no app-wide grab/wait_window)."""

from __future__ import annotations

import contextlib
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydicom import Dataset
from pydicom.uid import generate_uid

from anonymizer.view.ai import harmonize_results as harmonize_mod
from anonymizer.view.ai.harmonize_results import (
    HarmonizeBatchOutcome,
    HarmonizeResultsView,
    HarmonizeSeriesItem,
    get_open_harmonize_view,
    show_harmonize_results_view,
)
from anonymizer.view.series.series import SeriesView

_THEME_PATH = Path(__file__).resolve().parents[3] / "src" / "anonymizer" / "assets" / "themes" / "rsna_theme.json"


@pytest.fixture(scope="module", autouse=True)
def _init_customtkinter_theme() -> None:
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme(str(_THEME_PATH))


@pytest.fixture(autouse=True)
def _clear_harmonize_registry() -> None:
    harmonize_mod._open_harmonize_by_series_key.clear()
    yield
    harmonize_mod._open_harmonize_by_series_key.clear()


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    with contextlib.suppress(tk.TclError):
        root.destroy()


def _series_item(tmp_path: Path, *, series_uid: str | None = None) -> HarmonizeSeriesItem:
    series_dir = tmp_path / "series"
    series_dir.mkdir(parents=True, exist_ok=True)
    ds = Dataset()
    ds.SeriesInstanceUID = series_uid or str(generate_uid())
    ds.StudyInstanceUID = str(generate_uid())
    ds.Modality = "CT"
    ds.SeriesDescription = "CHEST AX"
    ds.StudyDescription = "CHEST CT"
    return HarmonizeSeriesItem.from_dataset(series_dir, ds)


def _open_harmonize(
    tk_root: tk.Tk,
    item: HarmonizeSeriesItem,
    *,
    on_closed=None,
    monkeypatch: pytest.MonkeyPatch,
) -> HarmonizeResultsView:
    monkeypatch.setattr(HarmonizeResultsView, "_start_current_item_worker", lambda self: None)
    grab = MagicMock()
    wait = MagicMock()
    monkeypatch.setattr(HarmonizeResultsView, "grab_set", grab)
    monkeypatch.setattr(tk.Misc, "wait_window", wait)
    view = show_harmonize_results_view(
        tk_root,
        items=[item],
        on_closed=on_closed,
    )
    tk_root.update_idletasks()
    return view, grab, wait


def test_show_harmonize_does_not_grab_or_wait(
    tk_root: tk.Tk,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _series_item(tmp_path)
    view, grab, wait = _open_harmonize(tk_root, item, monkeypatch=monkeypatch)
    grab.assert_not_called()
    wait.assert_not_called()
    assert view.winfo_exists()
    view.destroy()


def test_on_closed_fires_once_on_cancel_while_running(
    tk_root: tk.Tk,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _series_item(tmp_path)
    closed: list[HarmonizeBatchOutcome] = []
    view, _, _ = _open_harmonize(
        tk_root,
        item,
        on_closed=closed.append,
        monkeypatch=monkeypatch,
    )
    assert view._running is True
    view._on_cancel()
    assert closed == []
    assert view.cancelled is True
    status_text = str(view._status_label.cget("text"))
    assert "Cancelling after current step" in status_text

    view._harmonize_work_state.finish(None)
    HarmonizeResultsView._on_harmonize_job_done(view, None, view._harmonize_work_state)

    assert len(closed) == 1
    assert closed[0].cancelled is True
    assert get_open_harmonize_view(str(item.ds.SeriesInstanceUID)) is None


def test_cancel_during_review_closes_immediately(
    tk_root: tk.Tk,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _series_item(tmp_path)
    closed: list[HarmonizeBatchOutcome] = []
    view, _, _ = _open_harmonize(
        tk_root,
        item,
        on_closed=closed.append,
        monkeypatch=monkeypatch,
    )
    view._running = False
    view._on_cancel()
    assert len(closed) == 1
    assert closed[0].cancelled is True


def test_second_open_focuses_existing_without_new_worker(
    tk_root: tk.Tk,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _series_item(tmp_path)
    starts: list[int] = []

    def _start(self) -> None:
        starts.append(1)

    monkeypatch.setattr(HarmonizeResultsView, "_start_current_item_worker", _start)
    first = show_harmonize_results_view(tk_root, items=[item])
    focused: list[object] = []
    monkeypatch.setattr(
        harmonize_mod,
        "focus_harmonize_view",
        lambda view: focused.append(view),
    )
    second = show_harmonize_results_view(tk_root, items=[item])
    assert second is first
    assert starts == [1]
    assert focused == [first]
    first.destroy()


def test_second_open_different_series_focuses_existing(
    tk_root: tk.Tk,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_item = _series_item(tmp_path / "a")
    second_item = _series_item(tmp_path / "b")
    starts: list[int] = []

    def _start(self) -> None:
        starts.append(1)

    monkeypatch.setattr(HarmonizeResultsView, "_start_current_item_worker", _start)
    first = show_harmonize_results_view(tk_root, items=[first_item])
    focused: list[object] = []
    monkeypatch.setattr(
        harmonize_mod,
        "focus_harmonize_view",
        lambda view: focused.append(view),
    )
    second = show_harmonize_results_view(tk_root, items=[second_item])
    assert second is first
    assert starts == [1]
    assert focused == [first]
    first.destroy()


def test_series_view_disables_interaction_while_harmonize_open(
    tk_root: tk.Tk,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _series_item(tmp_path)
    series = SeriesView.__new__(SeriesView)
    series._ds = item.ds
    series._series_path = item.series_path
    series._fonts = None
    series._controller = MagicMock()
    series._controller.anonymizer.model = MagicMock()
    series._harmonize_view = None
    series._series_geometry = object()
    series._face_blur_eligibility_cache = object()
    series._face_blur_eligibility_geometry = object()
    series.harmonize_button = MagicMock()
    series.winfo_exists = lambda: True
    series._destroyed = False
    series._closing = False
    series._harmonize_button_visible = lambda: True
    enabled_states: list[bool] = []
    series._set_series_interaction_enabled = lambda enabled: enabled_states.append(enabled)
    series._refresh_analysis_cache_ui = MagicMock()
    series._refresh_series_processing_status = MagicMock()
    series._on_series_description_updated = MagicMock()

    mock_view = MagicMock()
    mock_view.winfo_exists.return_value = True
    monkeypatch.setattr(
        "anonymizer.view.series.series.harmonize_allowed_for_modality",
        lambda _modality: True,
    )
    monkeypatch.setattr(
        "anonymizer.view.series.series.show_harmonize_results_view",
        lambda *args, **kwargs: mock_view,
    )
    monkeypatch.setattr(
        "anonymizer.view.series.series.get_open_harmonize_view",
        lambda _key: None,
    )
    monkeypatch.setattr(
        "anonymizer.view.series.series.get_any_open_harmonize_view",
        lambda: None,
    )

    SeriesView.harmonize_description_button_clicked(series)
    assert enabled_states == [False]
    assert series._harmonize_view is mock_view

    SeriesView._on_harmonize_closed(series, HarmonizeBatchOutcome(cancelled=True))
    assert enabled_states == [False, True]
    assert series._harmonize_view is None
    series._refresh_analysis_cache_ui.assert_called_once()
    series._refresh_series_processing_status.assert_called_once()


def test_series_view_second_click_focuses_existing(
    tk_root: tk.Tk,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _series_item(tmp_path)
    series = SeriesView.__new__(SeriesView)
    series._ds = item.ds
    series._series_path = item.series_path
    series._fonts = None
    series._controller = MagicMock()
    series._controller.anonymizer.model = MagicMock()
    series.harmonize_button = MagicMock()
    series._set_series_interaction_enabled = MagicMock()
    series._on_series_description_updated = MagicMock()
    series._harmonize_button_visible = lambda: True

    mock_view = MagicMock()
    mock_view.winfo_exists.return_value = True
    series._harmonize_view = mock_view
    focused: list[object] = []
    monkeypatch.setattr(
        "anonymizer.view.series.series.harmonize_allowed_for_modality",
        lambda _modality: True,
    )
    monkeypatch.setattr(
        "anonymizer.view.series.series.focus_harmonize_view",
        lambda view: focused.append(view),
    )

    SeriesView.harmonize_description_button_clicked(series)
    assert focused == [mock_view]
    series._set_series_interaction_enabled.assert_not_called()
