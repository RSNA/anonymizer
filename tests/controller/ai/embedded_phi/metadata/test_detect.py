"""Unit tests: metadata Content PHI detect (pre-NER filter → NER only)."""

from unittest.mock import patch

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.detect import (
    detect_phi_in_texts,
    entity_count_by_label,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import MetadataNerItem


def test_detect_steps_filter_then_ner_only() -> None:
    ds = Dataset()
    ds.PatientID = "ANON-1"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        assert "Series Description:" in text
        assert "1.2.840" not in text
        assert "ANON-1" not in text
        idx = text.index("John")
        return [Entity(label="FIRST_NAME", start=idx, end=idx + 8)]

    items = [
        MetadataNerItem(text="John Doe", field_name="Series Description", vr="LO"),
        MetadataNerItem(text="1.2.840.10008.1.2", field_name="SOP Class UID", vr="UI"),
        MetadataNerItem(text="ANON-1", field_name="Patient ID", vr="LO"),
        MetadataNerItem(text="20190816", field_name="Study Date", vr="DA", is_date=True),
        # CS is non-prose VR — skipped without OCR whitelist.
        MetadataNerItem(text="AP", field_name="View Position", vr="CS"),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ) as mock_ner:
        out = detect_phi_in_texts(ds=ds, items=items)
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
        )
    assert mock_ner.call_count == 1
    assert out["John Smith"] == (Entity(label="FIRST_NAME", start=0, end=10),)


def test_detect_whitelist_masks_terms_before_model_runs() -> None:
    """Whitelisted terms never reach the model (pre-NER veto, not output deletion)."""
    ds = Dataset()
    seen: list[str] = []

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        seen.append(text)
        assert "Axilla" not in text
        idx = text.index("Biopsy")
        return [Entity(label="LOCATION", start=idx, end=idx + 6)]

    items = [
        MetadataNerItem(text="US Biopsy Axilla", field_name="Series Description", vr="LO"),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=["US", "AXILLA"])
    assert seen
    frags = ["US Biopsy Axilla"[e.start : e.end] for e in out["US Biopsy Axilla"]]
    assert frags == ["Biopsy"]


def test_detect_loads_modality_whitelist_when_whitelist_not_passed() -> None:
    """Modality code selects the effective whitelist (pixel SSOT loader)."""
    ds = Dataset()
    seen: list[str] = []

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        seen.append(text)
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
        detect_phi_in_texts(ds=ds, items=items, modality="US")
    mock_load.assert_called_once_with(None, "US")
    assert seen and "Jane" not in seen[0]
    assert "Doe" in seen[0]


def test_detect_keeps_openmed_spans_without_whitelist_drop() -> None:
    """No post-NER whitelist/shape screen — OpenMed spans pass through."""
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
        out = detect_phi_in_texts(ds=ds, items=items)
    frags = [
        "MAMMO screening for Jane Doe"[e.start : e.end] for e in out["MAMMO screening for Jane Doe"]
    ]
    assert frags == ["MAMMO"]


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
