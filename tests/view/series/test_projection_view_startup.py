"""ProjectionView startup: hidden build, single populate, then show."""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from anonymizer.controller.phi_io import PHI_IndexRecord
from anonymizer.view.project.dataset import DatasetView
from anonymizer.view.series.projection import ProjectionView, series_paths_for_phi_records
from tests.controller.tseg.support.synthetic_ct import FALCON_MIN_SLICES, build_synthetic_chest_ct_series
from tests.view.series.support.layout_probes import pump
from tests.view.series.support.projection_startup_trace import (
    assert_projection_startup_trace,
    parse_projection_view_startup_trace,
)

PATIENT_ID = "anon-patient"
STUDY_UID = "study-uid-1"


def _study_record() -> PHI_IndexRecord:
    return PHI_IndexRecord(
        anon_patient_id=PATIENT_ID,
        anon_patient_name=PATIENT_ID,
        phi_patient_name="Doe^Jane",
        phi_patient_id="P1",
        date_offset=0,
        phi_study_date="20200101",
        anon_accession="A1",
        phi_accession="ACC1",
        anon_study_uid=STUDY_UID,
        phi_study_uid="phi-study-1",
        study_description="Chest",
        num_series=2,
        num_instances=20,
    )


def _build_projection_fixture(tmp_path: Path) -> tuple[Path, list[PHI_IndexRecord]]:
    base_dir = tmp_path / "images"
    study_dir = base_dir / PATIENT_ID / STUDY_UID
    build_synthetic_chest_ct_series(study_dir / "series-z", num_slices=FALCON_MIN_SLICES)
    build_synthetic_chest_ct_series(study_dir / "series-a", num_slices=FALCON_MIN_SLICES)
    return base_dir, [_study_record()]


def _open_projection_view(
    tk_root,
    mock_controller: MagicMock,
    base_dir: Path,
    phi_records: list[PHI_IndexRecord],
    caplog: pytest.LogCaptureFixture | None = None,
) -> ProjectionView:
    log_ctx = (
        caplog.at_level(logging.INFO, logger="anonymizer.view.series.projection")
        if caplog is not None
        else contextlib.nullcontext()
    )
    with log_ctx:
        view = ProjectionView(
            tk_root,
            controller=mock_controller,
            base_dir=base_dir,
            phi_records=phi_records,
        )
        pump(view, steps=20)
    return view


def test_series_paths_are_sorted(tmp_path: Path) -> None:
    base_dir, phi_records = _build_projection_fixture(tmp_path)
    paths = series_paths_for_phi_records(base_dir, phi_records)
    assert [path.name for path in paths] == ["series-a", "series-z"]


def test_projection_view_startup_trace(
    tk_root,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    base_dir, phi_records = _build_projection_fixture(tmp_path)
    view = _open_projection_view(tk_root, mock_controller, base_dir, phi_records, caplog)
    assert_projection_startup_trace(parse_projection_view_startup_trace(caplog))
    view.destroy()
    pump(tk_root)


def test_projection_view_populates_while_hidden(
    tk_root,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir, phi_records = _build_projection_fixture(tmp_path)
    visible_during_populate: list[int] = []
    original = ProjectionView.generate_combined_image

    def _capture_visibility(self, series_path: Path):
        visible_during_populate.append(self.winfo_viewable())
        return original(self, series_path)

    monkeypatch.setattr(ProjectionView, "generate_combined_image", _capture_visibility)

    view = ProjectionView(
        tk_root,
        controller=mock_controller,
        base_dir=base_dir,
        phi_records=phi_records,
    )
    pump(view, steps=20)

    assert visible_during_populate
    assert all(value == 0 for value in visible_during_populate)
    assert view.winfo_viewable()
    view.destroy()
    pump(tk_root)


def test_projection_view_populates_once_on_open(
    tk_root,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir, phi_records = _build_projection_fixture(tmp_path)
    populate_calls: list[int] = []
    original = ProjectionView._populate_px_frame

    def _count_populate(self) -> None:
        populate_calls.append(self._page_number)
        original(self)

    monkeypatch.setattr(ProjectionView, "_populate_px_frame", _count_populate)

    view = ProjectionView(
        tk_root,
        controller=mock_controller,
        base_dir=base_dir,
        phi_records=phi_records,
    )
    pump(view, steps=20)

    assert populate_calls == [1]
    view.destroy()
    pump(tk_root)


def test_projection_view_deiconify_after_populate(
    tk_root,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir, phi_records = _build_projection_fixture(tmp_path)
    events: list[str] = []
    original_populate = ProjectionView._populate_px_frame
    original_deiconify = ProjectionView.deiconify

    def _track_populate(self) -> None:
        events.append("populate")
        original_populate(self)

    def _track_deiconify(self) -> None:
        events.append("deiconify")
        original_deiconify(self)

    monkeypatch.setattr(ProjectionView, "_populate_px_frame", _track_populate)
    monkeypatch.setattr(ProjectionView, "deiconify", _track_deiconify)

    view = ProjectionView(
        tk_root,
        controller=mock_controller,
        base_dir=base_dir,
        phi_records=phi_records,
    )
    pump(view, steps=20)

    populate_index = events.index("populate")
    deiconify_index = events.index("deiconify")
    assert populate_index < deiconify_index
    view.destroy()
    pump(tk_root)


def test_dataset_open_projection_view_opens_hidden_then_visible(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
) -> None:
    base_dir, phi_records = _build_projection_fixture(tmp_path)
    mock_controller.model.images_dir.return_value = base_dir

    parent = tk.Frame(tk_root)
    parent._projection_views = {}
    parent._projection_open_in_progress = False
    parent._controller = mock_controller
    parent._fonts = None
    parent._projection_view_for = lambda study_uids: DatasetView._projection_view_for(parent, study_uids)
    parent._forget_projection_view = lambda study_uids, _event=None: DatasetView._forget_projection_view(
        parent, study_uids, _event
    )

    DatasetView._open_projection_view(parent, phi_records)

    view = parent._projection_views[(STUDY_UID,)]
    assert view.winfo_viewable()
    assert len(view._pv_frame.winfo_children()) > 0
    view.destroy()
    pump(tk_root)
