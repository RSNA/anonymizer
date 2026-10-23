"""Unit tests for extractor + radiology guard (prototyping; not in CI)."""

from pathlib import Path

import pytest

from prototyping.metadata_phi.extract import extract_from_file
from prototyping.metadata_phi.guard import filter_spans
from prototyping.metadata_phi.locale_registry import get_locale_pack, list_locales
from prototyping.metadata_phi.pipeline import analyze_text
from prototyping.metadata_phi.types import Span

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "en_US"


def test_locale_pack_en_us() -> None:
    assert "en_US" in list_locales()
    pack = get_locale_pack("en_US")
    assert "mrn" in [c.casefold() for c in pack.cue_words["patient_identifier"]]


def test_guard_drops_mr_breast_as_name() -> None:
    text = "MR BREAST BILATERAL WITH AND WITHOUT CONTRAST"
    raw = [Span("NAME", 0, 9, 0.9, "PERSON")]  # "MR BREAST"
    kept = filter_spans(text, raw, locale="en_US")
    assert kept == []


def test_analyze_finds_mrn_and_not_protocol() -> None:
    spans = analyze_text("Patient Jane Doe MRN: 4455667", engine="regex_spacy", locale="en_US")
    labels = {s.label for s in spans}
    assert "ID" in labels
    assert "NAME" in labels

    neg = analyze_text("Protocol 12 Series 3", engine="regex_spacy", locale="en_US")
    assert not any(s.label == "ID" for s in neg)


def test_synthetic_sr_extracts_text() -> None:
    path = FIXTURES / "synthetic_sr_phi.dcm"
    if not path.is_file():
        pytest.skip("synthetic SR fixture not built")
    chunks = extract_from_file(path, locale="en_US")
    joined = " ".join(c.text for c in chunks)
    assert "Jane Doe" in joined or "MRN" in joined
    assert any("ContentSequence" in c.tag_or_path or c.tag_or_path == "StudyDescription" for c in chunks)
