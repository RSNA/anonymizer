"""Unit tests: Clean Descriptors detect (compile → OpenMed → post-NER)."""

from pathlib import Path
from unittest.mock import patch

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.embedded_phi.metadata.detect import (
    DEFAULT_NER_DETECT_OPTIONS,
    NerDetectOptions,
    detect_metadata_phi,
    entity_count_by_label,
)
from anonymizer.controller.ai.embedded_phi.metadata.ner_compile import NerCompileOptions
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import MetadataNerItem


def test_detect_compile_one_openmed_call() -> None:
    """Step 2 keeps printable Content; step 3 is one call; remap restores offsets."""
    ds = Dataset()
    ds.PatientID = "ANON-1"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        # Default compile: Tag Name: value, joined by spaces; anon not masked.
        assert "Series Description: John Doe," in text
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
        out = detect_metadata_phi(
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
        out = detect_metadata_phi(
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
        out = detect_metadata_phi(ds=ds, items=items, whitelist=["US", "AXILLA"])
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
        out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
    assert "US" not in out
    assert out["Jane"][0].label == "FIRST_NAME"


def test_detect_drops_pure_numeric_whole_cell_false_id() -> None:
    """Whole-cell pure numbers tagged as ID must not empty retain cells (GEMS 0)."""
    ds = Dataset()

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        out: list[Entity] = []
        for needle in ("0", "8371727310"):
            if needle in text:
                i = text.index(needle)
                out.append(Entity(label="ID", start=i, end=i + len(needle)))
        return out

    items = [
        MetadataNerItem(text="0", field_name="PET ir_num_iterations", vr="IS"),
        MetadataNerItem(
            text="Ordered for 8371727310 by PH",
            field_name="Protocol Name",
            vr="LO",
        ),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
    assert "0" not in out
    body = "Ordered for 8371727310 by PH"
    assert body in out
    frags = [body[e.start : e.end] for e in out[body]]
    # expand_entities_for_remove may widen to include leading "for ".
    assert any("8371727310" in frag for frag in frags)


def test_detect_accepts_legacy_newline_period_compile() -> None:
    """Format experiments can still request the historical newline+period layout."""
    ds = Dataset()
    seen: list[str] = []

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        seen.append(text)
        return []

    items = [
        MetadataNerItem(text="A", field_name="Series Description", vr="LO"),
        MetadataNerItem(text="B", field_name="Protocol Name", vr="LO"),
    ]
    legacy = NerDetectOptions(
        compile=NerCompileOptions(line_sep="\n", value_terminator="."),
        chunk_chars=DEFAULT_NER_DETECT_OPTIONS.chunk_chars,
        chunk_overlap=0,
    )
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        detect_metadata_phi(ds=ds, items=items, whitelist=[], detect_options=legacy)
    assert seen and seen[0] == "Series Description: A.\nProtocol Name: B."


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
            "anonymizer.controller.ai.embedded_phi.report.process_report_text.load_modality_whitelist",
            return_value=["Jane"],
        ) as mock_load,
        patch(
            "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
            side_effect=_fake_detect,
        ),
    ):
        out = detect_metadata_phi(ds=ds, items=items, modality="US")
    mock_load.assert_called_once_with(None, "US")
    # Jane still reached the model (post-NER drop).
    assert seen and "Jane" in seen[0]
    assert "Jane Doe" not in out or all("Jane Doe"[e.start : e.end] != "Jane" for e in out.get("Jane Doe", ()))


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
        out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
    frags = ["MAMMO screening for Jane Doe"[e.start : e.end] for e in out["MAMMO screening for Jane Doe"]]
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
        out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
    assert body in out
    frags = [body[e.start : e.end] for e in out[body]]
    assert frags == ["20101203"]
    assert out[body][0].label == "DATE"
    assert out[body][0].raw_label == "compact_da"


def test_detect_pattern_fills_id_site_when_ner_misses() -> None:
    """Post-NER: long ID + at/by site claimed when OpenMed returns nothing."""
    ds = Dataset()
    body = "2D/FGRE LOC at JCH for 8371727310"

    items = [
        MetadataNerItem(text=body, field_name="Series Description", vr="LO"),
    ]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
    frags = {body[e.start : e.end] for e in out[body]}
    assert "JCH" in frags
    assert "8371727310" in frags


def test_detect_pattern_fills_dr_name_when_ner_misses() -> None:
    ds = Dataset()
    body = "Ordered for 867-96-5220 by Dr. Brennan"
    items = [MetadataNerItem(text=body, field_name="Protocol Name", vr="LO")]
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
    frags = {body[e.start : e.end] for e in out[body]}
    assert "Dr. Brennan" in frags
    assert "867-96-5220" in frags


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
        out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
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
        out = detect_metadata_phi(ds=ds, items=items, whitelist=[])
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
        detect_metadata_phi(texts=["Jane"], ds=None)
        raise AssertionError("expected TypeError")
    except TypeError as exc:
        assert "requires ds" in str(exc)


def test_detect_empty_cells_returns_empty() -> None:
    ds = Dataset()
    assert detect_metadata_phi(ds=ds, items=[]) == {}
    assert detect_metadata_phi(texts=[], ds=ds) == {}


def test_detect_explicit_empty_whitelist_skips_modality_load() -> None:
    ds = Dataset()
    with (
        patch(
            "anonymizer.controller.ai.embedded_phi.report.process_report_text.load_modality_whitelist"
        ) as mock_load,
        patch(
            "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
            return_value=[],
        ),
    ):
        detect_metadata_phi(
            ds=ds,
            items=[MetadataNerItem(text="Jane Doe", field_name="Series Description", vr="LO")],
            whitelist=[],
            modality="US",
        )
    mock_load.assert_not_called()


def test_report_metadata_uses_study_whitelist(tmp_path: Path, caplog) -> None:
    """A one-file report series takes the parent study whitelist in Clean Descriptors."""
    project = tmp_path / "project"
    (project / "whitelists").mkdir(parents=True)
    (project / "whitelists" / "us.txt").write_text("AXILLA\n", encoding="utf-8")
    study = tmp_path / "study"
    series = study / "sr"
    series.mkdir(parents=True)
    report = Dataset()
    report.file_meta = FileMetaDataset()
    report.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    report.SOPClassUID = "1.2.840.10008.5.1.4.1.1.88.11"
    report.SOPInstanceUID = generate_uid()
    report.Modality = "SR"
    report.save_as(series / "report.dcm", enforce_file_format=True)
    us = Dataset()
    us.file_meta = FileMetaDataset()
    us.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    us.SOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    us.SOPInstanceUID = generate_uid()
    us.Modality = "US"
    (study / "us").mkdir()
    us.save_as(study / "us" / "image.dcm", enforce_file_format=True)

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        start = text.index("AXILLA")
        return [Entity(label="LOCATION", start=start, end=start + len("AXILLA"))]

    items = [MetadataNerItem(text="Clinic AXILLA", field_name="Study Description", vr="LO")]
    with (
        caplog.at_level("INFO", logger="anonymizer.controller.ai.embedded_phi.metadata.detect"),
        patch(
            "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
            side_effect=_fake_detect,
        ),
    ):
        out = detect_metadata_phi(
            ds=report,
            items=items,
            project_dir=project,
            modality="SR",
            series_dir=series,
        )
    assert out == {}
    assert "Clean Descriptors whitelist source=study modalities=US terms=1 similarity=0.85" in caplog.text


def test_imaging_metadata_uses_own_modality_whitelist(tmp_path: Path, caplog) -> None:
    """Manual Clean Descriptors on an imaging file ignores a sibling modality list."""
    project = tmp_path / "project"
    (project / "whitelists").mkdir(parents=True)
    (project / "whitelists" / "us.txt").write_text("AXILLA\n", encoding="utf-8")
    (project / "whitelists" / "ct.txt").write_text("AXIAL\n", encoding="utf-8")
    study = tmp_path / "study"
    series = study / "ct"
    series.mkdir(parents=True)
    ct = Dataset()
    ct.file_meta = FileMetaDataset()
    ct.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ct.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ct.SOPInstanceUID = generate_uid()
    ct.Modality = "CT"
    ct.save_as(series / "image.dcm", enforce_file_format=True)
    us = Dataset()
    us.file_meta = FileMetaDataset()
    us.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    us.SOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"
    us.SOPInstanceUID = generate_uid()
    us.Modality = "US"
    (study / "us").mkdir()
    us.save_as(study / "us" / "image.dcm", enforce_file_format=True)

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        start = text.index("AXILLA")
        return [Entity(label="LOCATION", start=start, end=start + len("AXILLA"))]

    items = [MetadataNerItem(text="Clinic AXILLA", field_name="Study Description", vr="LO")]
    with (
        caplog.at_level("INFO", logger="anonymizer.controller.ai.embedded_phi.metadata.detect"),
        patch(
            "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
            side_effect=_fake_detect,
        ),
    ):
        out = detect_metadata_phi(
            ds=ct,
            items=items,
            project_dir=project,
            modality="CT",
            series_dir=series,
        )
    text = "Clinic AXILLA"
    spans = [text[e.start : e.end] for e in out.get(text, ())]
    assert "AXILLA" in spans
    assert "Clean Descriptors whitelist source=modality modalities=CT terms=1 similarity=0.85" in caplog.text
