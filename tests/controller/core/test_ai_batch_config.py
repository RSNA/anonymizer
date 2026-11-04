"""Tests for headless AiBatchConfig JSON."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.anonymizer import run_HEADLESS_AI_BATCH
from anonymizer.controller.ai.batch_config import (
    AiBatchConfig,
    AiBatchConfigError,
    AiBatchStudyRef,
    EmbeddedPhiFeatureOptions,
    EmbeddedPhiPixelOptions,
    EmbeddedPhiTextOptions,
    FaceBlurFeatureOptions,
    HarmonizeFeatureOptions,
    enumerate_studies_from_images_dir,
    resolve_ai_batch_studies,
    validate_ai_batch_config_gates,
)
from anonymizer.controller.ai.batch_process import AiBatchAlgorithm, AiBatchProcessOptions, AiBatchSummary
from anonymizer.controller.ai.blur_face import FaceBlurMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import PixelPhiRemovalMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrRemoveMode

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_round_trip_json_to_options() -> None:
    config = AiBatchConfig(
        embedded_phi=EmbeddedPhiFeatureOptions(
            enabled=True,
            pixel=EmbeddedPhiPixelOptions(
                enabled=True,
                removal_method=PixelPhiRemovalMode.INPAINT,
                remove_scope=OcrRemoveMode.ALL_TEXT,
                use_exclude_areas=True,
            ),
            metadata=EmbeddedPhiTextOptions(enabled=True, replace_mode="blank"),
            reports=EmbeddedPhiTextOptions(enabled=True, replace_mode="synth"),
        ),
        harmonize=HarmonizeFeatureOptions(
            enabled=True,
            include_brain_structures=True,
            prefer_description_mappings=True,
        ),
        face_blur=FaceBlurFeatureOptions(
            enabled=True,
            blur_mode=FaceBlurMode.MEDIAN,
        ),
        ct_segmentation_mode="1.5mm",
        mr_segmentation_mode="6mm",
        studies=(AiBatchStudyRef(patient_id="pt1", study_uid="study1"),),
    )

    restored = AiBatchConfig.from_json(config.to_json())

    assert restored == config
    emitted = json.loads(config.to_json())
    assert "algorithms" not in emitted
    assert "ocr_remove_mode" not in emitted
    assert emitted["features"]["embedded_phi"]["pixel"]["remove_scope"] == "all_text"
    assert restored.to_options() == AiBatchProcessOptions(
        algorithms=restored.algorithms,
        blur_mode=FaceBlurMode.MEDIAN,
        pixel_phi_removal_mode=PixelPhiRemovalMode.INPAINT,
        ocr_remove_mode=OcrRemoveMode.ALL_TEXT,
        ocr_use_exclude_areas=True,
        include_brain_structures=True,
        prefer_description_mappings=True,
        embedded_phi_pixel_enabled=True,
        embedded_phi_metadata_enabled=True,
        embedded_phi_reports_enabled=True,
        metadata_replace_mode="blank",
        reports_replace_mode="synth",
    )


def test_from_dict_parses_plan_example() -> None:
    data = json.loads(
        (_REPO_ROOT / "docs/en/10-headless/AiBatchConfig.example.json").read_text(
            encoding="utf-8"
        )
    )
    config = AiBatchConfig.from_dict(data)

    assert config.algorithms == (
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        AiBatchAlgorithm.HARMONIZE,
        AiBatchAlgorithm.FACE_BLUR,
    )
    assert config.studies == "all"
    assert config.ct_segmentation_mode == "3mm"
    assert config.embedded_phi.pixel.remove_scope is OcrRemoveMode.PHI_ONLY
    assert config.embedded_phi.metadata.enabled is True
    assert config.embedded_phi.reports.enabled is True


def test_missing_features_raises() -> None:
    with pytest.raises(AiBatchConfigError, match="features must be an object"):
        AiBatchConfig.from_dict({"studies": "all"})


def test_flat_algorithms_rejected() -> None:
    with pytest.raises(AiBatchConfigError, match="features must be an object"):
        AiBatchConfig.from_dict({"algorithms": ["harmonize"], "studies": "all"})


def test_no_features_enabled_raises() -> None:
    with pytest.raises(AiBatchConfigError, match="at least one feature"):
        AiBatchConfig.from_dict(
            {
                "features": {
                    "embedded_phi": {"enabled": False},
                    "harmonize": {"enabled": False},
                    "face_blur": {"enabled": False},
                }
            }
        )


def test_skip_already_processed_false_raises() -> None:
    with pytest.raises(AiBatchConfigError, match="skip_already_processed"):
        AiBatchConfig.from_dict(
            {
                "features": {"harmonize": {"enabled": True}},
                "skip_already_processed": False,
            }
        )


def test_apply_segmentation_modes() -> None:
    config = AiBatchConfig(
        harmonize=HarmonizeFeatureOptions(enabled=True),
        ct_segmentation_mode="6mm",
        mr_segmentation_mode="1.5mm",
    )

    with (
        patch("anonymizer.controller.ai.batch_config.set_ct_segmentation_mode") as set_ct,
        patch("anonymizer.controller.ai.batch_config.set_mr_segmentation_mode") as set_mr,
    ):
        config.apply_segmentation_modes()

    set_ct.assert_called_once_with("6mm")
    set_mr.assert_called_once_with("1.5mm")


def test_validate_gates_fail_fast() -> None:
    config = AiBatchConfig(harmonize=HarmonizeFeatureOptions(enabled=True))

    with (
        patch("anonymizer.controller.ai.batch_config.harmonize_allowed", return_value=False),
        pytest.raises(AiBatchConfigError, match="harmonize"),
    ):
        validate_ai_batch_config_gates(config)


def test_resolve_studies_all_from_phi_index() -> None:
    config = AiBatchConfig(harmonize=HarmonizeFeatureOptions(enabled=True))
    anon_model = MagicMock()
    record = MagicMock(anon_patient_id="pt1", anon_study_uid="study1")

    with patch("anonymizer.controller.ai.batch_config.build_phi_index", return_value=[record]):
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
        harmonize=HarmonizeFeatureOptions(enabled=True),
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
        json.dumps(
            {
                "features": {"harmonize": {"enabled": True}},
                "studies": "all",
            }
        ),
        encoding="utf-8",
    )

    controller = MagicMock()
    controller.model.images_dir.return_value = tmp_path / "images"
    controller.ai_batch_process.return_value = AiBatchSummary(
        series_count=1,
        cancelled=False,
        failed=0,
    )

    with (
        patch("anonymizer.anonymizer.create_headless_controller", return_value=controller),
        patch("anonymizer.anonymizer.validate_ai_batch_config_gates"),
        patch(
            "anonymizer.anonymizer.resolve_ai_batch_studies",
            return_value=[("pt1", "study1")],
        ),
    ):
        exit_code = run_HEADLESS_AI_BATCH(project_path, batch_path)

    assert exit_code == 0
    controller.ai_batch_process.assert_called_once()
    args, _kwargs = controller.ai_batch_process.call_args
    assert args[0] == [("pt1", "study1")]
    assert args[1].algorithms == (AiBatchAlgorithm.HARMONIZE,)
    controller.shutdown.assert_called_once()
    controller.save_model.assert_called_once()
    controller.anonymizer.stop.assert_called_once()
