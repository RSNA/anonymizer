"""Tests for TotalSegmentator XGBoost contrast phase helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.ai.tseg.contrast import (
    CONTRAST_ORGANS_HN,
    _apply_hu_gate,
    _run_contrast_classifier,
    contrast_phase_cache_is_valid,
    estimate_contrast_remaining_sec,
    format_cached_contrast_phase_message,
    format_cached_organ_hu_message,
    format_cached_vessel_hu_message,
    format_contrast_organ_hu_summary,
    format_contrast_vessel_hu_summary,
    head_dominant_limited_fov,
    hu_gate_iv_contrast,
    needs_head_neck_vessel_stats,
    phase_to_iv_contrast,
    predict_contrast_phase,
    resolve_contrast_device,
    save_contrast_phase_cache,
    save_contrast_statistics,
    save_contrast_stats_hn,
    truncal_anatomy_present,
    verify_xgboost_runtime,
)
from anonymizer.controller.ai.tseg.segment import estimate_tseg_contrast_remaining_sec, series_cache_dir


def test_resolve_contrast_device_matches_resolve_device() -> None:
    from anonymizer.controller.ai.tseg.contrast import resolve_device

    assert resolve_contrast_device() == resolve_device()
    assert resolve_contrast_device(None) == resolve_device(None)


def test_resolve_contrast_device_explicit() -> None:
    assert resolve_contrast_device("mps") == "mps"


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("native", False),
        ("NATIVE", False),
        (" arterial_early ", True),
        ("arterial_early", True),
        ("arterial_late", True),
        ("portal_venous", True),
    ],
)
def test_phase_to_iv_contrast(phase: str, expected: bool) -> None:
    assert phase_to_iv_contrast(phase) is expected


def test_phase_to_iv_contrast_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown contrast phase"):
        phase_to_iv_contrast("delayed")


def test_verify_xgboost_runtime_ok() -> None:
    with patch("anonymizer.controller.ai.tseg.contrast.xgboost", create=True) as mock_xgb:
        mock_xgb.__version__ = "2.0.0"
        with patch.dict("sys.modules", {"xgboost": mock_xgb}):
            verify_xgboost_runtime()


def test_verify_xgboost_runtime_missing() -> None:
    with patch.dict("sys.modules", {"xgboost": None}):
        with pytest.raises(RuntimeError, match="pip install rsna-anonymizer"):
            verify_xgboost_runtime()


@patch("anonymizer.controller.ai.tseg.contrast.verify_xgboost_runtime")
@patch("anonymizer.controller.ai.tseg.contrast._contrast_classifier_pickle_path", return_value="/fake/classifier.pkl")
@patch("anonymizer.controller.ai.tseg.contrast._require_pi_time_to_phase")
@patch("anonymizer.controller.ai.tseg.contrast.open")
@patch("anonymizer.controller.ai.tseg.contrast.pickle.load")
def test_run_contrast_classifier(
    mock_pickle_load: MagicMock,
    mock_open: MagicMock,
    mock_pi_time_to_phase: MagicMock,
    mock_classifier_path: MagicMock,
    mock_verify: MagicMock,
) -> None:
    mock_clf = MagicMock()
    mock_clf.predict.return_value = [45.0]
    mock_pickle_load.return_value = {"model_a": mock_clf, "model_b": mock_clf}
    mock_pi_time_to_phase.return_value = lambda _pi_time: ("portal_venous", 0.92)

    result = _run_contrast_classifier([0.0] * 20)

    assert result["pi_time"] == 45.0
    assert result["phase"] == "portal_venous"
    assert result["probability"] == 0.92
    mock_verify.assert_called_once()


def _head_only_contrast_stats(*, brain_volume: float = 5000.0) -> dict:
    stats = {
        organ: {"intensity": 0.0, "volume": 0.0}
        for organ in (
            "liver",
            "pancreas",
            "urinary_bladder",
            "gallbladder",
            "heart",
            "aorta",
            "inferior_vena_cava",
            "portal_vein_and_splenic_vein",
            "iliac_vena_left",
            "iliac_vena_right",
            "iliac_artery_left",
            "iliac_artery_right",
            "pulmonary_vein",
            "brain",
            "colon",
            "small_bowel",
        )
    }
    stats["brain"] = {"intensity": 27.0, "volume": brain_volume}
    return stats


def _sample_contrast_stats(*, brain_volume: float = 0.0) -> dict:
    return {
        organ: {"intensity": 50.0, "volume": brain_volume if organ == "brain" else 1000.0}
        for organ in (
            "liver",
            "pancreas",
            "urinary_bladder",
            "gallbladder",
            "heart",
            "aorta",
            "inferior_vena_cava",
            "portal_vein_and_splenic_vein",
            "iliac_vena_left",
            "iliac_vena_right",
            "iliac_artery_left",
            "iliac_artery_right",
            "pulmonary_vein",
            "brain",
            "colon",
            "small_bowel",
        )
    }


@patch("anonymizer.controller.ai.tseg.contrast._run_contrast_classifier")
@patch("anonymizer.controller.ai.tseg.contrast._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.contrast._require_nibabel")
def test_predict_contrast_phase_reuses_existing_stats(
    mock_require_nib: MagicMock,
    mock_require_ts: MagicMock,
    mock_classifier: MagicMock,
    tmp_path: Path,
) -> None:
    mock_nib = MagicMock()
    mock_require_nib.return_value = mock_nib
    mock_ts = MagicMock()
    mock_require_ts.return_value = mock_ts
    mock_classifier.return_value = {
        "pi_time": 12.0,
        "phase": "native",
        "probability": 0.88,
        "pi_time_min": 10.0,
        "pi_time_max": 14.0,
        "stddev": 1.0,
    }
    nifti_path = tmp_path / "volume.nii.gz"
    nifti_path.write_bytes(b"")
    existing_stats = _sample_contrast_stats()

    result, inference_sec, hu_medians = predict_contrast_phase(
        nifti_path,
        existing_stats=existing_stats,
    )

    mock_ts.assert_not_called()
    mock_nib.load.assert_called_once_with(nifti_path)
    assert result["phase"] == "native"
    assert inference_sec >= 0.0
    assert hu_medians["liver"] == 50.0


@pytest.mark.parametrize(
    ("stats_cached", "stats_hn_cached", "phase_cached", "needs_head_neck", "expected"),
    [
        (True, True, True, True, 0.0),
        (True, True, False, True, 2.0),
        (True, False, False, True, 22.0),
        (True, False, False, False, 2.0),
        (False, False, False, False, 60.0),
    ],
)
def test_estimate_contrast_remaining_sec(
    stats_cached: bool,
    stats_hn_cached: bool,
    phase_cached: bool,
    needs_head_neck: bool,
    expected: float,
) -> None:
    assert (
        estimate_contrast_remaining_sec(
            stats_cached=stats_cached,
            stats_hn_cached=stats_hn_cached,
            phase_cached=phase_cached,
            needs_head_neck=needs_head_neck,
        )
        == expected
    )


@patch("anonymizer.controller.ai.tseg.contrast._run_contrast_classifier")
@patch("anonymizer.controller.ai.tseg.contrast._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.contrast._require_nibabel")
def test_predict_contrast_phase_reuses_phase_cache(
    mock_require_nib: MagicMock,
    mock_require_ts: MagicMock,
    mock_classifier: MagicMock,
    tmp_path: Path,
) -> None:
    nifti_path = tmp_path / "volume.nii.gz"
    nifti_path.write_bytes(b"")
    stats_path = tmp_path / "contrast_stats.json"
    phase_path = tmp_path / "contrast_phase.json"
    existing_stats = _sample_contrast_stats()
    save_contrast_statistics(existing_stats, stats_path)
    save_contrast_phase_cache(
        {
            "phase": "portal_venous",
            "pi_time": 45.0,
            "probability": 0.91,
            "pi_time_min": 44.0,
            "pi_time_max": 46.0,
            "stddev": 0.5,
        },
        hu_medians={"liver": 120.0},
        phase_cache_path=phase_path,
    )

    result, inference_sec, hu_medians = predict_contrast_phase(
        nifti_path,
        existing_stats=existing_stats,
        stats_output_path=stats_path,
        phase_cache_path=phase_path,
    )

    mock_require_ts.assert_not_called()
    mock_require_nib.assert_not_called()
    mock_classifier.assert_not_called()
    assert result["phase"] == "portal_venous"
    assert inference_sec >= 0.0
    assert hu_medians["liver"] == 120.0
    assert contrast_phase_cache_is_valid(phase_path, stats_path)


@patch("anonymizer.controller.ai.tseg.contrast._run_contrast_classifier")
@patch("anonymizer.controller.ai.tseg.contrast._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.contrast._require_nibabel")
def test_predict_contrast_phase_emits_progress_for_phase_cache(
    mock_require_nib: MagicMock,
    mock_require_ts: MagicMock,
    mock_classifier: MagicMock,
    tmp_path: Path,
) -> None:
    nifti_path = tmp_path / "volume.nii.gz"
    nifti_path.write_bytes(b"")
    stats_path = tmp_path / "contrast_stats.json"
    phase_path = tmp_path / "contrast_phase.json"
    existing_stats = _sample_contrast_stats()
    save_contrast_statistics(existing_stats, stats_path)
    save_contrast_phase_cache(
        {
            "phase": "native",
            "pi_time": 0.0,
            "probability": 0.99,
            "pi_time_min": 0.0,
            "pi_time_max": 0.0,
            "stddev": 0.0,
        },
        hu_medians={"liver": 50.0},
        phase_cache_path=phase_path,
    )
    events: list[tuple[str, str, float]] = []

    predict_contrast_phase(
        nifti_path,
        existing_stats=existing_stats,
        stats_output_path=stats_path,
        phase_cache_path=phase_path,
        progress=lambda stage, message, fraction: events.append((stage, message, fraction)),
    )

    assert events == [("contrast_phase_cache", "Using cached contrast phase: native (liver=50 HU)", 1.0)]


@patch("anonymizer.controller.ai.tseg.contrast._run_contrast_classifier")
@patch("anonymizer.controller.ai.tseg.contrast._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.contrast._require_nibabel")
def test_predict_contrast_phase_reuses_stats_hn_cache(
    mock_require_nib: MagicMock,
    mock_require_ts: MagicMock,
    mock_classifier: MagicMock,
    tmp_path: Path,
) -> None:
    mock_nib = MagicMock()
    mock_require_nib.return_value = mock_nib
    mock_ts = MagicMock()
    mock_require_ts.return_value = mock_ts
    mock_classifier.return_value = {
        "pi_time": 12.0,
        "phase": "native",
        "probability": 0.88,
        "pi_time_min": 10.0,
        "pi_time_max": 14.0,
        "stddev": 1.0,
    }
    nifti_path = tmp_path / "volume.nii.gz"
    nifti_path.write_bytes(b"")
    stats_path = tmp_path / "contrast_stats.json"
    stats_hn_path = tmp_path / "contrast_stats_hn.json"
    existing_stats = _sample_contrast_stats(brain_volume=5000.0)
    save_contrast_statistics(existing_stats, stats_path)
    save_contrast_stats_hn(
        {organ: {"intensity": 55.0, "volume": 100.0} for organ in CONTRAST_ORGANS_HN},
        stats_hn_path,
    )

    result, _, _ = predict_contrast_phase(
        nifti_path,
        existing_stats=existing_stats,
        stats_output_path=stats_path,
        stats_hn_output_path=stats_hn_path,
    )

    mock_ts.assert_not_called()
    mock_nib.load.assert_called_once_with(nifti_path)
    mock_classifier.assert_called_once()
    assert result["phase"] == "native"


@patch("anonymizer.controller.ai.tseg.contrast._run_contrast_classifier")
@patch("anonymizer.controller.ai.tseg.contrast._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.contrast._require_nibabel")
def test_predict_contrast_phase_headneck_task_omits_fast(
    mock_require_nib: MagicMock,
    mock_require_ts: MagicMock,
    mock_classifier: MagicMock,
    tmp_path: Path,
) -> None:
    mock_nib = MagicMock()
    mock_require_nib.return_value = mock_nib
    mock_ts = MagicMock()
    mock_require_ts.return_value = mock_ts
    organ_stats = _head_only_contrast_stats(brain_volume=5000.0)
    headneck_stats = {organ: {"intensity": 55.0, "volume": 100.0} for organ in CONTRAST_ORGANS_HN}
    mock_ts.side_effect = [(None, organ_stats), (None, headneck_stats)]
    mock_classifier.return_value = {
        "pi_time": 12.0,
        "phase": "native",
        "probability": 0.88,
        "pi_time_min": 10.0,
        "pi_time_max": 14.0,
        "stddev": 1.0,
    }
    nifti_path = tmp_path / "volume.nii.gz"
    nifti_path.write_bytes(b"")

    predict_contrast_phase(nifti_path)

    assert mock_ts.call_count == 2
    organ_call_kwargs = mock_ts.call_args_list[0].kwargs
    headneck_call_kwargs = mock_ts.call_args_list[1].kwargs
    assert organ_call_kwargs.get("fast") is True
    assert headneck_call_kwargs.get("task") == "headneck_bones_vessels"
    assert headneck_call_kwargs.get("fast") is not True


@patch("anonymizer.controller.ai.tseg.contrast._run_contrast_classifier")
@patch("anonymizer.controller.ai.tseg.contrast._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.contrast._require_nibabel")
def test_predict_contrast_phase_skips_headneck_for_truncal_fov(
    mock_require_nib: MagicMock,
    mock_require_ts: MagicMock,
    mock_classifier: MagicMock,
    tmp_path: Path,
) -> None:
    mock_nib = MagicMock()
    mock_require_nib.return_value = mock_nib
    mock_ts = MagicMock()
    mock_require_ts.return_value = mock_ts
    organ_stats = _sample_contrast_stats(brain_volume=5000.0)
    mock_ts.return_value = (None, organ_stats)
    mock_classifier.return_value = {
        "pi_time": 12.0,
        "phase": "portal_venous",
        "probability": 0.88,
        "pi_time_min": 10.0,
        "pi_time_max": 14.0,
        "stddev": 1.0,
    }
    nifti_path = tmp_path / "volume.nii.gz"
    nifti_path.write_bytes(b"")

    predict_contrast_phase(nifti_path)

    assert mock_ts.call_count == 1
    assert mock_ts.call_args.kwargs.get("task") != "headneck_bones_vessels"


@patch("anonymizer.controller.ai.tseg.contrast._run_contrast_classifier")
@patch("anonymizer.controller.ai.tseg.contrast._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.contrast._require_nibabel")
def test_predict_contrast_phase_skips_headneck_when_truncal_anatomy(
    mock_require_nib: MagicMock,
    mock_require_ts: MagicMock,
    mock_classifier: MagicMock,
    tmp_path: Path,
) -> None:
    """Abdomen-dominant anatomy skips head/neck even when organ HU stats look head-only."""
    mock_nib = MagicMock()
    mock_require_nib.return_value = mock_nib
    mock_ts = MagicMock()
    mock_require_ts.return_value = mock_ts
    organ_stats = _head_only_contrast_stats(brain_volume=5000.0)
    mock_ts.return_value = (None, organ_stats)
    mock_classifier.return_value = {
        "pi_time": 12.0,
        "phase": "native",
        "probability": 0.88,
        "pi_time_min": 10.0,
        "pi_time_max": 14.0,
        "stddev": 1.0,
    }
    nifti_path = tmp_path / "volume.nii.gz"
    nifti_path.write_bytes(b"")

    predict_contrast_phase(nifti_path, body_parts_present="Chest+Abdomen")

    assert mock_ts.call_count == 1
    assert mock_ts.call_args.kwargs.get("task") != "headneck_bones_vessels"


def test_truncal_anatomy_present() -> None:
    assert truncal_anatomy_present("Chest+Abdomen")
    assert truncal_anatomy_present("Abdomen")
    assert not truncal_anatomy_present("Head")
    assert not truncal_anatomy_present("")


def test_needs_head_neck_vessel_stats_respects_truncal_anatomy() -> None:
    stats = _head_only_contrast_stats(brain_volume=5000.0)
    assert head_dominant_limited_fov(stats)
    assert not needs_head_neck_vessel_stats(stats, body_parts_present="Chest+Abdomen")
    assert needs_head_neck_vessel_stats(stats, body_parts_present="Head")


def test_format_dominant_organ_hu_summary_head_region() -> None:
    from anonymizer.controller.ai.tseg.contrast import format_dominant_organ_hu_summary

    stats = {"brain": {"intensity": 27.0, "volume": 5000.0}}
    stats_hn = {
        "internal_carotid_artery_right": {"intensity": 75.0, "volume": 200.0},
        "internal_carotid_artery_left": {"intensity": 72.0, "volume": 200.0},
    }
    summary = format_dominant_organ_hu_summary(stats, stats_hn, dominant_region="Head")
    assert "27–75 HU" in summary
    assert "brain=27 HU" in summary


def test_format_dominant_organ_hu_summary_skips_low_volume() -> None:
    from anonymizer.controller.ai.tseg.contrast import format_dominant_organ_hu_summary

    stats = {"liver": {"intensity": 50.0, "volume": 0.0}}
    assert format_dominant_organ_hu_summary(stats, None, dominant_region="Abdomen") == ""


def test_estimate_tseg_contrast_remaining_sec_from_cache(tmp_path: Path) -> None:
    series_dir = tmp_path / "series"
    cache_dir = series_cache_dir(series_dir)
    cache_dir.mkdir(parents=True)
    stats_path = cache_dir / "contrast_stats.json"
    phase_path = cache_dir / "contrast_phase.json"
    existing_stats = _sample_contrast_stats(brain_volume=5000.0)
    save_contrast_statistics(existing_stats, stats_path)
    save_contrast_stats_hn(
        {organ: {"intensity": 55.0, "volume": 100.0} for organ in CONTRAST_ORGANS_HN},
        cache_dir / "contrast_stats_hn.json",
    )

    assert estimate_tseg_contrast_remaining_sec(series_dir) == 2.0

    save_contrast_phase_cache(
        {
            "phase": "native",
            "pi_time": 5.0,
            "probability": 0.9,
            "pi_time_min": 5.0,
            "pi_time_max": 5.0,
            "stddev": 0.0,
        },
        hu_medians={"liver": 50.0},
        phase_cache_path=phase_path,
    )
    assert estimate_tseg_contrast_remaining_sec(series_dir) == 0.0


def test_hu_gate_head_only_cect() -> None:
    """Head CECT: truncal organs absent, carotid ~75 HU → with contrast."""
    stats = {
        organ: {"intensity": 0.0, "volume": 0.0}
        for organ in (
            "liver",
            "aorta",
            "inferior_vena_cava",
            "heart",
            "portal_vein_and_splenic_vein",
            "brain",
        )
    }
    stats["brain"] = {"intensity": 27.0, "volume": 5000.0}
    stats_hn = {
        "internal_carotid_artery_right": {"intensity": 75.0, "volume": 200.0},
        "internal_carotid_artery_left": {"intensity": 75.0, "volume": 200.0},
        "internal_jugular_vein_right": {"intensity": 0.0, "volume": 0.0},
        "internal_jugular_vein_left": {"intensity": 0.0, "volume": 0.0},
    }
    assert head_dominant_limited_fov(stats)
    assert hu_gate_iv_contrast(stats, stats_hn) is True


def test_hu_gate_overrides_xgboost_native_on_head_cect() -> None:
    stats = {
        "brain": {"intensity": 27.0, "volume": 5000.0},
        "aorta": {"intensity": 0.0, "volume": 0.0},
        "liver": {"intensity": 0.0, "volume": 0.0},
        "inferior_vena_cava": {"intensity": 0.0, "volume": 0.0},
    }
    stats_hn = {
        "internal_carotid_artery_right": {"intensity": 75.0, "volume": 200.0},
        "internal_carotid_artery_left": {"intensity": 75.0, "volume": 200.0},
    }
    xgb = {"pi_time": 0.28, "phase": "native", "probability": 1.0}
    result = _apply_hu_gate(xgb, stats, stats_hn)
    assert result["phase"] == "arterial_early"
    assert phase_to_iv_contrast(result["phase"]) is True


def test_hu_gate_truncal_native() -> None:
    stats = {
        "brain": {"intensity": 20.0, "volume": 100.0},
        "aorta": {"intensity": 40.0, "volume": 500.0},
        "liver": {"intensity": 50.0, "volume": 800.0},
        "inferior_vena_cava": {"intensity": 35.0, "volume": 400.0},
    }
    assert hu_gate_iv_contrast(stats, {}) is False


@patch("anonymizer.controller.ai.tseg.contrast.log_memory_usage")
@patch("anonymizer.controller.ai.tseg.contrast.release_accelerator_memory")
@patch("anonymizer.controller.ai.tseg.contrast.gc.collect")
def test_release_before_contrast_gc_and_accelerator(
    mock_gc: MagicMock,
    mock_release_accel: MagicMock,
    _log_memory: MagicMock,
) -> None:
    from anonymizer.controller.ai.tseg.contrast import release_before_contrast

    release_before_contrast(stage="test_before_contrast")
    mock_release_accel.assert_called_once()
    assert mock_gc.call_count == 2


@patch("anonymizer.controller.ai.tseg.contrast.release_working_memory")
@patch("anonymizer.controller.ai.tseg.contrast._require_totalsegmentator")
@patch("anonymizer.controller.ai.tseg.contrast._require_nibabel")
def test_predict_contrast_phase_releases_memory_on_error(
    mock_nibabel: MagicMock,
    _mock_ts: MagicMock,
    mock_release: MagicMock,
    tmp_path: Path,
) -> None:
    nifti_path = tmp_path / "series.nii.gz"
    nifti_path.write_bytes(b"")
    mock_nibabel.return_value.load.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        predict_contrast_phase(nifti_path)
    mock_release.assert_called_once()


def test_format_contrast_organ_hu_summary_skips_low_volume_organs() -> None:
    stats = {
        "liver": {"intensity": 120.0, "volume": 5000.0},
        "aorta": {"intensity": 180.0, "volume": 800.0},
        "brain": {"intensity": 40.0, "volume": 0.0},
    }
    summary = format_contrast_organ_hu_summary(stats)
    assert summary == "aorta=180 HU, liver=120 HU"


def test_format_contrast_vessel_hu_summary_uses_short_labels() -> None:
    stats_hn = {organ: {"intensity": 55.0 + index, "volume": 200.0} for index, organ in enumerate(CONTRAST_ORGANS_HN)}
    summary = format_contrast_vessel_hu_summary(stats_hn)
    assert "ICA-R=55 HU" in summary
    assert "IJV-L=58 HU" in summary


def test_format_cached_organ_and_vessel_messages_include_hu_values() -> None:
    organ_stats = {
        "liver": {"intensity": 120.0, "volume": 5000.0},
        "aorta": {"intensity": 180.0, "volume": 800.0},
    }
    vessel_stats = {
        "internal_carotid_artery_right": {"intensity": 190.0, "volume": 100.0},
    }
    assert format_cached_organ_hu_message(organ_stats) == (
        "Using cached organ HU statistics: aorta=180 HU, liver=120 HU"
    )
    assert format_cached_vessel_hu_message(vessel_stats) == ("Using cached head/neck vessel statistics: ICA-R=190 HU")


def test_format_cached_contrast_phase_message_includes_phase_and_hu() -> None:
    message = format_cached_contrast_phase_message(
        {
            "phase": "portal_venous",
            "hu_medians": {"liver": 120.0, "aorta": 180.0},
        }
    )
    assert message == ("Using cached contrast phase: portal venous (aorta=180 HU, liver=120 HU)")
