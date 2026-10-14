"""Unit tests: Metadata tree dialog panel + Detect PHI highlights."""

from __future__ import annotations

import contextlib
import tkinter as tk
from unittest.mock import patch

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.view.series.metadata_assessment_dialog import (
    MetadataAssessmentDialog,
    MetadataTreePanel,
    _format_detection_status,
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
    ds.is_little_endian = True
    ds.is_implicit_VR = False
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
    ents = (Entity(label="NAME", start=0, end=len(content)),)
    count = panel.apply_phi_entities({content: ents})
    assert count == 1
    hit_iids = [iid for iid, text in panel._content_by_iid.items() if text == content]
    assert hit_iids
    tags = panel.tree.item(hit_iids[0], "tags")
    assert "phi_NAME" in tags


def test_format_detection_status_empty_and_counts() -> None:
    assert _format_detection_status({}) == "No PHI detected."
    ents = {"x": (Entity(label="NAME", start=0, end=1), Entity(label="ID", start=2, end=3))}
    status = _format_detection_status(ents)
    assert "Detection complete" in status
    assert "2" in status


def test_detect_button_wires_ner(tk_root: tk.Tk) -> None:
    dialog = MetadataAssessmentDialog(tk_root, dataset=_sc_dataset(patient_name="Smith^Ada"))
    # Keep off-screen: constructor deiconifies; tests must not flash mixed chrome.
    dialog.withdraw()
    with contextlib.suppress(tk.TclError):
        dialog.grab_release()
    assert dialog.detect_button.cget("text") == "Detect PHI"
    assert dialog.close_button.cget("text") == "Close"
    name = "Smith^Ada"
    fake = {name: (Entity(label="NAME", start=0, end=len(name)),)}

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
    assert "phi_NAME" in dialog.tree.item(hit_iids[0], "tags")
    dialog._on_close()
