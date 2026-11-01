"""Unit tests: Clean Descriptors detect (frozen compile → OpenMed → post-NER)."""

from unittest.mock import patch

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.detect import (
    detect_phi_in_texts,
    entity_count_by_label,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import MetadataNerItem


def test_detect_frozen_compile_one_openmed_call() -> None:
    """Step 2 keeps printable Content; step 3 is one call; remap restores offsets."""
    ds = Dataset()
    ds.PatientID = "ANON-1"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        # Frozen compile: Tag Name: value. lines; punctuation kept; anon not masked.
        assert "Series Description: John Doe." in text
        assert "1.2.840" not in text  # UI skipped at collect
        assert "G4EGU8PGUYWPI" not in text  # @safe never reaches NER
        assert "ANON-1" in text  # post-NER anon drop only
        idx = text.index("John Doe")
        return [Entity(label="FIRST_NAME", start=idx, end=idx + 8)]

    items = [
        MetadataNerItem(text="John Doe", field_name="Series Description", vr="LO"),
        MetadataNerItem(text="1.2.840.10008.1.2", field_name="SOP Class UID", vr="UI"),
        MetadataNerItem(text="ANON-1", field_name="Patient ID", vr="LO"),
        MetadataNerItem(
            text="G4EGU8PGUYWPI",
            field_name="Device Serial Number",
            tag="(0018,1000)",
            vr="LO",
            tag_path="DeviceSerialNumber",
            script_operation="@safe()",
        ),
        MetadataNerItem(text="20190816", field_name="Study Date", vr="DA", is_date=True),
        MetadataNerItem(text="AP", field_name="View Position", vr="CS"),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ) as mock_ner:
        out = detect_phi_in_texts(
            ds=ds,
            items=items,
            whitelist=[],
            script_operations={"00181000": "@safe()"},
        )
    assert mock_ner.call_count == 1
    assert out["John Doe"][0] == Entity(label="FIRST_NAME", start=0, end=8)
    assert "1.2.840.10008.1.2" not in out
    assert "AP" not in out


def test_detect_plain_texts_batches_prose() -> None:
    ds = Dataset()

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        if "John Smith" not in text:
            return []
        idx = text.index("John Smith")
        return [Entity(label="FIRST_NAME", start=idx, end=idx + 10)]

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ) as mock_ner:
        out = detect_phi_in_texts(
            ["John Smith", "John Smith", "  ", "100000", ""],
            ds,
            whitelist=[],
        )
    assert mock_ner.call_count == 1
    assert out["John Smith"] == (Entity(label="FIRST_NAME", start=0, end=10),)


def test_detect_whitelist_drops_after_ner_not_before() -> None:
    """Whitelist terms still reach the model; matching spans are dropped after."""
    ds = Dataset()
    seen: list[str] = []

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        seen.append(text)
        assert "Axilla" in text or "AXILLA" in text.upper()
        out: list[Entity] = []
        for needle, label in (("US", "LOCATION"), ("Biopsy", "LOCATION"), ("Axilla", "LOCATION")):
            if needle in text:
                i = text.index(needle)
                out.append(Entity(label=label, start=i, end=i + len(needle)))
        return out

    items = [
        MetadataNerItem(text="US Biopsy Axilla", field_name="Series Description", vr="LO"),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=["US", "AXILLA"])
    assert seen and "Axilla" in seen[0]
    frags = ["US Biopsy Axilla"[e.start : e.end] for e in out["US Biopsy Axilla"]]
    assert frags == ["Biopsy"]


def test_detect_always_allows_dicom_vr_code_spans() -> None:
    """Post-NER always drops spans that are only a DICOM VR code (e.g. Rescale Type US)."""
    ds = Dataset()

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        out: list[Entity] = []
        for needle, label in (("US", "LOCATION"), ("Jane", "FIRST_NAME")):
            if needle in text:
                i = text.index(needle)
                out.append(Entity(label=label, start=i, end=i + len(needle)))
        return out

    items = [
        MetadataNerItem(text="US", field_name="Rescale Type", vr="LO"),
        MetadataNerItem(text="Jane", field_name="Series Description", vr="LO"),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    assert "US" not in out
    assert out["Jane"][0].label == "FIRST_NAME"


def test_detect_loads_modality_whitelist_when_whitelist_not_passed() -> None:
    """Modality code selects the effective whitelist (pixel SSOT loader)."""
    ds = Dataset()
    seen: list[str] = []

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        seen.append(text)
        if "Jane" in text:
            i = text.index("Jane")
            return [Entity(label="FIRST_NAME", start=i, end=i + 4)]
        return []

    items = [MetadataNerItem(text="Jane Doe", field_name="Series Description", vr="LO")]
    with (
        patch(
            "anonymizer.controller.ai.embedded_phi.metadata.detect.load_modality_whitelist",
            return_value=["Jane"],
        ) as mock_load,
        patch(
            "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
            side_effect=_fake_detect,
        ),
    ):
        out = detect_phi_in_texts(ds=ds, items=items, modality="US")
    mock_load.assert_called_once_with(None, "US")
    # Jane still reached the model (post-NER drop).
    assert seen and "Jane" in seen[0]
    assert "Jane Doe" not in out or all(
        "Jane Doe"[e.start : e.end] != "Jane" for e in out.get("Jane Doe", ())
    )


def test_detect_keeps_non_whitelist_openmed_spans() -> None:
    ds = Dataset()

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        idx = text.index("MAMMO")
        return [Entity(label="FIRST_NAME", start=idx, end=idx + 5, raw_label="first_name")]

    items = [
        MetadataNerItem(
            text="MAMMO screening for Jane Doe",
            field_name="StudyDescription",
            vr="LO",
        ),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    frags = [
        "MAMMO screening for Jane Doe"[e.start : e.end] for e in out["MAMMO screening for Jane Doe"]
    ]
    assert frags == ["MAMMO"]


def test_detect_merges_compact_date_when_ner_misses() -> None:
    """Post-NER: bare YYYYMMDD after series prose → DATE on original Content."""
    ds = Dataset()
    body = "PET-CT SERIES 20101203"

    items = [
        MetadataNerItem(text=body, field_name="Series Description", vr="LO"),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    assert body in out
    frags = [body[e.start : e.end] for e in out[body]]
    assert frags == ["20101203"]
    assert out[body][0].label == "DATE"
    assert out[body][0].raw_label == "compact_da"


def test_detect_includes_pure_series_number_is_for_date_fill() -> None:
    """Pure IS Series Number is in NER input; compact DATE fill claims YYYYMMDD."""
    ds = Dataset()
    body = "20101203"
    items = [
        MetadataNerItem(
            text=body,
            field_name="Series Number",
            vr="IS",
            tag="00200011",
            tag_path="SeriesNumber",
        ),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    assert body in out
    assert body[out[body][0].start : out[body][0].end] == "20101203"
    assert out[body][0].label == "DATE"


def test_detect_ner_wins_over_overlapping_date_pattern() -> None:
    """If NER already covers the digit run, do not duplicate a pattern DATE."""
    ds = Dataset()
    body = "scan 20101203 done"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        idx = text.index("20101203")
        return [Entity(label="DATE", start=idx, end=idx + 8, raw_label="date", score=0.9)]

    items = [MetadataNerItem(text=body, field_name="Image Comments", vr="LT")]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=[])
    assert len(out[body]) == 1
    assert out[body][0].raw_label == "date"
    assert body[out[body][0].start : out[body][0].end] == "20101203"


def test_entity_count_by_label() -> None:
    ents = {
        "a": (Entity(label="FIRST_NAME", start=0, end=1), Entity(label="ID", start=2, end=3)),
        "b": (Entity(label="FIRST_NAME", start=0, end=2),),
    }
    assert entity_count_by_label(ents) == {"FIRST_NAME": 2, "ID": 1}


def test_detect_requires_dataset() -> None:
    try:
        detect_phi_in_texts(texts=["Jane"], ds=None)
        raise AssertionError("expected TypeError")
    except TypeError as exc:
        assert "requires ds" in str(exc)


def test_detect_empty_cells_returns_empty() -> None:
    ds = Dataset()
    assert detect_phi_in_texts(ds=ds, items=[]) == {}
    assert detect_phi_in_texts(texts=[], ds=ds) == {}


def test_detect_explicit_empty_whitelist_skips_modality_load() -> None:
    ds = Dataset()
    with (
        patch(
            "anonymizer.controller.ai.embedded_phi.metadata.detect.load_modality_whitelist"
        ) as mock_load,
        patch(
            "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
            return_value=[],
        ),
    ):
        detect_phi_in_texts(
            ds=ds,
            items=[MetadataNerItem(text="Jane Doe", field_name="Series Description", vr="LO")],
            whitelist=[],
            modality="US",
        )
    mock_load.assert_not_called()
