"""Dataset description edit candidates: RadLex series + LOINC study (modality-scoped)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from anonymizer.controller.ai.harmonize.loinc_study import LoincStudyMatch
from anonymizer.controller.ai.harmonize.pipeline import (
    ensure_min_description_choices,
    series_description_edit_choices,
    study_description_edit_choices,
    study_description_edit_offer,
)
from anonymizer.controller.phi_io import PHI_IndexRecord


def test_series_description_edit_choices_ct_radlex_variants() -> None:
    choices = series_description_edit_choices(
        modality="CT",
        current_description="Ch Ax WO",
    )
    assert choices[0] == "Ch Ax WO"
    assert "Ch Sag WO" in choices
    assert "Ch Cor WO" in choices
    assert "Ch Ax W" in choices
    assert len(choices) >= 4


def test_series_description_edit_choices_xr_radlex_views() -> None:
    choices = series_description_edit_choices(
        modality="CR",
        current_description="Chest AP",
    )
    assert choices[0] == "Chest AP"
    assert "Chest PA" in choices
    assert "Chest Lat" in choices
    assert len(choices) >= 4


def test_series_description_edit_choices_us_mode_variants() -> None:
    choices = series_description_edit_choices(
        modality="US",
        current_description="Abdomen",
    )
    assert choices[0] == "Abdomen"
    assert "Doppler Abdomen" in choices
    assert len(choices) >= 2


def test_series_description_edit_choices_raw_xray_seeds_chest_not_fake_anatomy() -> None:
    choices = series_description_edit_choices(
        modality="CR",
        current_description="XRAY",
    )
    assert "XRAY" not in choices
    assert "Chest AP" in choices
    assert "XRAY AP" not in choices


def test_series_description_edit_choices_empty_seeds_modality_defaults() -> None:
    ct = series_description_edit_choices(modality="CT", current_description="")
    assert ct
    assert ct[0] == "Ch Ax WO"
    xr = series_description_edit_choices(modality="CR", current_description="")
    assert xr
    assert xr[0] == "Chest AP"


def test_series_description_group_choices_raw_expands_catalog() -> None:
    from anonymizer.controller.ai.harmonize.pipeline import series_description_group_choices

    raw = series_description_group_choices(
        modalities=["CR", "CR"],
        current_descriptions=["XRAY", "XRAY"],
    )
    assert "Chest AP" in raw
    assert "Wrist AP" in raw
    harmonized = series_description_group_choices(
        modalities=["CR", "DX"],
        current_descriptions=["Chest AP", "Chest AP"],
    )
    assert "Chest PA" in harmonized
    assert len(harmonized) <= 12
    assert "Wrist AP" not in harmonized


def test_study_description_edit_choices_mr_head_hint_not_abdomen() -> None:
    model = MagicMock()
    model.study_composition_for_harmonize.return_value = (True, False)
    model.get_study_harmonized_description.return_value = None
    model.get_ct_series_harmonized_descriptions.return_value = []
    model.get_tseg_series_modalities.return_value = ["MR"]

    pairs = study_description_edit_choices(
        model,
        "study-mr",
        hint_description="MRI HEAD WITHOUT CON",
    )
    names = [name for name, _code in pairs]
    assert "MRI HEAD WITHOUT CON" not in names
    assert any(n.startswith("MR Brain") for n in names)
    # Hint ranks Head/Brain first; Abdomen may appear later in the full MR catalog.
    brain_idx = next(i for i, n in enumerate(names) if n.startswith("MR Brain"))
    assert brain_idx < 10
    abdomen_idxs = [i for i, n in enumerate(names) if "Abdomen" in n]
    if abdomen_idxs:
        assert brain_idx < abdomen_idxs[0]


def test_classify_and_group_series_choices() -> None:
    from anonymizer.controller.ai.harmonize.pipeline import (
        classify_description_edit_selection,
        find_similar_series_uids,
        find_similar_study_uids,
        series_description_cohort_key,
        series_description_group_choices,
    )

    assert series_description_cohort_key("CT") == "tseg"
    assert series_description_cohort_key("CR") == "XR"
    info = classify_description_edit_selection(series_cohort_keys=["XR", "XR"])
    assert info.kind == "series"
    mixed = classify_description_edit_selection(series_cohort_keys=["XR", "US"])
    assert mixed.kind == "invalid"
    assert mixed.reason == "mixed_modality"
    choices = series_description_group_choices(
        modalities=["CR", "DX"],
        current_descriptions=["Chest AP", "Chest AP"],
    )
    assert "Chest PA" in choices
    peers = find_similar_series_uids(
        [
            ("s1", "CR", "Chest AP"),
            ("s2", "DX", "Chest AP"),
            ("s3", "CR", "Chest PA"),
            ("s4", "US", "Chest AP"),
        ],
        seed_uid="s1",
        seed_modality="CR",
        seed_description="Chest AP",
    )
    assert peers == ["s2"]

    model = MagicMock()
    model.study_composition_for_harmonize.return_value = (False, True)
    model.get_study_harmonized_description.side_effect = lambda uid: {
        "study-a": "XR Chest AP",
        "study-b": "XR Chest AP",
        "study-c": "XR Chest PA",
    }.get(uid)
    model.find_studies_with_planar_series_fingerprint.return_value = []
    study_peers = find_similar_study_uids(
        model,
        "study-a",
        candidates=[
            ("study-a", "XR Chest AP", "XR "),
            ("study-b", "XR Chest AP", "XR "),
            ("study-c", "XR Chest PA", "XR "),
        ],
    )
    assert study_peers == ["study-b"]


def test_ensure_min_description_choices_pads_to_four() -> None:
    padded = ensure_min_description_choices(
        ["Chest AP"],
        ["Chest Lateral", "Chest PA", "Chest 2 Views", "Extra"],
        minimum=4,
    )
    assert padded == ["Chest AP", "Chest Lateral", "Chest PA", "Chest 2 Views"]


def test_ensure_min_description_choices_keeps_existing_when_already_enough() -> None:
    choices = ["A", "B", "C", "D", "E"]
    assert ensure_min_description_choices(choices, ["X", "Y"], minimum=4) == choices


def test_study_description_edit_offer_planar_uses_orm_instance_count() -> None:
    model = MagicMock()
    model.study_composition_for_harmonize.return_value = (False, True)
    model.get_study_harmonized_description.return_value = "XR Chest AP"
    model.get_planar_series_harmonized_descriptions.return_value = ["Chest AP"]
    model.get_planar_series_modalities.return_value = ["CR"]
    model.get_planar_series_instance_count.return_value = 2

    with patch(
        "anonymizer.controller.ai.harmonize.loinc_study.rank_planar_loinc_study_descriptions",
        return_value=[
            LoincStudyMatch("36643-5", "XR Chest 2 Views", 400.0),
            LoincStudyMatch("36572-6", "XR Chest AP", 200.0),
        ],
    ) as mock_rank:
        offer = study_description_edit_offer(model, "study-a")

    assert offer is not None
    assert offer.matches[0].long_common_name == "XR Chest 2 Views"
    mock_rank.assert_called_once()
    assert mock_rank.call_args.kwargs["image_count"] == 2
    assert mock_rank.call_args.kwargs.get("series_paths") is None


def test_study_description_edit_offer_ct_skips_series_paths() -> None:
    model = MagicMock()
    model.study_composition_for_harmonize.return_value = (True, False)
    model.get_study_harmonized_description.return_value = "CT Chest WO contrast"
    model.get_ct_series_harmonized_descriptions.return_value = ["Ch Ax WO"]
    model.get_tseg_series_modalities.return_value = ["CT"]

    with patch(
        "anonymizer.controller.ai.harmonize.loinc_study.build_study_description_ranking",
        return_value=(
            MagicMock(),
            [LoincStudyMatch("29252-4", "CT Chest WO contrast", 500.0)],
            False,
        ),
    ) as mock_rank:
        offer = study_description_edit_offer(model, "study-a")

    assert offer is not None
    mock_rank.assert_called_once()
    assert mock_rank.call_args.kwargs["series_paths"] is None
    assert mock_rank.call_args.kwargs["loinc_prefix"] == "CT "


def test_study_description_edit_choices_pads_from_loinc_prefix_not_index() -> None:
    model = MagicMock()
    model.study_composition_for_harmonize.return_value = (False, True)
    model.get_study_harmonized_description.return_value = "XR Chest AP"
    model.get_planar_series_harmonized_descriptions.return_value = ["Chest AP"]
    model.get_planar_series_modalities.return_value = ["CR"]
    model.get_planar_series_instance_count.return_value = 1

    with (
        patch(
            "anonymizer.controller.ai.harmonize.loinc_study.rank_planar_loinc_study_descriptions",
            return_value=[LoincStudyMatch("36572-6", "XR Chest AP", 500.0)],
        ),
        patch(
            "anonymizer.controller.ai.harmonize.loinc_study.load_loinc_study_descriptions_for_prefix",
            return_value=[
                ("36572-6", "XR Chest AP"),
                ("36643-5", "XR Chest 2 Views"),
                ("36554-4", "XR Chest PA"),
                ("36571-8", "XR Chest Lat"),
            ],
        ) as mock_load,
    ):
        pairs = study_description_edit_choices(model, "study-a", minimum=4)

    names = [name for name, _code in pairs]
    assert names[0] == "XR Chest AP"
    assert "XR Chest 2 Views" in names
    assert "XR Chest PA" in names
    assert len(names) >= 4
    mock_load.assert_called()
    assert mock_load.call_args.args[0].startswith("XR")


def test_study_description_edit_offer_skips_non_loinc_current() -> None:
    model = MagicMock()
    model.study_composition_for_harmonize.return_value = (False, True)
    model.get_study_harmonized_description.return_value = "Custom Study Name"
    model.get_planar_series_harmonized_descriptions.return_value = ["Chest AP"]
    model.get_planar_series_modalities.return_value = ["CR"]
    model.get_planar_series_instance_count.return_value = 1

    with patch(
        "anonymizer.controller.ai.harmonize.loinc_study.rank_planar_loinc_study_descriptions",
        return_value=[LoincStudyMatch("36572-6", "XR Chest AP", 500.0)],
    ):
        offer = study_description_edit_offer(model, "study-a")

    assert offer is not None
    names = [m.long_common_name for m in offer.matches]
    assert "Custom Study Name" not in names
    assert names[0] == "XR Chest AP"


def test_series_description_edit_choices_raw_mr_not_in_options() -> None:
    choices = series_description_edit_choices(
        modality="MR",
        current_description="T1Pre",
        anatomy_hint="MRI HEAD WITHOUT CON",
        full_catalog=True,
    )
    assert "T1Pre" not in choices
    assert any(c.startswith("Brain") or c.startswith("Head") for c in choices)


def test_phi_index_study_description_prefers_harmonized() -> None:
    study = SimpleNamespace(
        series=[],
        anon_date_delta=0,
        study_date="20200101",
        anon_accession_number="A",
        accession_number="B",
        anon_study_uid="anon",
        study_uid="phi",
        description="Original",
        harmonized_description="XR Chest 2 Views",
    )
    phi = SimpleNamespace(
        anon_patient_id="pt",
        patient_id="phi-pt",
        patient_name="Name",
    )
    from anonymizer.controller.phi_io import _phi_index_record_from_orm

    with (
        patch("anonymizer.controller.phi_io._study_index_harmonized", return_value=True),
        patch("anonymizer.controller.phi_io._study_face_blur_label", return_value=""),
        patch("anonymizer.controller.phi_io._study_pixel_phi_removed", return_value=False),
        patch("anonymizer.controller.phi_io._study_pixel_phi_digest", return_value=""),
    ):
        record = _phi_index_record_from_orm(phi, study)

    assert isinstance(record, PHI_IndexRecord)
    assert record.study_description == "XR Chest 2 Views"
    assert record.tree_label() == "XR Chest 2 Views"
