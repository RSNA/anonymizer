"""IS/DS numeric strings: embedded dates/PHI must reach NER and be detected.

Contract tests mock OpenMed (compile + remap). Live OpenMed tests assert the
model tags digit IDs / compact dates inside IS and DS Content; they xfail when
the current weights miss (model gap until fine-tune).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydicom.dataelem import DataElement
from pydicom.datadict import tag_for_keyword
from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.detect import detect_phi_in_texts
from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    NER_INPUT_VRS,
    extract_metadata_phi_rows,
)
from anonymizer.controller.ai.embedded_phi.metadata.ner_compile import (
    NerCompileCell,
    compile_ner_input,
)
from anonymizer.controller.ai.embedded_phi.metadata.scrub import scrub_dataset_descriptors
from anonymizer.controller.ai.embedded_phi.ner.cache import ner_ready
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity, detect_entities
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import MetadataNerItem


def _set_vr_text(ds: Dataset, keyword: str, vr: str, value: str) -> None:
    """Assign keyword with raw VR text (pydicom cannot coerce impure IS/DS)."""
    tag = tag_for_keyword(keyword)
    assert tag is not None, keyword
    placeholder = "0" if vr == "IS" else "0.0"
    elem = DataElement(tag, vr, placeholder)
    elem._value = value
    ds.add(elem)


def test_ner_input_vrs_include_is_and_ds() -> None:
    assert "IS" in NER_INPUT_VRS
    assert "DS" in NER_INPUT_VRS
    assert "LO" in NER_INPUT_VRS


def test_is_with_embedded_id_and_date_in_compile_and_remap() -> None:
    """IS Content with embedded PatientID + YYYYMMDD appears as Tag Name: alnum."""
    body = "scan for 2522288856 on 20101203"
    cells = [
        NerCompileCell(
            text=body,
            field_name="Series Number",
            tag="(0020,0011)",
            vr="IS",
            tag_path="SeriesNumber",
        )
    ]
    compiled = compile_ner_input(cells)
    assert compiled.ner_text == "Series Number: scan for 2522288856 on 20101203."
    assert "2522288856" in compiled.ner_text

    ds = Dataset()
    id_start = compiled.ner_text.index("2522288856")
    date_start = compiled.ner_text.index("20101203")

    def _fake(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        assert text == compiled.ner_text
        return [
            Entity(label="ID", start=id_start, end=id_start + 10, raw_label="credit_debit_card"),
            Entity(label="DATE", start=date_start, end=date_start + 8, raw_label="date"),
        ]

    items = [
        MetadataNerItem(
            text=body,
            field_name="Series Number",
            tag="(0020,0011)",
            vr="IS",
            tag_path="SeriesNumber",
        )
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake,
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    frags = [body[e.start : e.end] for e in out[body]]
    # Leading "for " may expand onto the ID span before remove.
    assert any("2522288856" in f for f in frags)
    assert any("20101203" in f for f in frags)


def test_ds_with_embedded_id_in_compile_and_remap() -> None:
    """DS Content with embedded ID (letters/junk + float) reaches NER."""
    body = "0.096000 for 8371727310"
    cells = [
        NerCompileCell(
            text=body,
            field_name="Rescale Slope",
            tag="(0028,1053)",
            vr="DS",
            tag_path="RescaleSlope",
        )
    ]
    compiled = compile_ner_input(cells)
    assert compiled.ner_text == "Rescale Slope: 0.096000 for 8371727310."
    assert "8371727310" in compiled.ner_text

    ds = Dataset()
    id_start = compiled.ner_text.index("8371727310")

    def _fake(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        return [
            Entity(label="ID", start=id_start, end=id_start + 10, raw_label="credit_debit_card"),
        ]

    items = [
        MetadataNerItem(
            text=body,
            field_name="Rescale Slope",
            tag="(0028,1053)",
            vr="DS",
            tag_path="RescaleSlope",
        )
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake,
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    frags = [body[e.start : e.end] for e in out[body]]
    assert any("8371727310" in f for f in frags)


def test_ds_with_embedded_date_in_compile_and_detect() -> None:
    """DS Content with embedded YYYYMMDD is compiled and DATE-filled after NER."""
    body = "1.25 dated 20101203"
    cells = [
        NerCompileCell(
            text=body,
            field_name="Slice Thickness",
            tag="(0018,0050)",
            vr="DS",
            tag_path="SliceThickness",
        )
    ]
    compiled = compile_ner_input(cells)
    assert compiled.ner_text == "Slice Thickness: 1.25 dated 20101203."
    assert "20101203" in compiled.ner_text

    ds = Dataset()
    items = [
        MetadataNerItem(
            text=body,
            field_name="Slice Thickness",
            tag="(0018,0050)",
            vr="DS",
            tag_path="SliceThickness",
        )
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    assert body in out
    frags = [body[e.start : e.end] for e in out[body]]
    assert "20101203" in frags
    assert all(e.label == "DATE" for e in out[body] if body[e.start : e.end] == "20101203")


def test_ds_with_embedded_name_in_compile_and_remap() -> None:
    """DS Content with embedded person name remaps OpenMed span to original offsets."""
    body = "62.9 Michelle"
    cells = [
        NerCompileCell(
            text=body,
            field_name="Rescale Slope",
            tag="(0028,1053)",
            vr="DS",
            tag_path="RescaleSlope",
        )
    ]
    compiled = compile_ner_input(cells)
    assert compiled.ner_text == "Rescale Slope: 62.9 Michelle."
    name_start = compiled.ner_text.index("Michelle")

    def _fake(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        return [
            Entity(
                label="FIRST_NAME",
                start=name_start,
                end=name_start + len("Michelle"),
                raw_label="given_name",
            ),
        ]

    items = [
        MetadataNerItem(
            text=body,
            field_name="Rescale Slope",
            tag="(0028,1053)",
            vr="DS",
            tag_path="RescaleSlope",
        )
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake,
    ):
        out = detect_phi_in_texts(ds=Dataset(), items=items, whitelist=[])
    assert body[out[body][0].start : out[body][0].end] == "Michelle"


def test_scrub_blanks_embedded_id_in_is_and_ds() -> None:
    ds = Dataset()
    _set_vr_text(ds, "SeriesNumber", "IS", "ordered for 2522288856")
    _set_vr_text(ds, "RescaleSlope", "DS", "1.5 id 8371727310")
    ds.Modality = "CT"

    def _fake(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        out: list[Entity] = []
        for needle in ("2522288856", "8371727310"):
            if needle in text:
                i = text.index(needle)
                out.append(Entity(label="ID", start=i, end=i + len(needle)))
        return out

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake,
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert changed is True
    assert any("2522288856" in r for r in removed)
    assert any("8371727310" in r for r in removed)
    assert "2522288856" not in str(ds.SeriesNumber)
    assert "8371727310" not in str(ds.RescaleSlope)


def test_scrub_blanks_embedded_date_and_name_in_ds() -> None:
    """DS write-back blanks DATE fill and remapped FIRST_NAME spans."""
    ds = Dataset()
    _set_vr_text(ds, "SliceThickness", "DS", "1.25 dated 20101203")
    _set_vr_text(ds, "RescaleSlope", "DS", "62.9 Michelle")
    ds.Modality = "CT"

    def _fake(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        out: list[Entity] = []
        if "Michelle" in text:
            i = text.index("Michelle")
            out.append(Entity(label="FIRST_NAME", start=i, end=i + len("Michelle")))
        return out

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake,
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert changed is True
    assert any("20101203" in r for r in removed)
    assert any("Michelle" in r for r in removed)
    assert "20101203" not in str(ds.SliceThickness)
    assert "Michelle" not in str(ds.RescaleSlope)


def test_extract_includes_impure_is_and_ds() -> None:
    ds = Dataset()
    _set_vr_text(ds, "SeriesNumber", "IS", "for 2522288856")
    _set_vr_text(ds, "RescaleSlope", "DS", "0.096 Jane")
    rows = extract_metadata_phi_rows(ds)
    by_path = {r.tag_path: r.text for r in rows}
    assert by_path.get("SeriesNumber") == "for 2522288856"
    assert by_path.get("RescaleSlope") == "0.096 Jane"


def test_pure_frame_duration_not_claimed_as_compact_tm() -> None:
    """Actual Frame Duration 360000 must not be wiped as a clock time."""
    ds = Dataset()
    ds.ActualFrameDuration = "360000"
    ds.StudyDescription = "ROUTINE"
    ds.Modality = "PT"
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")
    assert "360000" not in removed
    assert str(ds.ActualFrameDuration) == "360000"


def test_pure_ds_attenuation_not_claimed_as_compact_tm() -> None:
    """Pure DS 0.096000 must not be wiped as a compact time."""
    ds = Dataset()
    ds.RescaleSlope = "0.096000"
    ds.StudyDescription = "ROUTINE"
    ds.Modality = "PT"
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")
    assert "096000" not in removed
    assert "0.096000" not in removed
    assert str(ds.RescaleSlope) == "0.096000"
    assert changed is False


def _require_openmed_hit(frags: list[str], needle: str) -> None:
    """Assert OpenMed hit; xfail when current weights miss (model gap)."""
    if any(needle in f for f in frags):
        return
    pytest.xfail(f"OpenMed gap on glued IS/DS: no span covering {needle!r} in {frags!r}")


@pytest.mark.skipif(not ner_ready(), reason="NER weights not installed")
def test_openmed_detects_id_and_date_inside_is_string() -> None:
    """Live model: digit ID + YYYYMMDD inside an IS-shaped string."""
    body = "scan for 2522288856 on 20101203"
    compiled = compile_ner_input(
        [
            NerCompileCell(
                text=body,
                field_name="Series Number",
                tag="(0020,0011)",
                vr="IS",
                tag_path="SeriesNumber",
            )
        ]
    )
    ents = detect_entities(compiled.ner_text, locale="en_US")
    frags = [compiled.ner_text[e.start : e.end] for e in ents]
    _require_openmed_hit(frags, "2522288856")

    ds = Dataset()
    items = [
        MetadataNerItem(
            text=body,
            field_name="Series Number",
            tag="(0020,0011)",
            vr="IS",
            tag_path="SeriesNumber",
        )
    ]
    out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    assert body in out
    detected = [body[e.start : e.end] for e in out[body]]
    assert any("2522288856" in f for f in detected), detected
    assert any("20101203" in f for f in detected), detected


@pytest.mark.skipif(not ner_ready(), reason="NER weights not installed")
def test_openmed_detects_id_inside_ds_string() -> None:
    """Live model: digit ID inside a DS string with a float prefix."""
    body = "0.096000 for 8371727310"
    compiled = compile_ner_input(
        [
            NerCompileCell(
                text=body,
                field_name="Rescale Slope",
                tag="(0028,1053)",
                vr="DS",
                tag_path="RescaleSlope",
            )
        ]
    )
    ents = detect_entities(compiled.ner_text, locale="en_US")
    frags = [compiled.ner_text[e.start : e.end] for e in ents]
    _require_openmed_hit(frags, "8371727310")

    ds = Dataset()
    items = [
        MetadataNerItem(
            text=body,
            field_name="Rescale Slope",
            tag="(0028,1053)",
            vr="DS",
            tag_path="RescaleSlope",
        )
    ]
    out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    assert body in out
    detected = [body[e.start : e.end] for e in out[body]]
    assert any("8371727310" in f for f in detected), detected


@pytest.mark.skipif(not ner_ready(), reason="NER weights not installed")
def test_openmed_detects_name_and_date_inside_ds_string() -> None:
    """Live model: person name in DS; DATE fill covers embedded YYYYMMDD."""
    body_name = "62.9 Michelle"
    body_date = "1.25 dated 20101203"
    compiled_name = compile_ner_input(
        [
            NerCompileCell(
                text=body_name,
                field_name="Rescale Slope",
                tag="(0028,1053)",
                vr="DS",
                tag_path="RescaleSlope",
            )
        ]
    )
    ents = detect_entities(compiled_name.ner_text, locale="en_US")
    frags = [compiled_name.ner_text[e.start : e.end] for e in ents]
    _require_openmed_hit(frags, "Michelle")

    ds = Dataset()
    out_name = detect_phi_in_texts(
        ds=ds,
        items=[
            MetadataNerItem(
                text=body_name,
                field_name="Rescale Slope",
                tag="(0028,1053)",
                vr="DS",
                tag_path="RescaleSlope",
            )
        ],
        whitelist=[],
    )
    assert any("Michelle" in body_name[e.start : e.end] for e in out_name[body_name])

    out_date = detect_phi_in_texts(
        ds=ds,
        items=[
            MetadataNerItem(
                text=body_date,
                field_name="Slice Thickness",
                tag="(0018,0050)",
                vr="DS",
                tag_path="SliceThickness",
            )
        ],
        whitelist=[],
    )
    assert any("20101203" in body_date[e.start : e.end] for e in out_date[body_date])
