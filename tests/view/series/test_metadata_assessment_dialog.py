"""Unit tests: Metadata tree dialog panel + Detect PHI highlights."""

import contextlib
import tkinter as tk
from unittest.mock import patch

from pydicom import dcmread
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.view.series.metadata_assessment_dialog import (
    MetadataAssessmentDialog,
    MetadataTreePanel,
    _content_display_text,
    _format_detection_status,
    _metadata_window_title,
    _phi_hover_text,
    metadata_dialog_size,
)


def _sc_dataset(*, patient_name: str = "Test^Patient") -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "OT"
    ds.PatientName = patient_name
    ds.ImageType = ["DERIVED", "PRIMARY"]
    item = Dataset()
    item.CodeMeaning = "Test"
    ds.ProcedureCodeSequence = Sequence([item])
    # Endian / VR come from TransferSyntaxUID (pydicom 3+; avoid deprecated Dataset flags).
    return ds


def test_metadata_tree_panel_expand_and_search(tk_root: tk.Tk) -> None:
    panel = MetadataTreePanel(tk_root)
    panel.set_dataset(_sc_dataset())
    assert panel.tree.get_children()
    assert panel._expand_button.cget("text") == "Expand"
    assert panel._collapse_button.cget("text") == "Collapse"
    panel.expand_all()
    nested = []
    for top in panel.tree.get_children():
        nested.extend(panel.tree.get_children(top))
    assert nested  # ImageType values and/or sequence items
    visible = panel._visible_iids()
    assert visible
    tags0 = panel.tree.item(visible[0], "tags")
    assert "row_even" in tags0 or "row_odd" in tags0
    if len(visible) > 1:
        tags1 = panel.tree.item(visible[1], "tags")
        assert tags0 != tags1
    panel._search_var.set("procedure")
    panel._rebuild()
    kids = panel.tree.get_children()
    assert kids
    assert any("Procedure" in panel.tree.item(i, "text") for i in kids)


def test_apply_phi_entities_colors_content_rows(tk_root: tk.Tk) -> None:
    panel = MetadataTreePanel(tk_root)
    panel.set_dataset(_sc_dataset(patient_name="Doe^Jane"))
    content = "Doe^Jane"
    assert content in panel.content_texts()
    ents = (Entity(label="FIRST_NAME", start=0, end=len(content)),)
    count = panel.apply_phi_entities({content: ents})
    assert count == 1
    hit_iids = [iid for iid, text in panel._content_by_iid.items() if text == content]
    assert hit_iids
    tags = panel.tree.item(hit_iids[0], "tags")
    # Dataset View pattern: the highlight tag is the row's only tag, so no
    # zebra stripe can override its entity background / white foreground.
    assert tags == ("phi_FIRST_NAME",)
    # Category is visible in the Content column itself (Treeview tags are
    # row-wide; they cannot color only the matched span inside one cell).
    values = panel.tree.item(hit_iids[0], "values")
    assert "[FIRST_NAME]" in str(values[1])


def test_phi_hover_text_shows_detected_phi_after_class() -> None:
    content = "Jane Doe 06.16.1976"
    ents = (
        Entity(label="DATE", start=9, end=19),
        Entity(label="FIRST_NAME", start=0, end=4),
        Entity(label="LAST_NAME", start=5, end=8),
    )
    assert _phi_hover_text(content, ents) == "FIRST_NAME: Jane · LAST_NAME: Doe · DATE: 06.16.1976"
    assert _phi_hover_text("Portable", ()) == ""


def test_content_display_text_marks_phi_categories() -> None:
    ents = (Entity(label="LOCATION", start=3, end=9), Entity(label="FIRST_NAME", start=0, end=2))
    assert _content_display_text("US biopsy", ents) == "US biopsy  [FIRST_NAME · LOCATION]"
    assert _content_display_text("Portable", ()) == "Portable"


def test_metadata_dialog_size_caps_height_at_85_percent_screen() -> None:
    # Content needs more room → grow, but never past 85% of screen height.
    width, height = metadata_dialog_size(
        screen_width=1440, screen_height=900, required_width=1500, required_height=5000
    )
    assert height == int(900 * 0.85)
    assert width == 1400
    # Small content keeps the default size.
    assert metadata_dialog_size(
        screen_width=1440, screen_height=900, required_width=800, required_height=500
    ) == (960, 600)


def test_field_name_column_fits_longest_name(tk_root: tk.Tk) -> None:
    ds = _sc_dataset()
    ds.ManufacturerModelName = "LOGIQE9"
    panel = MetadataTreePanel(tk_root)
    panel.set_dataset(ds)
    longest = "Manufacturer's Model Name"
    width = int(panel.tree.column("#0", option="width"))
    assert width >= len(longest) * panel._char_width_px


def test_value_children_detect_as_parent_field(tk_root: tk.Tk) -> None:
    panel = MetadataTreePanel(tk_root)
    panel.set_dataset(_sc_dataset())
    items = panel.content_ner_items()
    # Multi-value children are one field: only the parent's joined Content
    # is a NER/remove unit, carrying the parent VR.
    assert not any(item.tag_path.endswith(("ImageType[0]", "ImageType[1]")) for item in items)
    image_type = [item for item in items if item.tag_path == "ImageType"]
    assert len(image_type) == 1
    assert image_type[0].vr == "CS"


def test_metadata_window_title_names_series() -> None:
    ds = _sc_dataset()
    ds.SeriesDescription = "US biopsy"
    assert _metadata_window_title(ds) == "Metadata — US biopsy (OT)"
    ds.SeriesDescription = ""
    ds.SeriesInstanceUID = "1.2.840.1234567890"
    title = _metadata_window_title(ds)
    assert title.startswith("Metadata — …")
    assert title.endswith("(OT)")


def test_format_detection_status_reports_private_uid_date_handling() -> None:
    status = _format_detection_status({}, private_uid_count=2, private_date_count=3)
    assert status.startswith("No PHI detected.")
    assert "Private data: 2 UID, 3 date fields" in status
    assert "UID remapping / date delta" in status
    assert "not scored by Detect PHI" in status


def test_format_detection_status_empty_and_counts() -> None:
    assert _format_detection_status({}) == "No PHI detected."
    ents = {"x": (Entity(label="FIRST_NAME", start=0, end=1), Entity(label="ID", start=2, end=3))}
    status = _format_detection_status(ents)
    assert "Detection complete" in status
    assert "(2 in 1 field)" in status
    multi = {
        "a": (Entity(label="FIRST_NAME", start=0, end=1),),
        "b": (Entity(label="LOCATION", start=0, end=1), Entity(label="ID", start=2, end=3)),
    }
    assert "(3 in 2 fields)" in _format_detection_status(multi)
    # Explicit field count (tree rows) wins over distinct Content values.
    assert "(3 in 4 fields)" in _format_detection_status(multi, field_count=4)


def test_panel_apply_cleaned_texts_writes_dataset(tk_root: tk.Tk) -> None:
    ds = _sc_dataset(patient_name="Doe^Jane")
    panel = MetadataTreePanel(tk_root)
    panel.set_dataset(ds)
    changed = panel.apply_cleaned_texts({"Doe^Jane": ""})
    assert changed == 1
    assert str(ds.PatientName) == ""
    assert panel.pending_cleaned_by_tag_path() == {"PatientName": ""}
    assert "Doe^Jane" not in panel.content_texts()


def test_detect_button_wires_ner(tk_root: tk.Tk) -> None:
    dialog = MetadataAssessmentDialog(tk_root, dataset=_sc_dataset(patient_name="Smith^Ada"))
    # Keep off-screen: constructor deiconifies; tests must not flash mixed chrome.
    dialog.withdraw()
    with contextlib.suppress(tk.TclError):
        dialog.grab_release()
    assert dialog.detect_button.cget("text") == "Detect PHI"
    assert dialog.close_button.cget("text") == "Close"
    name = "Smith^Ada"
    fake = {name: (Entity(label="FIRST_NAME", start=0, end=len(name)),)}

    class _ImmediateThread:
        def __init__(self, target=None, **_kwargs) -> None:  # noqa: ANN001
            self._target = target

        def start(self) -> None:
            if self._target is not None:
                self._target()

    with (
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.report_text_phi_ready",
            return_value=True,
        ),
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.detect_phi_in_texts",
            return_value=fake,
        ),
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.threading.Thread",
            side_effect=_ImmediateThread,
        ),
    ):
        dialog._on_detect()
        dialog._poll_detect()
    assert not dialog._detecting
    hit_iids = [iid for iid, text in dialog.panel._content_by_iid.items() if text == name]
    assert hit_iids
    assert "phi_FIRST_NAME" in dialog.tree.item(hit_iids[0], "tags")
    dialog._on_close()


def test_metadata_remove_phi_then_save_writes_file(tk_root: tk.Tk, tmp_path) -> None:  # noqa: ANN001
    ds = _sc_dataset(patient_name="Smith^Ada")
    path = tmp_path / "slice.dcm"
    ds.save_as(path, enforce_file_format=True)
    dialog = MetadataAssessmentDialog(tk_root, dataset=ds, dataset_path=path)
    dialog.withdraw()
    with contextlib.suppress(tk.TclError):
        dialog.grab_release()
    name = "Smith^Ada"
    fake = {name: (Entity(label="FIRST_NAME", start=0, end=len(name)),)}

    class _ImmediateThread:
        def __init__(self, target=None, **_kwargs) -> None:  # noqa: ANN001
            self._target = target

        def start(self) -> None:
            if self._target is not None:
                self._target()

    with (
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.report_text_phi_ready",
            return_value=True,
        ),
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.detect_phi_in_texts",
            return_value=fake,
        ),
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.threading.Thread",
            side_effect=_ImmediateThread,
        ),
    ):
        dialog._on_detect()
        dialog._poll_detect()
    # Report View flow: Remove appears after Detect, then Save persists.
    # grid_info (not winfo_ismapped): dialog is withdrawn in this test.
    assert dialog.remove_button.grid_info()
    dialog._on_remove()
    assert dialog._dirty
    assert name not in dialog.panel.content_texts()
    dialog._on_save()
    assert not dialog._dirty
    assert str(dcmread(path).PatientName) != name
    dialog._on_close()


class _ImmediateThread:
    def __init__(self, target=None, **_kwargs) -> None:  # noqa: ANN001
        self._target = target
        self.started = False

    def start(self) -> None:
        self.started = True
        if self._target is not None:
            self._target()


def _run_detect(dialog: MetadataAssessmentDialog, fake: dict) -> None:
    with (
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.report_text_phi_ready",
            return_value=True,
        ),
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.detect_phi_in_texts",
            return_value=fake,
        ),
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.threading.Thread",
            side_effect=_ImmediateThread,
        ),
    ):
        dialog._on_detect()
        dialog._poll_detect()


def test_dialog_without_dataset_path_disables_save(tk_root: tk.Tk) -> None:
    """Series View opens Metadata without dataset_path — Save stays disabled."""
    ds = _sc_dataset(patient_name="Smith^Ada")
    dialog = MetadataAssessmentDialog(tk_root, dataset=ds, dataset_path=None)
    dialog.withdraw()
    with contextlib.suppress(tk.TclError):
        dialog.grab_release()
    name = "Smith^Ada"
    _run_detect(dialog, {name: (Entity(label="FIRST_NAME", start=0, end=len(name)),)})
    dialog._on_remove()
    assert dialog._dirty
    assert dialog.save_button.cget("state") == "disabled"
    dialog._on_save()  # no-op without path
    assert dialog._dirty
    assert name not in dialog.panel.content_texts()
    with patch(
        "anonymizer.view.series.metadata_assessment_dialog.messagebox.askyesno",
        return_value=True,
    ):
        dialog._on_close()


def test_detect_models_not_ready_warns_without_thread(tk_root: tk.Tk) -> None:
    dialog = MetadataAssessmentDialog(tk_root, dataset=_sc_dataset())
    dialog.withdraw()
    with contextlib.suppress(tk.TclError):
        dialog.grab_release()
    with (
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.report_text_phi_ready",
            return_value=False,
        ),
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.messagebox.showwarning"
        ) as warn,
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.threading.Thread"
        ) as thread_cls,
    ):
        dialog._on_detect()
    warn.assert_called_once()
    thread_cls.assert_not_called()
    assert not dialog._detecting
    dialog._on_close()


def test_detect_error_surfaces_status(tk_root: tk.Tk) -> None:
    dialog = MetadataAssessmentDialog(tk_root, dataset=_sc_dataset())
    dialog.withdraw()
    with contextlib.suppress(tk.TclError):
        dialog.grab_release()

    def _failing_worker() -> None:
        dialog._detect_queue.put(("error", "boom"))

    class _FailThread:
        def __init__(self, target=None, **_kwargs) -> None:  # noqa: ANN001
            del target

        def start(self) -> None:
            _failing_worker()

    with (
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.report_text_phi_ready",
            return_value=True,
        ),
        patch(
            "anonymizer.view.series.metadata_assessment_dialog.threading.Thread",
            side_effect=_FailThread,
        ),
    ):
        dialog._on_detect()
        dialog._poll_detect()
    assert not dialog._detecting
    assert "Detection failed" in str(dialog._status_label.cget("text"))
    dialog._on_close()


def test_exclude_all_phi_disables_remove(tk_root: tk.Tk) -> None:
    ds = _sc_dataset(patient_name="Smith^Ada")
    dialog = MetadataAssessmentDialog(tk_root, dataset=ds)
    dialog.withdraw()
    with contextlib.suppress(tk.TclError):
        dialog.grab_release()
    name = "Smith^Ada"
    _run_detect(dialog, {name: (Entity(label="FIRST_NAME", start=0, end=len(name)),)})
    assert dialog.remove_button.cget("state") == "normal"
    dialog.panel._excluded_contents.add(name)
    dialog._refresh_state()
    assert dialog.remove_button.cget("state") == "disabled"
    dialog._on_close()


def test_dirty_close_cancels_when_user_declines(tk_root: tk.Tk) -> None:
    ds = _sc_dataset(patient_name="Smith^Ada")
    dialog = MetadataAssessmentDialog(tk_root, dataset=ds)
    dialog.withdraw()
    with contextlib.suppress(tk.TclError):
        dialog.grab_release()
    name = "Smith^Ada"
    _run_detect(dialog, {name: (Entity(label="FIRST_NAME", start=0, end=len(name)),)})
    dialog._on_remove()
    assert dialog._dirty
    with patch(
        "anonymizer.view.series.metadata_assessment_dialog.messagebox.askyesno",
        return_value=False,
    ):
        dialog._on_close()
    assert not dialog._destroyed
    with patch(
        "anonymizer.view.series.metadata_assessment_dialog.messagebox.askyesno",
        return_value=True,
    ):
        dialog._on_close()
    assert dialog._destroyed


def test_private_uid_date_counts_on_panel(tk_root: tk.Tk) -> None:
    ds = _sc_dataset()
    block = ds.private_block(0x0009, "GEMS_PETD_01", create=True)
    block.add_new(0x01, "UI", "1.2.3.4.5")
    block.add_new(0x05, "DA", "20200115")
    panel = MetadataTreePanel(tk_root)
    panel.set_dataset(ds)
    uids, dates = panel.private_uid_date_counts()
    assert uids >= 1
    assert dates >= 1


def test_remove_synth_and_blank_modes(tk_root: tk.Tk) -> None:
    for mode_key in ("blank", "synth"):
        ds = _sc_dataset(patient_name="Smith^Ada")
        dialog = MetadataAssessmentDialog(tk_root, dataset=ds)
        dialog.withdraw()
        with contextlib.suppress(tk.TclError):
            dialog.grab_release()
        name = "Smith^Ada"
        _run_detect(dialog, {name: (Entity(label="FIRST_NAME", start=0, end=len(name)),)})
        label = next(lbl for lbl, key in dialog._mode_labels.items() if key == mode_key)
        dialog.mode_var.set(label)
        dialog._on_remove()
        texts = dialog.panel.content_texts()
        assert name not in texts
        with patch(
            "anonymizer.view.series.metadata_assessment_dialog.messagebox.askyesno",
            return_value=True,
        ):
            dialog._on_close()
