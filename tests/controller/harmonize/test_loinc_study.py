"""Unit tests for LOINC study-description ranking and fingerprints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.harmonize import (
    auto_apply_best_study_descriptions,
    auto_apply_study_description_offer,
    group_study_description_offers_by_fingerprint,
)
from anonymizer.controller.ai.harmonize.loinc_study import (
    LoincStudyMatch,
    StudyDescriptionOffer,
    aggregate_study_from_series_descriptions,
    build_study_description_ranking,
    loinc_study_description_csv_path,
    load_ct_loinc_study_descriptions,
    parse_playbook_series_description,
    preferred_anatomy_from_fractions,
    rank_loinc_study_descriptions,
    ranking_is_ambiguous,
    study_series_description_fingerprint,
)
from anonymizer.controller.series_io import apply_study_description

_CSV = loinc_study_description_csv_path()


@pytest.mark.skipif(not _CSV.is_file(), reason="LOINC StudyDescription CSV missing")
def test_load_ct_loinc_rows():
    rows = load_ct_loinc_study_descriptions(str(_CSV))
    assert len(rows) > 100
    assert all(name.startswith("CT ") for _, name in rows)


def test_parse_playbook_series_description():
    parsed = parse_playbook_series_description("Ch+Abd Ax PortVen")
    assert parsed["body_parts"] == ["Ch", "Abd"]
    assert parsed["plane"] == "Ax"
    assert parsed["contrast"] == "PortVen"
    assert parsed["is_localizer"] is False

    localizer = parse_playbook_series_description("Ch WO Localizer")
    assert localizer["is_localizer"] is True
    assert localizer["contrast"] == "WO"

    thin = parse_playbook_series_description("Ch Ax WO Thin")
    assert thin["slice_thickness"] == "Thin"
    assert thin["plane"] == "Ax"
    assert thin["contrast"] == "WO"

    mpr = parse_playbook_series_description("Brain Sag WO MPR")
    assert mpr["series_type_modifier"] == "MPR"


def test_aggregate_chest_abdomen_with_contrast():
    aggregate = aggregate_study_from_series_descriptions(
        ["Ch Ax PortVen", "Abd Ax PortVen", "Ch WO Localizer"]
    )
    assert aggregate.anatomy_parts == ("Chest", "Abdomen")
    assert aggregate.preferred_anatomy_parts == ("Chest", "Abdomen")
    assert aggregate.contrast_family == "W"
    assert aggregate.diagnostic_series_count == 2


def test_preferred_anatomy_chest_dominant():
    preferred = preferred_anatomy_from_fractions(
        ("Chest", "Abdomen"),
        {"Chest": 0.85, "Abdomen": 0.15},
    )
    assert preferred == ("Chest",)


def test_aggregate_with_chest_dominant_fractions():
    aggregate = aggregate_study_from_series_descriptions(
        ["Ch Ax LateArt", "Ch+Abd Ax PortVen"],
        region_fractions={"Chest": 0.85, "Abdomen": 0.15},
    )
    assert aggregate.anatomy_parts == ("Chest", "Abdomen")
    assert aggregate.preferred_anatomy_parts == ("Chest",)


def test_aggregate_wo_and_w_contrast():
    aggregate = aggregate_study_from_series_descriptions(["Ch Ax WO", "Ch Ax PortVen"])
    assert aggregate.contrast_family == "WO_AND_W"
    assert aggregate.anatomy_parts == ("Chest",)


def test_fingerprint_is_sorted_multiset():
    fp_a = study_series_description_fingerprint(["Ch Ax W", "Abd Ax W", "Ch Ax W"])
    fp_b = study_series_description_fingerprint(["Abd Ax W", "Ch Ax W", "Ch Ax W"])
    fp_c = study_series_description_fingerprint(["Ch Ax W", "Abd Ax W"])
    assert fp_a == fp_b
    assert fp_a != fp_c
    assert fp_a == ("Abd Ax W", "Ch Ax W", "Ch Ax W")


@pytest.mark.skipif(not _CSV.is_file(), reason="LOINC StudyDescription CSV missing")
def test_rank_prefers_chest_and_abdomen_without_fractions():
    matches = rank_loinc_study_descriptions(
        ["Ch Ax PortVen", "Abd Ax PortVen"],
        top_n=8,
        csv_path=str(_CSV),
    )
    assert matches
    top = matches[0].long_common_name
    assert "Chest" in top and "Abdomen" in top
    assert "W contrast" in top
    assert all("Chest" in m.long_common_name and "Abdomen" in m.long_common_name for m in matches)


@pytest.mark.skipif(not _CSV.is_file(), reason="LOINC StudyDescription CSV missing")
def test_rank_prefers_chest_only_when_abdomen_minor():
    matches = rank_loinc_study_descriptions(
        ["Ch Ax LateArt", "Ch+Abd Ax PortVen"],
        top_n=8,
        csv_path=str(_CSV),
        region_fractions={"Chest": 0.85, "Abdomen": 0.15},
    )
    assert matches[0].long_common_name.startswith("CT Chest W contrast")
    assert "Abdomen" not in matches[0].long_common_name
    names = [m.long_common_name for m in matches]
    assert any("Chest and Abdomen" in name for name in names)


@pytest.mark.skipif(not _CSV.is_file(), reason="LOINC StudyDescription CSV missing")
def test_rank_top_n_length():
    matches = rank_loinc_study_descriptions(["Brain Ax WO"], top_n=5, csv_path=str(_CSV))
    assert 1 <= len(matches) <= 5


@pytest.mark.skipif(not _CSV.is_file(), reason="LOINC StudyDescription CSV missing")
def test_rank_brain_maps_to_head_wo_not_ankle():
    """Playbook Brain must rank CT Head WO; never fill top-N with unrelated anatomy."""
    aggregate, matches, ambiguous = build_study_description_ranking(
        ["Brain Ax WO", "Brain Ax WO"],
        top_n=8,
        csv_path=str(_CSV),
    )
    assert aggregate.anatomy_parts == ("Head",)
    assert matches
    assert matches[0].long_common_name == "CT Head WO contrast"
    assert ambiguous is False
    names = [m.long_common_name for m in matches]
    assert all("Head" in name or "Brain" in name for name in names)
    assert not any(
        bad in name
        for name in names
        for bad in ("Ankle", "Adrenal", "Appendix", "Abdominal Aorta", "Elbow", "Airway")
    )


_UNRELATED_MARKERS = (
    "Ankle",
    "Adrenal",
    "Appendix",
    "Abdominal Aorta",
    "Elbow",
    "Airway",
    "Clavicle",
    "Foot",
    "Wrist",
    "Knee",
)


@pytest.mark.skipif(not _CSV.is_file(), reason="LOINC StudyDescription CSV missing")
@pytest.mark.parametrize(
    ("series_descriptions", "must_include", "forbidden_other_regions"),
    [
        (["Brain Ax WO"], ("Head", "Brain"), ("Chest", "Abdomen", "Pelvis", "Ankle")),
        (["Head Ax WO"], ("Head", "Brain"), ("Chest", "Abdomen", "Ankle")),
        (["Neck Ax W"], ("Neck",), ("Ankle", "Adrenal", "Chest")),
        (["Ch Ax PortVen"], ("Chest",), ("Ankle", "Adrenal", "Brain", "Head")),
        (["Abd Ax PortVen"], ("Abdomen",), ("Ankle", "Chest", "Head")),
        (["Pel Ax WO"], ("Pelvis",), ("Ankle", "Adrenal", "Chest")),
        (["AbdPel Ax PortVen"], ("Abdomen", "Pelvis"), ("Ankle", "Head")),
        (["CAP Ax PortVen"], ("Chest", "Abdomen", "Pelvis"), ("Ankle", "Adrenal")),
        (["Ch+Abd Ax PortVen"], ("Chest", "Abdomen"), ("Ankle", "Head")),
        (["Spine Ax WO"], ("Spine",), ("Ankle", "Adrenal", "Chest")),
        (["CSp Ax WO"], ("Cervical", "Spine"), ("Ankle", "Adrenal", "Chest")),
        (["TSp Ax WO"], ("Thoracic", "Spine"), ("Ankle", "Adrenal", "Chest")),
        (["LSp Ax WO"], ("Lumbar", "Spine"), ("Ankle", "Adrenal", "Chest")),
    ],
)
def test_rank_anatomy_family_stays_on_topic(
    series_descriptions: list[str],
    must_include: tuple[str, ...],
    forbidden_other_regions: tuple[str, ...],
):
    matches = rank_loinc_study_descriptions(series_descriptions, top_n=8, csv_path=str(_CSV))
    assert matches, f"expected LOINC matches for {series_descriptions}"
    top = matches[0].long_common_name
    assert any(token in top for token in must_include), top
    for match in matches:
        name = match.long_common_name
        assert not any(marker in name for marker in _UNRELATED_MARKERS), name
        # Every suggestion must still mention required family anatomy.
        assert any(token in name for token in must_include), name


@pytest.mark.skipif(not _CSV.is_file(), reason="LOINC StudyDescription CSV missing")
def test_clear_winner_not_ambiguous_for_chest_dominant():
    aggregate, matches, ambiguous = build_study_description_ranking(
        ["Ch Ax LateArt", "Ch+Abd Ax PortVen"],
        top_n=8,
        csv_path=str(_CSV),
        region_fractions={"Chest": 0.85, "Abdomen": 0.15},
    )
    assert aggregate.preferred_anatomy_parts == ("Chest",)
    assert matches[0].long_common_name.startswith("CT Chest W contrast")
    assert ambiguous is False


def test_ranking_is_ambiguous_when_anatomy_disagrees_and_scores_close():
    aggregate = aggregate_study_from_series_descriptions(
        ["Ch+Abd Ax PortVen"],
        region_fractions={"Chest": 0.55, "Abdomen": 0.45},
    )
    matches = [
        LoincStudyMatch("1", "CT Chest W contrast IV", 100.0),
        LoincStudyMatch("2", "CT Chest and Abdomen W contrast IV", 95.0),
    ]
    assert ranking_is_ambiguous(matches, aggregate) is True


def test_ranking_clear_when_score_gap_large():
    aggregate = aggregate_study_from_series_descriptions(["Ch Ax PortVen"])
    matches = [
        LoincStudyMatch("1", "CT Chest W contrast IV", 1000.0),
        LoincStudyMatch("2", "CT Chest and Abdomen W contrast IV", 900.0),
    ]
    assert ranking_is_ambiguous(matches, aggregate) is False


def test_group_offers_by_fingerprint():
    match = LoincStudyMatch("1", "CT Chest W contrast IV", 1.0)
    offer_a = StudyDescriptionOffer(
        anon_study_uid="study-a",
        fingerprint=("Ch Ax W",),
        matches=(match,),
        peer_study_uids=("study-b",),
        ambiguous=False,
    )
    offer_b = StudyDescriptionOffer(
        anon_study_uid="study-c",
        fingerprint=("Ch Ax W",),
        matches=(match,),
        peer_study_uids=(),
        ambiguous=True,
    )
    offer_d = StudyDescriptionOffer(
        anon_study_uid="study-d",
        fingerprint=("Abd Ax WO",),
        matches=(match,),
        peer_study_uids=(),
    )
    grouped = group_study_description_offers_by_fingerprint([offer_a, offer_b, offer_d])
    assert len(grouped) == 2
    chest = next(o for o in grouped if o.fingerprint == ("Ch Ax W",))
    assert chest.anon_study_uid == "study-a"
    assert set(chest.peer_study_uids) == {"study-b", "study-c"}
    assert chest.ambiguous is True


def test_auto_apply_best_applies_fingerprint_peers():
    match = LoincStudyMatch("42274-1", "CT Chest W contrast IV", 1000.0)
    offer = StudyDescriptionOffer(
        anon_study_uid="study-a",
        fingerprint=("Ch Ax W",),
        matches=(match,),
        peer_study_uids=("study-b",),
        ambiguous=False,
    )
    model = MagicMock()
    model.get_study_harmonized_description.return_value = None
    model.get_anon_patient_id_for_study.side_effect = lambda uid: f"pt-{uid}"

    with pytest.MonkeyPatch.context() as mp:
        applied: list[str] = []

        def fake_apply(study_root, description, anon_model, anon_study_uid, *, loinc_number=None):
            applied.append(anon_study_uid)
            return True

        mp.setattr(
            "anonymizer.controller.ai.harmonize.pipeline.apply_harmonized_study_description",
            fake_apply,
        )
        mp.setattr(
            "anonymizer.controller.ai.harmonize.pipeline.maybe_offer_study_description_harmonize",
            lambda *_args, **_kwargs: offer,
        )
        results = auto_apply_best_study_descriptions(
            images_dir=Path("/tmp/images"),
            anon_model=model,
            anon_study_uids=("study-a",),
        )
    assert len(results) == 1
    assert set(results[0][1]) == {"study-a", "study-b"}
    assert set(applied) == {"study-a", "study-b"}


def test_auto_apply_study_description_offer_uses_top_match():
    match = LoincStudyMatch("42274-1", "CT Chest W contrast IV", 1000.0)
    offer = StudyDescriptionOffer(
        anon_study_uid="study-a",
        fingerprint=("Ch Ax W",),
        matches=(match,),
        peer_study_uids=(),
        ambiguous=False,
    )
    model = MagicMock()
    model.get_study_harmonized_description.return_value = None
    model.get_anon_patient_id_for_study.return_value = "pt-a"

    with pytest.MonkeyPatch.context() as mp:
        seen: dict[str, object] = {}

        def fake_apply(study_root, description, anon_model, anon_study_uid, *, loinc_number=None):
            seen["description"] = description
            seen["loinc"] = loinc_number
            return True

        mp.setattr(
            "anonymizer.controller.ai.harmonize.pipeline.apply_harmonized_study_description",
            fake_apply,
        )
        updated = auto_apply_study_description_offer(
            images_dir=Path("/tmp/images"),
            anon_model=model,
            offer=offer,
        )
    assert updated == ["study-a"]
    assert seen["description"] == "CT Chest W contrast IV"
    assert seen["loinc"] == "42274-1"


def test_auto_apply_best_study_descriptions_applies_ambiguous_top_match():
    from anonymizer.controller.ai.harmonize.pipeline import auto_apply_best_study_descriptions

    match = LoincStudyMatch("36572-6", "XR Chest AP", 500.0)
    offer = StudyDescriptionOffer(
        anon_study_uid="study-a",
        fingerprint=("Chest AP",),
        matches=(match, LoincStudyMatch("36643-5", "XR Chest 2 Views", 490.0)),
        peer_study_uids=(),
        ambiguous=True,
    )
    model = MagicMock()
    model.get_study_harmonized_description.return_value = None
    model.get_anon_patient_id_for_study.return_value = "pt-a"

    with pytest.MonkeyPatch.context() as mp:
        applied: list[str] = []

        def fake_offer(*_args, **_kwargs):
            return offer

        def fake_apply(study_root, description, anon_model, anon_study_uid, *, loinc_number=None):
            applied.append(description)
            return True

        mp.setattr(
            "anonymizer.controller.ai.harmonize.pipeline.maybe_offer_study_description_harmonize",
            fake_offer,
        )
        mp.setattr(
            "anonymizer.controller.ai.harmonize.pipeline.apply_harmonized_study_description",
            fake_apply,
        )
        results = auto_apply_best_study_descriptions(
            images_dir=Path("/tmp/images"),
            anon_model=model,
            anon_study_uids=["study-a"],
        )

    assert len(results) == 1
    assert applied == ["XR Chest AP"]


def test_aggregate_breast_postprocess_mr_series():
    aggregate = aggregate_study_from_series_descriptions(
        [
            "Breast Ax WO Postprocess",
            "Breast Ax WO Postprocess",
        ]
    )
    assert aggregate.anatomy_parts == ("Breast",)
    assert aggregate.contrast_family == "WO"
    assert aggregate.diagnostic_series_count == 2


@pytest.mark.skipif(not _CSV.is_file(), reason="LOINC StudyDescription CSV missing")
def test_rank_mr_breast_study_description():
    _aggregate, matches, ambiguous = build_study_description_ranking(
        ["Breast Ax WO Postprocess"],
        top_n=5,
        loinc_prefix="MR ",
    )
    assert _aggregate.anatomy_parts == ("Breast",)
    assert matches
    assert all(match.long_common_name.startswith("MR Breast") for match in matches)
    assert any("WO contrast" in match.long_common_name for match in matches)


def test_maybe_offer_only_when_study_complete_and_description_empty():
    from anonymizer.controller.ai.harmonize import maybe_offer_study_description_harmonize

    model = MagicMock()
    model.study_is_harmonized.return_value = False
    assert maybe_offer_study_description_harmonize(model, "study-1") is None

    model.study_is_harmonized.return_value = True
    model.get_study_harmonized_description.return_value = "CT Chest WO contrast"
    assert maybe_offer_study_description_harmonize(model, "study-1") is None

    model.get_study_harmonized_description.return_value = None
    model.get_ct_series_harmonized_descriptions.return_value = ["Ch Ax PortVen"]
    model.find_studies_with_series_fingerprint.return_value = ["study-1"]
    model.get_anon_patient_id_for_study.return_value = None
    offer = maybe_offer_study_description_harmonize(model, "study-1", top_n=3)
    assert offer is not None
    assert offer.anon_study_uid == "study-1"
    assert len(offer.matches) <= 3
    assert offer.peer_study_uids == ()
    assert isinstance(offer.ambiguous, bool)


def _write_minimal_dcm(path: Path, *, study_description: str = "OLD") -> None:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "CT"
    ds.StudyDescription = study_description
    ds.Rows = 2
    ds.Columns = 2
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    ds.PixelData = bytes(2 * 2 * 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(path, write_like_original=False)


def test_apply_study_description(tmp_path: Path):
    study_root = tmp_path / "patient" / "study"
    _write_minimal_dcm(study_root / "series-a" / "1.dcm", study_description="OLD")
    _write_minimal_dcm(study_root / "series-b" / "2.dcm", study_description="OLD")
    assert apply_study_description(
        study_root,
        "CT Chest W contrast IV",
        loinc_number="42274-1",
    )
    from pydicom import dcmread

    for dcm in study_root.rglob("*.dcm"):
        ds = dcmread(dcm)
        assert str(ds.StudyDescription) == "CT Chest W contrast IV"
        assert hasattr(ds, "ProcedureCodeSequence")
        item = ds.ProcedureCodeSequence[0]
        assert str(item.CodeValue) == "42274-1"
        assert str(item.CodingSchemeDesignator) == "LN"
        assert str(item.CodeMeaning) == "CT Chest W contrast IV"
