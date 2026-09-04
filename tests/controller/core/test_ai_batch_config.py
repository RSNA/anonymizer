"""Tests for headless AiBatchConfig JSON."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.ai.blur_face import FaceBlurMode
from anonymizer.controller.ai.remove_pixel_phi import PixelPhiRemovalMode
from anonymizer.controller.ai_batch_config import (
    AiBatchAlgorithm,
    AiBatchConfig,
    AiBatchConfigError,
    AiBatchStudyRef,
    enumerate_studies_from_images_dir,
    resolve_ai_batch_studies,
    validate_ai_batch_config_gates,
)
from anonymizer.controller.ai_batch_process import AiBatchProcessOptions


def test_round_trip_json_to_options() -> None:
    config = AiBatchConfig(
        algorithms=(
            AiBatchAlgorithm.HARMONIZE,
            AiBatchAlgorithm.FACE_BLUR,
            AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        ),
        blur_mode=FaceBlurMode.MEDIAN,
        pixel_phi_removal_mode=PixelPhiRemovalMode.INPAINT,
        use_modality_whitelist=False,
        include_brain_structures=True,
        ct_segmentation_mode="1.5mm",
        mr_segmentation_mode="6mm",
        studies=(AiBatchStudyRef(patient_id="pt1", study_uid="study1"),),
    )

    restored = AiBatchConfig.from_json(config.to_json())

    assert restored == config
    assert restored.to_options() == AiBatchProcessOptions(
        algorithms=restored.algorithms,
        blur_mode=FaceBlurMode.MEDIAN,
        pixel_phi_removal_mode=PixelPhiRemovalMode.INPAINT,
        use_modality_whitelist=False,
        include_brain_structures=True,
    )


def test_from_dict_parses_plan_example() -> None:
    data = json.loads(
        Path("docs/examples/AiBatchConfig.json").read_text(encoding="utf-8")
    )
    config = AiBatchConfig.from_dict(data)

    assert config.algorithms == (
        AiBatchAlgorithm.HARMONIZE,
        AiBatchAlgorithm.FACE_BLUR,
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
    )
    assert config.studies == "all"
    assert config.ct_segmentation_mode == "3mm"


def test_empty_algorithms_raises() -> None:
    with pytest.raises(AiBatchConfigError, match="non-empty"):
        AiBatchConfig.from_dict({"algorithms": []})


def test_unknown_algorithm_raises() -> None:
    with pytest.raises(AiBatchConfigError, match="Unknown algorithm"):
        AiBatchConfig.from_dict({"algorithms": ["not_real"]})


def test_skip_already_processed_false_raises() -> None:
    with pytest.raises(AiBatchConfigError, match="skip_already_processed"):
        AiBatchConfig.from_dict(
            {
                "algorithms": ["harmonize"],
                "skip_already_processed": False,
            }
        )


def test_apply_segmentation_modes() -> None:
    config = AiBatchConfig(
        algorithms=(AiBatchAlgorithm.HARMONIZE,),
        ct_segmentation_mode="6mm",
        mr_segmentation_mode="1.5mm",
    )

    with (
        patch("anonymizer.controller.ai_batch_config.set_ct_segmentation_mode") as set_ct,
        patch("anonymizer.controller.ai_batch_config.set_mr_segmentation_mode") as set_mr,
    ):
        config.apply_segmentation_modes()

    set_ct.assert_called_once_with("6mm")
    set_mr.assert_called_once_with("1.5mm")


def test_validate_gates_fail_fast() -> None:
    config = AiBatchConfig(algorithms=(AiBatchAlgorithm.HARMONIZE,))

    with (
        patch("anonymizer.controller.ai_batch_config.harmonize_allowed", return_value=False),
        pytest.raises(AiBatchConfigError, match="harmonize"),
    ):
        validate_ai_batch_config_gates(config)


def test_resolve_studies_all_from_phi_index() -> None:
    config = AiBatchConfig(algorithms=(AiBatchAlgorithm.HARMONIZE,))
    anon_model = MagicMock()
    record = MagicMock(anon_patient_id="pt1", anon_study_uid="study1")

    with patch("anonymizer.controller.ai_batch_config.build_phi_index", return_value=[record]):
        studies = resolve_ai_batch_studies(
            config,
            images_dir=Path("/images"),
            anon_model=anon_model,
        )

    assert studies == [("pt1", "study1")]


def test_resolve_studies_explicit_path(tmp_path: Path) -> None:
    study_dir = tmp_path / "pt1" / "study1" / "series1"
    study_dir.mkdir(parents=True)
    config = AiBatchConfig(
        algorithms=(AiBatchAlgorithm.HARMONIZE,),
        studies=(AiBatchStudyRef(patient_id="pt1", study_uid="study1"),),
    )

    studies = resolve_ai_batch_studies(
        config,
        images_dir=tmp_path,
        anon_model=MagicMock(),
    )

    assert studies == [("pt1", "study1")]


def test_enumerate_studies_from_images_dir(tmp_path: Path) -> None:
    (tmp_path / "pt1" / "study1").mkdir(parents=True)
    (tmp_path / "pt1" / "study2").mkdir(parents=True)
    (tmp_path / ".hidden").mkdir()

    assert enumerate_studies_from_images_dir(tmp_path) == [
        ("pt1", "study1"),
        ("pt1", "study2"),
    ]


def test_run_headless_ai_batch_invokes_controller(tmp_path: Path) -> None:
    project_path = tmp_path / "ProjectModel.json"
    batch_path = tmp_path / "AiBatchConfig.json"
    project_path.write_text("{}", encoding="utf-8")
    batch_path.write_text(
        json.dumps({"algorithms": ["harmonize"], "studies": "all"}),
        encoding="utf-8",
    )

    controller = MagicMock()
    controller.model.images_dir.return_value = tmp_path / "images"
    controller.ai_batch_process.return_value = MagicMock(cancelled=False, failed=0)

    with (
        patch("anonymizer.anonymizer.create_headless_controller", return_value=controller),
        patch("anonymizer.controller.ai_batch_config.validate_ai_batch_config_gates"),
        patch(
            "anonymizer.controller.ai_batch_config.resolve_ai_batch_studies",
            return_value=[("pt1", "study1")],
        ),
    ):
        from anonymizer.anonymizer import run_HEADLESS_AI_BATCH

        exit_code = run_HEADLESS_AI_BATCH(project_path, batch_path)

    assert exit_code == 0
    controller.ai_batch_process.assert_called_once()
    args, kwargs = controller.ai_batch_process.call_args
    assert args[0] == [("pt1", "study1")]
    assert args[1].algorithms == (AiBatchAlgorithm.HARMONIZE,)
    controller.shutdown.assert_called_once()
    controller.save_model.assert_called_once()
    controller.anonymizer.stop.assert_called_once()
