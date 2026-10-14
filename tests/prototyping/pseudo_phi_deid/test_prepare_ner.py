"""Step 4 prepare: only keep / process / always → NER; private KB wrap."""

from __future__ import annotations

from pydicom.dataset import Dataset

from prototyping.pseudo_phi_deid.pipeline.metadata_ner import (
    ner_field_label,
    prepare_ner_fields,
)


def _keep(ops: dict[str, str]):
    return lambda tag: ops.get(str(tag).upper())


def test_prepare_only_keep_process_always_not_safe() -> None:
    ds = Dataset()
    ds.PatientName = "midi.b-000001"
    ds.PatientID = "midi.b-000001"
    ds.StudyDescription = "PET-CT STUDY"
    ds.Occupation = "Estate agent"
    ds.ManufacturerModelName = "GENESIS_SIGNA"
    ds.DeidentificationMethod = "RSNA DICOM ANONYMIZER"

    resolve = _keep(
        {
            "00100010": "@ptid",
            "00100020": "@ptid",
            "00081030": "",  # keep → NER
            "00102180": "@keep",
            "00081090": "@safe()",
            "00120063": "@always()RSNA DICOM ANONYMIZER",
        }
    )
    _segments, meta, stats = prepare_ner_fields(ds, resolve_tag_keep=resolve)
    paths = {p for p, *_ in meta}
    assert paths == {"StudyDescription", "Occupation", "DeidentificationMethod"}
    assert "ManufacturerModelName" not in paths
    assert "PatientName" not in paths
    assert stats["dropped"] >= 3


def test_private_creators_excluded_from_ner_data_kept() -> None:
    ds = Dataset()
    ds.add_new(0x00730010, "LO", "STENTOR")
    ds.add_new(0x00090010, "LO", "GEMS_IDEN_01")
    ds.add_new(0x00091004, "LO", "SIGNA")
    ds.StudyDescription = "x"
    resolve = _keep({"00081030": "", "00091004": ""})
    _seg, meta, _ = prepare_ner_fields(ds, resolve_tag_keep=resolve)
    paths = {p for p, *_ in meta}
    assert "(0073,0010)" not in paths
    assert "(0009,0010)" not in paths
    assert "(0009,1004)" in paths
    assert ds[0x00730010].value == "STENTOR"  # still on dataset


def test_private_wrap_uses_kb_or_dictionary_name() -> None:
    ds = Dataset()
    ds.add_new(0x00090010, "LO", "GEMS_PETD_01")
    ds.add_new(0x00091001, "LO", "GE Advance")
    label = ner_field_label(ds, "(0009,1001)", ds[0x00091001])
    assert label
