"""Tests for HarmonizeResultsView batch header helpers."""

from __future__ import annotations

from pydicom import Dataset

from anonymizer.controller.harmonize import HarmonizeProgress
from anonymizer.controller.tseg.dicom_geometry import SeriesGeometryResult
from anonymizer.controller.tseg.radlex_playbook import PLAYBOOK_TREE_IIDS
from anonymizer.controller.tseg.segment import TS_result
from anonymizer.model.anonymizer import StudyPhiHeader
from anonymizer.view.harmonize_results import HarmonizeResultsView, HarmonizeSeriesItem


class _MockPlaybookTree:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, ...]] = {}
        self.insert_order: list[str] = []
        self.columns: dict[str, int] = {}

    def get_children(self) -> tuple[str, ...]:
        return tuple(self.insert_order)

    def exists(self, iid: str) -> bool:
        return iid in self.rows

    def insert(self, _parent: str, _index: str, *, iid: str, values: tuple[str, ...]) -> None:
        self.rows[iid] = values
        if iid not in self.insert_order:
            self.insert_order.append(iid)

    def item(self, iid: str, option: str | None = None, *, values: tuple[str, ...] | None = None):
        if option == "values":
            return self.rows.get(iid)
        if values is not None:
            self.rows[iid] = values
        return None

    def column(self, col: str, option: str | None = None, **kwargs):
        if option == "width":
            return self.columns.get(col, 10)
        if "width" in kwargs:
            self.columns[col] = kwargs["width"]

    def delete(self, iid: str) -> None:
        self.rows.pop(iid, None)
        if iid in self.insert_order:
            self.insert_order.remove(iid)

    def see(self, _iid: str) -> None:
        return None


def _geometry() -> SeriesGeometryResult:
    return SeriesGeometryResult(
        plane="axial",
        plane_confidence=0.99,
        slice_normal_lps=(0.0, 0.0, 1.0),
        plane_angles_deg={"axial": 5.0, "coronal": 85.0, "sagittal": 85.0},
        dimensionality="volume_3d",
        n_slices=24,
        through_plane_extent_mm=120.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=True,
        metadata_suspect=False,
        method="dicom_headers",
        notes="",
    )


def _tseg(*, body_parts: str = "Head", contrast_phase: str = "arterial_early") -> TS_result:
    return TS_result(
        series_directory=__import__("pathlib").Path("/tmp/series"),
        dominant_region=body_parts,
        body_parts_present=body_parts,
        multi_region=False,
        region_fraction=0.91,
        iv_contrast=True,
        contrast_phase=contrast_phase,
        phase_probability=0.88,
        radlex_series_description="",
        structures_present={"brain": 50000, "skull": 10000},
    )


def test_playbook_tree_starts_empty_and_grows_with_progress() -> None:
    import customtkinter as ctk

    root = ctk.CTk()
    root.withdraw()
    try:
        view = HarmonizeResultsView.__new__(HarmonizeResultsView)
        view.PAD = HarmonizeResultsView.PAD
        view._data_font = ctk.CTkFont(family="Menlo", size=12)
        view._playbook_column_keys = HarmonizeResultsView._playbook_column_keys
        view._playbook_attr_map = HarmonizeResultsView._playbook_attr_map
        view._series_path = __import__("pathlib").Path("/tmp/series")
        view._ds = Dataset()
        view._playbook_tree = _MockPlaybookTree()

        view._clear_playbook_tree()
        assert view._playbook_tree.get_children() == ()

        view._update_playbook_from_progress(
            HarmonizeProgress(stage="geometry", message="", fraction=0.08, elapsed_sec=0.1, geometry=_geometry())
        )
        assert view._playbook_tree.insert_order == [
            PLAYBOOK_TREE_IIDS[1],
            PLAYBOOK_TREE_IIDS[3],
        ]
        for iid in view._playbook_tree.insert_order:
            values = view._playbook_tree.rows[iid]
            assert not all(value == "—" for value in values)

        view._update_playbook_from_progress(
            HarmonizeProgress(
                stage="regions",
                message="",
                fraction=0.62,
                elapsed_sec=1.0,
                geometry=_geometry(),
                tseg=_tseg(body_parts="Head", contrast_phase=""),
            )
        )
        assert PLAYBOOK_TREE_IIDS[0] in view._playbook_tree.insert_order
        assert PLAYBOOK_TREE_IIDS[2] not in view._playbook_tree.insert_order

        view._update_playbook_from_progress(
            HarmonizeProgress(
                stage="contrast",
                message="",
                fraction=0.92,
                elapsed_sec=2.0,
                geometry=_geometry(),
                tseg=_tseg(),
            )
        )
        assert view._playbook_tree.insert_order[-1] == PLAYBOOK_TREE_IIDS[2]
        assert len(view._playbook_tree.insert_order) == 4
    finally:
        root.destroy()


def test_on_yes_runs_save_before_recording_outcome(monkeypatch) -> None:
    from anonymizer.controller.harmonize import HarmonizedResult
    from pathlib import Path

    saved: list[tuple[Path, str]] = []

    def fake_apply(series_path: Path, description: str) -> bool:
        saved.append((series_path, description))
        return True

    monkeypatch.setattr(
        "anonymizer.view.harmonize_results.apply_series_description",
        fake_apply,
    )

    view = HarmonizeResultsView.__new__(HarmonizeResultsView)
    view._series_path = Path("/tmp/series")
    view._ds = Dataset()
    view._ds.SeriesInstanceUID = "1.2.3.4"
    view._item_index = 0
    view._batch_total = 1
    view._outcomes = []
    view._items = []
    view.cancelled = False
    view._saving = False
    view._running = False
    view._closing = False
    view._poll_after_id = None
    view._on_series_description_updated = None
    view._save_queue = __import__("queue").Queue()
    view._harmonize_queue = __import__("queue").Queue()
    view.ux_poll_interval_ms = 1
    view.PAD = HarmonizeResultsView.PAD
    view._batch_overall_fraction = lambda item_fraction: item_fraction
    view.result = HarmonizedResult(
        series_directory=Path("/tmp/series"),
        radlex_series_description="Brain Ax EarlyArt",
        tseg=None,
    )
    view._anon_model = None
    view._status_label = type("Lbl", (), {"configure": lambda *_a, **_k: None})()
    view._progressbar = type("Bar", (), {"set": lambda *_a, **_k: None})()
    view._no_button = type("Btn", (), {"configure": lambda *_a, **_k: None, "grid_remove": lambda *_a, **_k: None})()
    view._yes_button = type("Btn", (), {"configure": lambda *_a, **_k: None, "grid_remove": lambda *_a, **_k: None})()
    view._ok_button = type("Btn", (), {"grid_remove": lambda *_a, **_k: None})()
    view._error_frame = type("Frm", (), {"grid_remove": lambda *_a, **_k: None})()
    view._error_label = type("Lbl", (), {"configure": lambda *_a, **_k: None})()
    view._record_outcome = lambda *, accepted: view._outcomes.append(accepted)
    view.protocol = lambda *_a, **_k: None
    view.update_idletasks = lambda: None
    view.after = lambda _ms, fn: fn()
    view.winfo_exists = lambda: True

    view._begin_save_accepted_description("Brain Ax EarlyArt")

    assert saved == [(Path("/tmp/series"), "Brain Ax EarlyArt")]
    assert view._outcomes == [True]


def test_format_study_header_uses_placeholder_when_empty():
    line = HarmonizeResultsView.format_study_header("")
    assert line == "Study: (no study description)"


def test_blur_face_header_uses_phi_context_line():
    from anonymizer.view.harmonize_results import HarmonizeSeriesItem

    ds = Dataset()
    ds.StudyDescription = "Anon study"
    ds.SeriesDescription = "Anon series"
    ds.PatientName = "Anon^Patient"
    ds.PatientID = "ANON-1"
    phi_header = StudyPhiHeader(
        patient_name="Smith^Jane",
        patient_id="PHI-999",
        study_date="20240301",
        accession_number="ACC-42",
        study_description="PHI HEAD CT",
    )
    item = HarmonizeSeriesItem.from_dataset("/tmp/series", ds, phi_header=phi_header)

    study_line = HarmonizeResultsView.format_study_header(item.study_description, phi_header=item.phi_header)
    context_line = HarmonizeResultsView.format_study_context_line(phi_header=item.phi_header)

    assert study_line == "Study: PHI HEAD CT"
    assert "Patient: Smith^Jane" in context_line
    assert "ID: PHI-999" in context_line
    assert "Date: 20240301" in context_line
    assert "Accession: ACC-42" in context_line
    assert "Anon^Patient" not in context_line
    line = HarmonizeResultsView.format_study_header("")
    assert line == "Study: (no study description)"


def test_format_study_header_includes_description_without_phi():
    line = HarmonizeResultsView.format_study_header("CT HEAD WO")
    assert line == "Study: CT HEAD WO"


def test_format_study_header_prefers_phi_study_description():
    phi_header = StudyPhiHeader(study_description="PHI HEAD CT")
    line = HarmonizeResultsView.format_study_header("Anonymized study", phi_header=phi_header)
    assert line == "Study: PHI HEAD CT"


def test_format_series_description_header_includes_number_and_description():
    ds = Dataset()
    ds.SeriesNumber = 3
    line = HarmonizeResultsView.format_series_description_header(ds=ds, current_description="HEAD WO")
    assert line == 'Series Description (#3): "HEAD WO"'


def test_format_study_context_line_uses_phi_header_when_provided():
    ds = Dataset()
    ds.PatientName = "Anon^Name"
    ds.PatientID = "ANON123"
    ds.StudyDate = "19000101"
    ds.AccessionNumber = "ANON-A001"
    phi_header = StudyPhiHeader(
        patient_name="Doe^John",
        patient_id="MRN123",
        study_date="20240115",
        accession_number="ACC001",
        study_description="CT HEAD",
    )
    line = HarmonizeResultsView.format_study_context_line(phi_header=phi_header, ds=ds)
    assert "Patient: Doe^John" in line
    assert "ID: MRN123" in line
    assert "Date: 20240115" in line
    assert "Accession: ACC001" in line
    assert "Anon^Name" not in line
    assert "ANON123" not in line


def test_format_study_context_line_falls_back_to_dataset_without_phi():
    ds = Dataset()
    ds.PatientName = "Doe^John"
    ds.PatientID = "123"
    ds.StudyDate = "20240115"
    ds.AccessionNumber = "A001"
    ds.Modality = "CT"
    line = HarmonizeResultsView.format_study_context_line(
        ds=ds,
        batch_index=1,
        batch_total=5,
    )
    assert not line.startswith("Study:")
    assert "Patient: Doe^John" in line
    assert "ID: 123" in line
    assert "Date: 20240115" in line
    assert "Accession: A001" in line
    assert "Batch 2/5" in line
    assert line.endswith("A001") or "Batch 2/5" in line
    parts = line.split(" · ")
    assert "CT" not in parts


def test_format_batch_position_line():
    line = HarmonizeResultsView.format_batch_position_line(index=1, total=5)
    assert line == "Batch 2/5"


def test_harmonize_series_item_from_dataset():
    ds = Dataset()
    ds.StudyDescription = "Brain MRI"
    ds.SeriesDescription = "Ax T1"
    item = HarmonizeSeriesItem.from_dataset("/tmp/series", ds)
    assert item.study_description == "Brain MRI"
    assert item.current_description == "Ax T1"


def test_status_text_for_contrast_substeps():
    progress = HarmonizeProgress(
        stage="contrast_xgboost",
        message="Classifying contrast phase (XGBoost)",
        fraction=0.8,
        elapsed_sec=1.0,
    )
    text = HarmonizeResultsView._status_text_for_progress(progress)
    assert "Classifying contrast phase" in text
    assert "(80%)" in text


def test_status_text_for_cached_contrast_stats():
    progress = HarmonizeProgress(
        stage="contrast_stats_hn_cached",
        message="Using cached head/neck vessel statistics",
        fraction=0.7,
        elapsed_sec=1.0,
    )
    text = HarmonizeResultsView._status_text_for_progress(progress)
    assert "cached head/neck vessel statistics" in text
    assert "(70%)" in text


def test_harmonize_results_tree_row_counts_match_playbook_content():
    assert HarmonizeResultsView._DICOM_TREE_ROWS == 16
    assert HarmonizeResultsView._PLAYBOOK_TREE_ROWS == 4
    assert HarmonizeResultsView._DICOM_TREE_VISIBLE_ROWS == 17
    assert HarmonizeResultsView._PLAYBOOK_TREE_VISIBLE_ROWS == 5


def test_harmonize_results_min_height_fits_all_sections():
    import customtkinter as ctk

    root = ctk.CTk()
    root.withdraw()
    try:
        font = ctk.CTkFont(family="Menlo", size=12)
        view = HarmonizeResultsView.__new__(HarmonizeResultsView)
        view.PAD = HarmonizeResultsView.PAD
        view._DICOM_TREE_ROWS = HarmonizeResultsView._DICOM_TREE_ROWS
        view._PLAYBOOK_TREE_ROWS = HarmonizeResultsView._PLAYBOOK_TREE_ROWS
        view._DICOM_TREE_VISIBLE_ROWS = HarmonizeResultsView._DICOM_TREE_VISIBLE_ROWS
        view._PLAYBOOK_TREE_VISIBLE_ROWS = HarmonizeResultsView._PLAYBOOK_TREE_VISIBLE_ROWS
        view._data_font = font
        min_height = view._compute_min_window_height()
        assert min_height >= 720
        # DICOM (16) + Playbook (4) + header/proposal/footer should exceed old 540px default.
        assert min_height > 540
    finally:
        root.destroy()
