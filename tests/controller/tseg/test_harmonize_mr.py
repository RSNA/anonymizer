"""MR Harmonize / Face Blur gate tests — keep CT suites untouched."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from pydicom import Dataset

from anonymizer.controller.ai.blur_face import (
    CachedRegionSignal,
    FaceBlurGateDecision,
    FaceBlurGateReason,
    FaceBlurMode,
    blur_face_intensity_volume,
    blur_face_volume_for_profile,
    evaluate_face_blur_eligibility,
)
from anonymizer.controller.ai.harmonize.pipeline import _load_ct_series_dataset, _load_tseg_series_dataset
from anonymizer.controller.ai.tseg.dicom_geometry import SeriesGeometryResult
from anonymizer.controller.ai.tseg.modality_profile import (
    mr_modality_profile,
    profile_for_modality,
)
from anonymizer.controller.ai.tseg.segment import run_face_segmentation, run_segmentation
from anonymizer.view.series.series import harmonize_button_visible


def _geometry(*, ts_suitable: bool = True) -> SeriesGeometryResult:
    return SeriesGeometryResult(
        plane="axial",
        plane_confidence=0.95,
        slice_normal_lps=(0.0, 0.0, 1.0),
        plane_angles_deg={"axial": 5.0, "coronal": 85.0, "sagittal": 85.0},
        dimensionality="volume_3d",
        n_slices=24,
        through_plane_extent_mm=120.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=ts_suitable,
        metadata_suspect=False,
        method="dicom_headers",
        notes="" if ts_suitable else "Not a diagnostic 3D volume (localizer_2d)",
    )


def test_profile_for_mr_and_mri():
    assert profile_for_modality("MR") is not None
    assert profile_for_modality("MRI") is not None
    assert profile_for_modality("MR").anatomy_task == "total_mr"
    assert profile_for_modality("US") is None


def test_harmonize_button_visible_for_mr():
    assert harmonize_button_visible(
        harmonize_models_ready=True,
        modality="MR",
        already_harmonized=False,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=True,
        modality="US",
        already_harmonized=False,
    )


def test_face_blur_eligibility_allows_mr_when_weights_ready(tmp_path: Path):
    series = tmp_path / "mr_series"
    series.mkdir()
    with (
        patch(
            "anonymizer.controller.ai.blur_face.pipeline.cached_region_signal",
            return_value=CachedRegionSignal.HEAD,
        ),
        patch("anonymizer.controller.ai.tseg.model_cache.mr_face_model_ready", return_value=True),
    ):
        result = evaluate_face_blur_eligibility(
            series,
            modality="MR",
            geometry=_geometry(),
            enable_tseg_face=True,
        )
    assert result.decision is FaceBlurGateDecision.ALLOW
    assert result.reason is FaceBlurGateReason.CACHED_REGIONS_HEAD


def test_face_blur_eligibility_blocks_mr_without_weights(tmp_path: Path):
    series = tmp_path / "mr_series"
    series.mkdir()
    with patch("anonymizer.controller.ai.tseg.model_cache.mr_face_model_ready", return_value=False):
        result = evaluate_face_blur_eligibility(
            series,
            modality="MR",
            geometry=_geometry(),
            enable_tseg_face=True,
        )
    assert result.decision is FaceBlurGateDecision.BLOCK
    assert result.reason is FaceBlurGateReason.FEATURE_DISABLED


def test_ct_loader_rejects_mr_tseg_loader_accepts():
    ds = MagicMock()
    ds.Modality = "MR"
    with patch(
        "anonymizer.controller.ai.harmonize.pipeline._load_series_dataset",
        return_value=ds,
    ):
        assert _load_ct_series_dataset(Path("/tmp/x")) is None
        assert _load_tseg_series_dataset(Path("/tmp/x")) is ds


def test_run_segmentation_passes_total_mr_task(tmp_path: Path):
    totalseg = MagicMock()
    out = tmp_path / "seg"
    with (
        patch(
            "anonymizer.controller.ai.tseg.segment._require_totalsegmentator",
            return_value=totalseg,
        ),
        patch("anonymizer.controller.ai.tseg.segment.sequential_ml_context"),
    ):
        run_segmentation(
            tmp_path / "in.nii.gz",
            out,
            task="total_mr",
            roi_subset=["brain", "heart"],
            n_slices=10,
        )
    kwargs = totalseg.call_args.kwargs
    assert kwargs["task"] == "total_mr"
    assert kwargs["roi_subset"] == ["brain", "heart"]


def test_run_face_segmentation_passes_face_mr(tmp_path: Path):
    totalseg = MagicMock()
    out = tmp_path / "seg"
    out.mkdir()

    def _write_ts_face_output(*_args, **_kwargs):
        # TotalSegmentator writes class label "face" even for task face_mr.
        (out / "face.nii.gz").write_bytes(b"x")

    totalseg.side_effect = _write_ts_face_output
    with (
        patch(
            "anonymizer.controller.ai.tseg.segment._require_totalsegmentator",
            return_value=totalseg,
        ),
        patch("anonymizer.controller.ai.tseg.segment.sequential_ml_context"),
    ):
        run_face_segmentation(
            tmp_path / "in.nii.gz",
            out,
            face_task="face_mr",
            face_mask_filename="face_mr.nii.gz",
        )
    assert totalseg.call_args.kwargs["task"] == "face_mr"
    assert (out / "face_mr.nii.gz").is_file()
    assert not (out / "face.nii.gz").exists()


def test_blur_face_intensity_volume_fills_mask():
    volume = np.ones((4, 8, 8), dtype=np.float32) * 100.0
    volume[:, 2:6, 2:6] = 200.0
    mask = np.zeros((4, 8, 8), dtype=bool)
    mask[:, 2:6, 2:6] = True
    out = blur_face_intensity_volume(volume, mask, low_percentile=10, high_percentile=20)
    assert out.shape == volume.shape
    assert np.allclose(out[:, 0, 0], 100.0)
    assert float(out[0, 4, 4]) < 150.0


def test_blur_dispatch_mr_fill_noise_uses_intensity():
    profile = mr_modality_profile()
    volume = np.random.default_rng(0).normal(50, 10, size=(2, 16, 16)).astype(np.float32)
    mask = np.zeros((2, 16, 16), dtype=bool)
    mask[:, 4:12, 4:12] = True
    with patch(
        "anonymizer.controller.ai.blur_face.pipeline.blur_face_intensity_volume",
        wraps=blur_face_intensity_volume,
    ) as intensity:
        blur_face_volume_for_profile(
            volume,
            mask,
            profile=profile,
            blur_mode=FaceBlurMode.FILL_NOISE,
        )
        intensity.assert_called_once()


def test_loinc_mr_prefix_ranks_mr_rows():
    from anonymizer.controller.ai.harmonize.loinc_study import (
        load_loinc_study_descriptions_for_prefix,
        rank_loinc_study_descriptions,
    )

    mr_rows = load_loinc_study_descriptions_for_prefix("MR ")
    assert mr_rows
    assert all(name.startswith("MR ") for _, name in mr_rows[:20])

    matches = rank_loinc_study_descriptions(
        ["Head Ax WO"],
        top_n=5,
        loinc_prefix="MR ",
        region_fractions={"Head": 1.0},
    )
    assert matches
    assert all(m.long_common_name.startswith("MR ") for m in matches)


def test_mr_combined_vertebrae_excluded_from_static_profile():
    profile = mr_modality_profile()
    assert "vertebrae" not in profile.structure_to_region


@pytest.mark.parametrize(
    ("series_description", "expected_region"),
    [
        ("THORACIC SPINE STIR", "Chest"),
        ("LUMBAR SPINE T2", "Abdomen"),
        ("CERVICAL SPINE T1", "Head"),
        ("", "Chest"),
    ],
)
def test_infer_mr_vertebrae_region_from_metadata(series_description: str, expected_region: str) -> None:
    from anonymizer.controller.ai.tseg.modality_profile import infer_mr_vertebrae_region

    ds = Dataset()
    ds.SeriesDescription = series_description
    assert infer_mr_vertebrae_region(ds) == expected_region


def test_mr_vertebrae_mask_maps_to_playbook_region() -> None:
    from anonymizer.controller.ai.tseg.modality_profile import mr_structure_to_region_for_series
    from anonymizer.controller.ai.tseg.segment import body_parts_present, dominant_region_from_voxels

    ds = Dataset()
    ds.SeriesDescription = "THORACIC SPINE T2"
    mapping = mr_structure_to_region_for_series(ds)
    region = dominant_region_from_voxels({"vertebrae": 50_000}, structure_to_region=mapping)
    assert region.dominant_region == "Chest"
    assert body_parts_present(region.region_voxels) == "Chest"


def test_mr_harmonize_skips_contrast_and_merges_wo(tmp_path: Path):
    from anonymizer.controller.ai.harmonize import harmonize_series
    from anonymizer.controller.ai.tseg.segment import TS_result

    series = tmp_path / "mr_abd"
    series.mkdir()
    (series / "1.dcm").write_bytes(b"")

    ds = MagicMock()
    ds.Modality = "MR"
    ds.SeriesDescription = "ABD T2"
    ds.ProtocolName = ""
    ds.StudyDescription = ""
    ds.DerivationDescription = ""
    ds.ContrastBolusAgent = ""
    ds.ContrastBolusRoute = ""
    ds.ContrastBolusVolume = ""
    ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL"]
    ds.get = lambda key, default=None: getattr(ds, key, default)

    geometry = _geometry()
    region = TS_result(
        series_directory=series,
        dominant_region="Abdomen",
        body_parts_present="Abdomen",
        multi_region=False,
        region_fraction=0.85,
        iv_contrast=False,
        contrast_phase="",
        phase_probability=0.0,
        structures_present={"liver": 50000, "kidney_left": 20000},
    )

    with (
        patch("anonymizer.controller.ai.harmonize.pipeline.resolve_series_geometry", return_value=geometry),
        patch(
            "anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions",
            return_value=(region, series / "vol.nii.gz"),
        ),
        patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast") as mock_contrast,
        patch("anonymizer.controller.ai.harmonize.pipeline.resolve_profile_for_series", return_value=mr_modality_profile()),
        patch("anonymizer.controller.ai.harmonize.pipeline._load_series_dataset", return_value=ds),
        patch("anonymizer.controller.ai.harmonize.pipeline.ENABLE_TS_CONTRAST", True),
    ):
        results = harmonize_series([series])

    merged = results[0]
    assert merged.error is None
    assert merged.tseg is not None
    assert merged.tseg.contrast_phase == ""
    assert merged.playbook is not None
    assert merged.playbook.iv_contrast_code == "WO"
    assert "Abd" in merged.radlex_series_description
    mock_contrast.assert_not_called()


def test_mr_iv_contrast_row_uses_dicom_not_ts_phase():
    from pydicom import Dataset

    from anonymizer.controller.ai.harmonize.playbook import (
        build_playbook_attributes,
        map_mr_iv_contrast_from_dicom,
        playbook_iv_contrast_row_values,
    )
    from anonymizer.controller.ai.tseg.segment import TS_result

    ds = Dataset()
    ds.Modality = "MR"
    ds.SeriesDescription = "BRAIN T1 +C"
    ds.ContrastBolusAgent = "GADOLINIUM"

    code, evidence = map_mr_iv_contrast_from_dicom(ds)
    assert code == "W"
    assert "GADOLINIUM" in evidence or "+C" in evidence or "Series/protocol" in evidence

    tseg = TS_result(
        series_directory=Path("/tmp/x"),
        dominant_region="Head",
        body_parts_present="Head",
        multi_region=False,
        region_fraction=1.0,
        iv_contrast=False,
        contrast_phase="",
        phase_probability=0.0,
        structures_present={"brain": 50000},
    )
    attributes = build_playbook_attributes(tseg, _geometry(), ds=ds)
    element, row_code, value, row_evidence, source = playbook_iv_contrast_row_values(
        attributes,
        tseg=tseg,
        ds=ds,
    )
    assert element == "IV Contrast"
    assert row_code == "W"
    assert value == "With contrast"
    assert "TotalSegmentator" not in source
    assert "DICOM" in source
    assert row_evidence != "native"


def test_mr_harmonize_falls_back_to_dicom_when_ts_regions_empty(tmp_path: Path):
    from anonymizer.controller.ai.harmonize import harmonize_series
    from anonymizer.controller.ai.tseg.segment import TS_result

    series = tmp_path / "mr_spine"
    series.mkdir()
    (series / "1.dcm").write_bytes(b"")

    ds = MagicMock()
    ds.Modality = "MR"
    ds.SeriesDescription = "THORACIC SPINE T2"
    ds.ProtocolName = ""
    ds.StudyDescription = ""
    ds.BodyPartExamined = ""
    ds.DerivationDescription = ""
    ds.ContrastBolusAgent = ""
    ds.ContrastBolusRoute = ""
    ds.ContrastBolusVolume = ""
    ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL"]
    ds.get = lambda key, default=None: getattr(ds, key, default)

    geometry = _geometry()
    failed_regions = TS_result(
        series_directory=series,
        dominant_region="",
        body_parts_present="",
        multi_region=False,
        region_fraction=0.0,
        iv_contrast=False,
        contrast_phase="",
        phase_probability=0.0,
        error="No anatomy regions detected in volume",
    )

    with (
        patch("anonymizer.controller.ai.harmonize.pipeline.resolve_series_geometry", return_value=geometry),
        patch(
            "anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions",
            return_value=(failed_regions, series / "vol.nii.gz"),
        ),
        patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast") as mock_contrast,
        patch("anonymizer.controller.ai.harmonize.pipeline.resolve_profile_for_series", return_value=mr_modality_profile()),
        patch("anonymizer.controller.ai.harmonize.pipeline._load_series_dataset", return_value=ds),
        patch("anonymizer.controller.ai.harmonize.pipeline.ENABLE_TS_CONTRAST", True),
    ):
        results = harmonize_series([series])

    merged = results[0]
    assert merged.error is None
    assert merged.playbook is not None
    assert merged.playbook.body_part_code == "Spine"
    assert merged.playbook.iv_contrast_code == "WO"
    assert "Spine" in merged.radlex_series_description
    mock_contrast.assert_not_called()


    profile = mr_modality_profile()
    assert "vertebrae" not in profile.structure_to_region
    assert profile.structure_to_region["lung_left"] == "Chest"
    assert profile.structure_to_region["sacrum"] == "Abdomen"
