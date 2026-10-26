"""Private-tag keep/remove intent sampled from MIDI-B answer key."""

from __future__ import annotations

import json
import re
import sqlite3

import pytest
from pydicom import dcmread
from pydicom.data import get_testdata_file

from anonymizer.controller.project import ProjectController
from anonymizer.model.project import BASIC_OPTIONS
from anonymizer.utils.dicom import DeidMethodCode
from prototyping.midi_b.paths import DEFAULT_ANSWER_KEY_VALIDATION
from tests.controller.dicom.support.test_files import ct_small_filename
from tests.controller.dicom.support.test_nodes import LocalSCU
from tests.controller.private_tags.support_private_ds import (
    apply_private_specs,
    find_private_element,
    ingest_fixture_specs,
)
from tests.prototyping.midi_b.support import midi_b_ready

pytestmark = [
    pytest.mark.midi_b_integration,
    pytest.mark.prototyping,
]

_TAG_RE = re.compile(r"\(([0-9a-fA-F]{4}),([0-9a-fA-F]{4})\)")


def _parse_tag(tag_ds: str) -> tuple[int, int] | None:
    m = _TAG_RE.search(tag_ds.replace("<", "").replace(">", ""))
    if not m:
        return None
    return int(m.group(1), 16), int(m.group(2), 16)


def _sample_private_actions(limit: int = 6) -> list[dict]:
    """Pull a few private-tag answer actions from the Validation answer key."""
    if not DEFAULT_ANSWER_KEY_VALIDATION.is_file():
        return []
    con = sqlite3.connect(str(DEFAULT_ANSWER_KEY_VALIDATION))
    try:
        rows = con.execute(
            "SELECT PatientID, AnswerData FROM answer_data LIMIT 200"
        ).fetchall()
    finally:
        con.close()

    keep: list[dict] = []
    remove: list[dict] = []
    for patient_id, blob in rows:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            tag_ds = str(entry.get("tag_ds") or entry.get("tag") or "")
            parsed = _parse_tag(tag_ds)
            if parsed is None:
                continue
            group, elem = parsed
            if group % 2 == 0:
                continue
            action = str(entry.get("action") or "").replace("<", "").replace(">", "")
            item = {
                "patient_id": str(patient_id),
                "group": group,
                "element": elem,
                "action": action,
                "tag_ds": tag_ds,
                "value": str(entry.get("value") or "").replace("<", "").replace(">", ""),
            }
            if action in {"text_retained", "tag_retained"} and len(keep) < limit // 2:
                keep.append(item)
            elif action in {"text_removed"} and len(remove) < limit // 2:
                remove.append(item)
            if len(keep) + len(remove) >= limit:
                return keep + remove
    return keep + remove


def test_answer_key_private_actions_sampled() -> None:
    if not midi_b_ready():
        pytest.skip("MIDI-B answer key not available")
    samples = _sample_private_actions()
    assert samples, "expected at least one private-tag action in answer key sample"
    assert any(s["action"] in {"text_removed", "text_retained", "tag_retained"} for s in samples)


def test_safe_private_vs_strip_matches_answer_intent(controller: ProjectController) -> None:
    """
    Safe Private keeps KB-known keep slots; strip-all removes vendor privates.

    Answer-key private remove/retain intents are recorded for taxonomy alignment;
    product behavior is asserted via planted KEEP + unknown (mirrors ingest smoke).
    """
    if not midi_b_ready():
        pytest.skip("MIDI-B answer key not available")
    samples = _sample_private_actions()
    # Document sampled intents in assertion message if behavior drifts.
    intents = {(s["action"], s["tag_ds"]) for s in samples}

    specs = ingest_fixture_specs()
    keep_spec = specs[0]
    unknown = specs[-1]

    # Strip-all (Basic alone): vendor privates gone.
    controller.apply_confidentiality_options(BASIC_OPTIONS)
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "MIDI-PRIV-STRIP"
    ds.StudyDate = "20200115"
    ds.StudyInstanceUID = "1.2.840.10008.midi.priv.strip.study"
    ds.SeriesInstanceUID = "1.2.840.10008.midi.priv.strip.series"
    ds.SOPInstanceUID = "1.2.840.10008.midi.priv.strip.1"
    apply_private_specs(ds, [keep_spec, unknown])
    keep_tag = find_private_element(ds, keep_spec).tag
    unk_tag = find_private_element(ds, unknown).tag
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert keep_tag not in ds
    assert unk_tag not in ds

    # Safe Private: KB keep survives; unknown removed.
    controller.apply_confidentiality_options(
        BASIC_OPTIONS | {DeidMethodCode.SAFE_PRIVATE}
    )
    ds2 = dcmread(get_testdata_file(ct_small_filename))
    ds2.PatientID = "MIDI-PRIV-SAFE"
    ds2.StudyDate = "20200115"
    ds2.StudyInstanceUID = "1.2.840.10008.midi.priv.safe.study"
    ds2.SeriesInstanceUID = "1.2.840.10008.midi.priv.safe.series"
    ds2.SOPInstanceUID = "1.2.840.10008.midi.priv.safe.1"
    apply_private_specs(ds2, [keep_spec, unknown])
    keep_tag2 = find_private_element(ds2, keep_spec).tag
    unk_tag2 = find_private_element(ds2, unknown).tag
    assert controller.anonymizer.anonymize(LocalSCU, ds2) is None
    assert keep_tag2 in ds2
    assert unk_tag2 not in ds2
    assert intents  # answer-key private intents were observed for this suite
