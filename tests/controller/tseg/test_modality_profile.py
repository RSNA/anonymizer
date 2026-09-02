"""CT modality-profile invariants — must not drift when MR support is added."""

from __future__ import annotations

from anonymizer.controller.ai.tseg.config import FACE_MASK_FILENAME, FACE_TASK, ROI_SUBSET
from anonymizer.controller.ai.tseg.modality_profile import (
    CT_ANATOMY_TASK_IDS_3MM,
    CT_FACE_TASK_ID,
    ROI_SUBSET_MR,
    ct_modality_profile,
    mr_modality_profile,
    profile_for_modality,
)
from anonymizer.controller.ai.tseg.segment import STRUCTURE_TO_REGION
from anonymizer.utils.modalities import (
    is_ct_modality,
    is_mr_modality,
    is_tseg_modality,
    normalize_modality,
    series_is_tseg_eligible,
)


def test_normalize_modality_maps_mri():
    assert normalize_modality("mri") == "MR"
    assert normalize_modality("MR") == "MR"
    assert normalize_modality("ct") == "CT"
    assert normalize_modality(None) == ""


def test_tseg_modality_helpers():
    assert is_ct_modality("CT")
    assert is_mr_modality("MRI")
    assert is_tseg_modality("CT") and is_tseg_modality("MR")
    assert not is_tseg_modality("US")
    assert series_is_tseg_eligible("MR")
    assert not series_is_tseg_eligible("DX")


def test_ct_profile_matches_production_defaults(monkeypatch, tmp_path):
    from anonymizer.controller.ai.tseg import config as tseg_config

    monkeypatch.setenv("TOTALSEG_HOME_DIR", str(tmp_path))
    tseg_config.clear_segmentation_mode_cache()
    tseg_config.set_ct_segmentation_mode("3mm")

    profile = ct_modality_profile()
    assert profile.modality == "CT"
    assert profile.anatomy_task == "total"
    assert profile.face_task == FACE_TASK == "face"
    assert profile.face_task_id == CT_FACE_TASK_ID == 303
    assert profile.roi_subset == ROI_SUBSET
    assert profile.structure_to_region == STRUCTURE_TO_REGION
    assert profile.enable_contrast_phase is True
    assert profile.face_fill == "hu_band"
    assert profile.loinc_prefix == "CT "
    assert profile.face_mask_filename == FACE_MASK_FILENAME == "face.nii.gz"
    # 3mm default mode uses tasks 297+298.
    assert profile.anatomy_task_ids == CT_ANATOMY_TASK_IDS_3MM


def test_profile_for_modality_ct_equals_ct_factory():
    assert profile_for_modality("CT") == ct_modality_profile()
    assert profile_for_modality("US") is None


def test_mr_profile_is_additive_not_ct(monkeypatch, tmp_path):
    from anonymizer.controller.ai.tseg import config as tseg_config

    monkeypatch.setenv("TOTALSEG_HOME_DIR", str(tmp_path))
    tseg_config.clear_segmentation_mode_cache()
    tseg_config.set_mr_segmentation_mode("3mm")

    profile = mr_modality_profile()
    assert profile.modality == "MR"
    assert profile.anatomy_task == "total_mr"
    assert profile.face_task == "face_mr"
    assert profile.face_task_id == 856
    assert profile.roi_subset == ROI_SUBSET_MR
    assert profile.roi_subset != ROI_SUBSET
    assert profile.enable_contrast_phase is False
    assert profile.face_fill == "intensity_percentile"
    assert profile.loinc_prefix == "MR "
    assert profile.face_mask_filename == "face_mr.nii.gz"
    assert "lung_left" in profile.structure_to_region
    assert profile.structure_to_region["lung_left"] == "Chest"
    assert profile.structure_to_region["brain"] == "Head"
    assert profile.anatomy_task_ids == (852,)
