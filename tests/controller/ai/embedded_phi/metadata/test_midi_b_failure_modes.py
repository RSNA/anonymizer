"""MIDI-B Clean Descriptors failure-mode fixtures.

Compile-contract and write-back tests must pass.
OpenMed ID-hit cases may fail until fine-tuning — marked xfail(strict=False)
where the gap is the model, not the compile/remap/apply contract.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.detect import detect_metadata_phi
from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    extract_metadata_phi_rows,
    omit_pure_numeric_from_descriptor_ner,
)
from anonymizer.controller.ai.embedded_phi.metadata.ner_compile import (
    NerCompileCell,
    compile_ner_input,
)
from anonymizer.controller.ai.embedded_phi.metadata.scrub import scrub_dataset_descriptors
from anonymizer.controller.ai.embedded_phi.ner.cache import ner_ready
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import MetadataNerItem

# --- Compile contract (must pass) -------------------------------------------


def test_midi_compile_supine_for_patient_id_stays_in_ner_input() -> None:
    """Image Comments: supine + ID keep spaces after compile."""
    body = "supine for 2522288856"
    compiled = compile_ner_input(
        [
            NerCompileCell(
                text=body,
                field_name="Image Comments",
                tag="(0020,4000)",
                vr="LT",
                tag_path="ImageComments",
            )
        ]
    )
    assert compiled.ner_text == "Image Comments: supine for 2522288856."
    assert "supine for 2522288856" in compiled.ner_text


def test_midi_compile_never_applies_whitelist() -> None:
    """Whitelist is post-NER only — step 2 compile is unchanged by clinical terms."""
    body = "supine for 2522288856 CT ABDOMEN"
    compiled = compile_ner_input(
        [
            NerCompileCell(
                text=body,
                field_name="Image Comments",
                tag="(0020,4000)",
                vr="LT",
                tag_path="ImageComments",
            )
        ]
    )
    assert compiled.ner_text.startswith("Image Comments: ")
    assert "supine" in compiled.ner_text
    assert "CT" in compiled.ner_text
    assert "ABDOMEN" in compiled.ner_text
    assert "2522288856" in compiled.ner_text


def test_midi_compile_hyphenated_study_description_id() -> None:
    compiled = compile_ner_input(
        [
            NerCompileCell(
                text="110-78-3749",
                field_name="Study Description",
                tag="(0008,1030)",
                vr="LO",
                tag_path="StudyDescription",
            )
        ]
    )
    assert compiled.ner_text == "Study Description: 110-78-3749."
    assert "110-78-3749" in compiled.ner_text


def test_midi_shared_content_write_back_both_tags() -> None:
    """Same Content on two tags: cleaned string written to every match."""
    shared = "Ordered for 8371727310 by DH"
    ds = Dataset()
    ds.RequestedProcedureDescription = shared
    ds.StudyComments = shared
    ds.Modality = "PT"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        needle = "8371727310"
        if needle not in text:
            return []
        i = text.index(needle)
        return [Entity(label="ID", start=i, end=i + len(needle))]

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert changed is True
    assert any("8371727310" in r for r in removed)
    assert "8371727310" not in str(ds.RequestedProcedureDescription)
    assert "8371727310" not in str(ds.StudyComments)


def test_midi_pure_is_ds_not_wiped_as_id() -> None:
    """Pure frame duration / short series / attenuation floats stay when NER is empty."""
    ds = Dataset()
    ds.ActualFrameDuration = "360000"
    ds.SeriesNumber = "3"
    # Attenuation-style decimal (DS).
    ds.RescaleSlope = "0.096000"
    ds.StudyDescription = "ROUTINE"
    ds.Modality = "PT"

    assert omit_pure_numeric_from_descriptor_ner("IS", "360000")
    assert omit_pure_numeric_from_descriptor_ner("DS", "0.096000")
    rows = extract_metadata_phi_rows(ds)
    paths = {r.tag_path for r in rows}
    assert "ActualFrameDuration" in paths
    assert "SeriesNumber" in paths
    assert "RescaleSlope" in paths

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")
    assert changed is False
    assert removed == []
    assert str(ds.ActualFrameDuration) == "360000"
    assert str(ds.SeriesNumber) == "3"
    assert str(ds.RescaleSlope) == "0.096000"


def test_midi_protocol_for_patient_id_eligible_after_compile() -> None:
    """Protocol / Series '… for {PatientID}' digit ID is still in NER input."""
    body = "PET WB for 2522288856"
    ds = Dataset()
    seen: list[str] = []

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        seen.append(text)
        assert "2522288856" in text
        i = text.index("2522288856")
        return [Entity(label="ID", start=i, end=i + 10, raw_label="credit_debit_card")]

    items = [
        MetadataNerItem(text=body, field_name="Protocol Name", vr="LO"),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
    assert seen and "for 2522288856" in seen[0]
    # Post-NER expand may include leading "for "; ID digits must be covered.
    span = body[out[body][0].start : out[body][0].end]
    assert "2522288856" in span


def test_midi_study_comments_doctor_name_blank_includes_title() -> None:
    """Dr. + surname blank together so MIDI token checks do not see leftover 'dr'."""
    body = "Dr. Ramirez, call if questions"
    ds = Dataset()
    ds.StudyComments = body
    ds.Modality = "CT"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        # Compile keeps printable punctuation; name is still present.
        needle = "Ramirez"
        i = text.index(needle)
        return [Entity(label="LAST_NAME", start=i, end=i + len(needle))]

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert changed is True
    assert any("Ramirez" in r for r in removed)
    assert "Ramirez" not in str(ds.StudyComments)
    # Title expands onto the name span (post-NER Dr. widen / pattern fill).
    assert "Dr." not in str(ds.StudyComments)
    assert "Dr" not in str(ds.StudyComments).split(",")[0]


# --- Model-gap cases (may fail until fine-tuning) ---------------------------


@pytest.mark.xfail(
    reason="OpenMed model gap: ID after clinical 'supine for' — fine-tune follow-up",
    strict=False,
)
def test_midi_xfail_openmed_tags_id_after_supine_for() -> None:
    """Live model should tag 2522288856 in Image Comments (fine-tune if not)."""
    pytest.importorskip("transformers")

    if not ner_ready():
        pytest.skip("NER weights not installed")

    body = "supine for 2522288856"
    ds = Dataset()
    items = [MetadataNerItem(text=body, field_name="Image Comments", vr="LT")]
    out = detect_metadata_phi(ds=ds, items=items, whitelist=["SUPINE", "CT", "ABDOMEN"])
    assert body in out
    frags = [body[e.start : e.end] for e in out[body]]
    assert any("2522288856" in f for f in frags)


@pytest.mark.xfail(
    reason="OpenMed model gap: hyphenated Study Description ID — fine-tune follow-up",
    strict=False,
)
def test_midi_xfail_openmed_tags_hyphenated_study_description_id() -> None:
    pytest.importorskip("transformers")

    if not ner_ready():
        pytest.skip("NER weights not installed")

    body = "110-78-3749"
    ds = Dataset()
    items = [MetadataNerItem(text=body, field_name="Study Description", vr="LO")]
    out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
    assert body in out
    frags = [body[e.start : e.end] for e in out[body]]
    assert any(f.replace("-", "") == "110783749" or "110" in f for f in frags)
