"""Tests for TotalSegmentator XGBoost contrast phase helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.tseg.contrast import (
    _apply_hu_gate,
    _run_contrast_classifier,
    head_dominant_limited_fov,
    hu_gate_iv_contrast,
    phase_to_iv_contrast,
    predict_contrast_phase,
    resolve_contrast_device,
    verify_xgboost_runtime,
)


def test_resolve_contrast_device_matches_resolve_device() -> None:
    from anonymizer.controller.tseg.contrast import resolve_device

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
    with patch("anonymizer.controller.tseg.contrast.xgboost", create=True) as mock_xgb:
        mock_xgb.__version__ = "2.0.0"
        with patch.dict("sys.modules", {"xgboost": mock_xgb}):
            verify_xgboost_runtime()


def test_verify_xgboost_runtime_missing() -> None:
    with patch.dict("sys.modules", {"xgboost": None}):
        with pytest.raises(RuntimeError, match='pip install "rsna-anonymizer\\[tseg\\]"'):
            verify_xgboost_runtime()


@patch("anonymizer.controller.tseg.contrast.verify_xgboost_runtime")
@patch("anonymizer.controller.tseg.contrast._require_pi_time_to_phase")
@patch("anonymizer.controller.tseg.contrast.open")
@patch("anonymizer.controller.tseg.contrast.pickle.load")
def test_run_contrast_classifier(
    mock_pickle_load: MagicMock,
    mock_open: MagicMock,
    mock_pi_time_to_phase: MagicMock,
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


@patch("anonymizer.controller.tseg.contrast._run_contrast_classifier")
@patch("anonymizer.controller.tseg.contrast._require_totalsegmentator")
@patch("anonymizer.controller.tseg.contrast.nib.load")
def test_predict_contrast_phase_reuses_existing_stats(
    mock_nib_load: MagicMock,
    mock_require_ts: MagicMock,
    mock_classifier: MagicMock,
    tmp_path: Path,
) -> None:
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
    mock_nib_load.assert_called_once_with(nifti_path)
    assert result["phase"] == "native"
    assert inference_sec >= 0.0
    assert hu_medians["liver"] == 50.0


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


@patch("anonymizer.controller.tseg.contrast.log_memory_usage")
@patch("anonymizer.controller.tseg.contrast.release_accelerator_memory")
@patch("anonymizer.controller.tseg.contrast.gc.collect")
def test_release_before_contrast_gc_and_accelerator(
    mock_gc: MagicMock,
    mock_release_accel: MagicMock,
    _log_memory: MagicMock,
) -> None:
    from anonymizer.controller.tseg.contrast import release_before_contrast

    release_before_contrast(stage="test_before_contrast")
    mock_release_accel.assert_called_once()
    assert mock_gc.call_count == 2
