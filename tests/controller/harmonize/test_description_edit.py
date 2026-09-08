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


def test_series_description_edit_choices_empty_without_current() -> None:
    assert series_description_edit_choices(modality="CT", current_description="") == []


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


def test_study_description_edit_offer_prepends_current_when_missing_from_rank() -> None:
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
    assert offer.matches[0].long_common_name == "Custom Study Name"
    assert offer.matches[1].long_common_name == "XR Chest AP"


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
