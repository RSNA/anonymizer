"""Frozen Clean Descriptors NER compile contract (do not change in fine-tuning)."""

from anonymizer.controller.ai.embedded_phi.metadata.ner_compile import (
    NerCompileCell,
    compile_ner_input,
    remap_entities_via_offset_map,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity


def test_compile_keeps_punctuation_and_spaces() -> None:
    cells = [
        NerCompileCell(
            text="supine for 2522288856",
            field_name="Image Comments",
            tag="(0020,4000)",
            vr="LT",
            tag_path="ImageComments",
        ),
        NerCompileCell(
            text="110-78-3749",
            field_name="Study Description",
            tag="(0008,1030)",
            vr="LO",
            tag_path="StudyDescription",
        ),
    ]
    compiled = compile_ner_input(cells)
    assert compiled.ner_text == (
        "Image Comments: supine for 2522288856.\n"
        "Study Description: 110-78-3749."
    )
    assert "Image Comments: " in compiled.ner_text
    assert "\n" in compiled.ner_text
    assert compiled.ner_text.endswith(".")
    assert len(compiled.offset_map) == len(compiled.ner_text)


def test_compile_keeps_spaces_in_person_name_prose() -> None:
    """Spaces and hyphens stay so OpenMed sees normal prose."""
    body = "PET-CT STUDY for Michelle Stanley"
    compiled = compile_ner_input(
        [
            NerCompileCell(
                text=body,
                field_name="Study Description",
                tag="(0008,1030)",
                vr="LO",
                tag_path="StudyDescription",
            )
        ]
    )
    assert compiled.ner_text == "Study Description: PET-CT STUDY for Michelle Stanley."
    assert "Michelle Stanley" in compiled.ner_text
    assert "MichelleStanley" not in compiled.ner_text


def test_compile_drops_control_characters_only() -> None:
    """Non-printable / control chars are stripped; normal punctuation is kept."""
    body = "hello\x00world\x07!"
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
    assert compiled.ner_text == "Image Comments: helloworld!."


def test_remap_span_on_hyphenated_id() -> None:
    cells = [
        NerCompileCell(
            text="Study 110-78-3749 done",
            field_name="Study Description",
            tag="(0008,1030)",
            vr="LO",
            tag_path="StudyDescription",
        ),
    ]
    compiled = compile_ner_input(cells)
    assert "Study 110-78-3749 done" in compiled.ner_text
    start = compiled.ner_text.index("110-78-3749")
    ents = [Entity(label="ID", start=start, end=start + 11, raw_label="credit_debit_card")]
    by_text = remap_entities_via_offset_map(ents, compiled)
    body = "Study 110-78-3749 done"
    assert body in by_text
    frag = body[by_text[body][0].start : by_text[body][0].end]
    assert frag == "110-78-3749"
