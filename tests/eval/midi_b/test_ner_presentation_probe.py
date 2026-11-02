"""NER presentation probe classifies chunk miss vs isolated hit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from eval.midi_b.ner_presentation_probe import (
    ProbeCase,
    load_underremove_cases,
    probe_case,
    write_probe_report,
)


def test_load_underremove_cases_dedupes(tmp_path: Path) -> None:
    csv_path = tmp_path / "disc.csv"
    # Quote tag_ds — it contains commas.
    csv_path.write_text(
        "index,check_passed,check_score,tag_ds,tag_name,file_value,answer_value,"
        "action,action_text,category,subcategory,modality,class,patient,study,"
        "series,instance,file_name\n"
        '0,0,0,"<(0018,1030)>",Protocol Name,<x>,<Ordered for 8371727310 by PH>,'
        "<text_removed>,<8371727310>,c,s,PT,c,p,st,se,i,f\n"
        '1,0,0,"<(0018,1030)>",Protocol Name,<x>,<Ordered for 8371727310 by PH>,'
        "<text_removed>,<8371727310>,c,s,PT,c,p,st,se,i,f\n"
        '2,0,0,"<(0018,1030)>",Protocol Name,<x>,<Ordered for 8371727310 by PH>,'
        "<text_removed>,<PH>,c,s,PT,c,p,st,se,i,f\n",
        encoding="utf-8",
    )
    cases = load_underremove_cases(csv_path)
    assert len(cases) == 2
    by_needle = {c.needle: c.fail_count for c in cases}
    assert by_needle["8371727310"] == 2
    assert by_needle["PH"] == 1


def test_probe_case_presentation_sensitive() -> None:
    case = ProbeCase(
        field_name="Protocol Name",
        tag_ds="<(0018,1030)>",
        body="Ordered for 8371727310 by PH",
        needle="8371727310",
        fail_count=3,
    )

    def _fake(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        # Multi-tag chunk includes distractors — refuse to tag ID there.
        if "AXIAL T2" in text or "OMNISCAN" in text:
            return []
        if "8371727310" not in text:
            return []
        i = text.index("8371727310")
        return [Entity(label="ID", start=i, end=i + 10, score=0.9)]

    with patch(
        "eval.midi_b.ner_presentation_probe.detect_entities",
        side_effect=_fake,
    ):
        result = probe_case(case)
    assert result.classification == "presentation_sensitive"
    assert result.chunk_hit is False
    assert result.isolated_wrapped_hit is True or result.isolated_raw_hit is True


def test_write_probe_report(tmp_path: Path) -> None:
    case = ProbeCase(
        field_name="Protocol Name",
        tag_ds="<(0018,1030)>",
        body="at FGH",
        needle="FGH",
        fail_count=2,
    )
    with patch(
        "eval.midi_b.ner_presentation_probe.detect_entities",
        return_value=[],
    ):
        result = probe_case(case)
    path = write_probe_report([result], tmp_path)
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "model_gap" in text
    assert (tmp_path / "ner_presentation_probe_cases.json").is_file()
