"""Tests for TotalSegmentator runtime status probes."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.tseg.runtime_status import (
    TsegRuntimeStatus,
    TsegSetupRowKind,
    TsWeightKind,
    TsWeightState,
    TsWeightStatus,
    _totalsegmentator_import_ok,
    build_ai_setup_rows,
    clear_weight_override,
    download_segmentation_model,
    get_runtime_status,
    log_runtime_status,
    probe_runtime_status,
    probe_weight_state,
    refresh_weight_status,
    set_weight_state,
    verify_face_license,
)


def test_totalsegmentator_import_ok_ignores_cwd_shadow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken totalsegmentator/ tree in cwd must not hide the venv package."""
    shadow = tmp_path / "totalsegmentator"
    shadow.mkdir()
    (shadow / "__init__.py").write_text('raise ImportError("broken cwd stub")\n', encoding="utf-8")

    pkg_root = tmp_path / "site-packages"
    pkg_root.mkdir()
    real_pkg = pkg_root / "totalsegmentator"
    real_pkg.mkdir()
    (real_pkg / "__init__.py").write_text('__version__ = "2.17.0"\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", ["", str(pkg_root), *sys.path[1:]])
    for name in list(sys.modules):
        if name == "totalsegmentator" or name.startswith("totalsegmentator."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    import importlib.metadata as md

    monkeypatch.setattr(
        md,
        "version",
        lambda name: "2.17.0" if name == "totalsegmentator" else (_ for _ in ()).throw(md.PackageNotFoundError(name)),
    )

    assert _totalsegmentator_import_ok() is True
    module = importlib.import_module("totalsegmentator")
    assert str(real_pkg) in module.__file__.replace("\\", "/")


def test_build_ai_setup_rows_respects_feature_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.chdir(tmp_path)
    (tmp_path / "assets" / "ai" / "ocr" / "model").mkdir(parents=True)
    tseg_weights = tmp_path / "assets" / "ai" / "tseg" / "nnunet" / "results"
    tseg_weights.mkdir(parents=True)
    os.environ["TOTALSEG_HOME_DIR"] = str(tmp_path / "assets" / "ai" / "tseg")
    os.environ["TOTALSEG_WEIGHTS_PATH"] = str(tseg_weights)

    status = probe_runtime_status()
    ocr_only = build_ai_setup_rows(status, enable_ocr=True, enable_harmonize=False, enable_face_blur=False)
    assert any(row.kind == TsegSetupRowKind.OCR_MODEL for row in ocr_only)
    assert not any(row.kind == TsegSetupRowKind.PACKAGE for row in ocr_only)

    harmonize_only = build_ai_setup_rows(status, enable_ocr=False, enable_harmonize=True, enable_face_blur=False)
    assert not any(row.kind == TsegSetupRowKind.OCR_MODEL for row in harmonize_only)
    assert any(row.kind == TsegSetupRowKind.ANATOMY_MODEL for row in harmonize_only)


def test_totalsegmentator_import_ok_false_without_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as md

    def _missing(_name: str) -> str:
        raise md.PackageNotFoundError("totalsegmentator")

    monkeypatch.setattr(md, "version", _missing)
    assert _totalsegmentator_import_ok() is False


def test_probe_runtime_status_without_totalsegmentator() -> None:
    with patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=False):
        status = probe_runtime_status()
    assert status.totalsegmentator_available is False
    assert status.harmonize_ready is False
    assert status.face_blur_ready is False
    assert status.anatomy_weights.status == TsWeightStatus.UNAVAILABLE
    assert "packages" in status.messages


def test_harmonize_ready_requires_xgboost() -> None:
    with (
        patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=True),
        patch("anonymizer.controller.tseg.runtime_status._xgboost_import_ok", return_value=(False, "need libomp")),
        patch("anonymizer.controller.tseg.runtime_status.verify_face_license", return_value=(True, "ok")),
        patch("anonymizer.controller.tseg.runtime_status.probe_weight_state") as mock_probe,
    ):
        mock_probe.side_effect = lambda kind: TsWeightState(
            kind=kind,
            status=TsWeightStatus.MISSING,
            task_id=297 if kind == TsWeightKind.ANATOMY else 303,
            model_folder=None,
        )
        status = probe_runtime_status()
    assert status.harmonize_ready is False
    assert status.face_blur_ready is True
    assert "xgboost" in status.messages


def test_probe_weight_state_ready_when_checkpoint_in_fold(tmp_path: Path) -> None:
    model_folder = tmp_path / "model"
    fold_dir = model_folder / "fold_0"
    fold_dir.mkdir(parents=True)
    (fold_dir / "checkpoint_final.pth").write_bytes(b"x")

    with (
        patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=True),
        patch("anonymizer.controller.tseg.model_cache.missing_harmonize_ts_task_ids", return_value=()),
        patch(
            "anonymizer.controller.tseg.model_cache.resolve_anatomy_model_folder",
            return_value=model_folder,
        ),
        patch(
            "anonymizer.controller.tseg.runtime_status._resolve_model_folder",
            return_value=model_folder,
        ),
    ):
        anatomy = probe_weight_state(TsWeightKind.ANATOMY)
        face = probe_weight_state(TsWeightKind.FACE)

    assert anatomy.status == TsWeightStatus.READY
    assert face.status == TsWeightStatus.READY


def test_probe_weight_state_ready_when_checkpoint_at_root(tmp_path: Path) -> None:
    model_folder = tmp_path / "model"
    model_folder.mkdir()
    (model_folder / "checkpoint_final.pth").write_bytes(b"x")

    with (
        patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=True),
        patch("anonymizer.controller.tseg.model_cache.missing_harmonize_ts_task_ids", return_value=()),
        patch(
            "anonymizer.controller.tseg.model_cache.resolve_anatomy_model_folder",
            return_value=model_folder,
        ),
    ):
        state = probe_weight_state(TsWeightKind.ANATOMY)

    assert state.status == TsWeightStatus.READY
    assert state.task_id == 297


def test_probe_weight_state_missing_when_crop_task_not_downloaded(tmp_path: Path) -> None:
    model_folder = tmp_path / "model"
    model_folder.mkdir()

    with (
        patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=True),
        patch("anonymizer.controller.tseg.model_cache.missing_harmonize_ts_task_ids", return_value=(298,)),
        patch(
            "anonymizer.controller.tseg.model_cache.resolve_anatomy_model_folder",
            return_value=model_folder,
        ),
    ):
        state = probe_weight_state(TsWeightKind.ANATOMY)

    assert state.status == TsWeightStatus.MISSING
    assert state.task_id == 297
    assert "298" in state.detail


def test_probe_weight_state_missing_when_no_checkpoint(tmp_path: Path) -> None:
    model_folder = tmp_path / "model"
    model_folder.mkdir()

    with (
        patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=True),
        patch(
            "anonymizer.controller.tseg.runtime_status._resolve_model_folder",
            return_value=model_folder,
        ),
    ):
        state = probe_weight_state(TsWeightKind.FACE)

    assert state.status == TsWeightStatus.MISSING
    assert state.task_id == 303
    assert "Licensed task" in state.detail


def test_weight_override_downloading_visible_in_status() -> None:
    downloading = TsWeightState(
        kind=TsWeightKind.ANATOMY,
        status=TsWeightStatus.DOWNLOADING,
        task_id=297,
        model_folder=None,
        detail="Downloading…",
    )
    set_weight_state(downloading)
    with (
        patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=True),
        patch("anonymizer.controller.tseg.runtime_status._xgboost_import_ok", return_value=(True, "")),
        patch("anonymizer.controller.tseg.runtime_status.verify_face_license", return_value=(True, "ok")),
        patch(
            "anonymizer.controller.tseg.runtime_status.probe_weight_state",
            return_value=TsWeightState(
                kind=TsWeightKind.ANATOMY,
                status=TsWeightStatus.MISSING,
                task_id=297,
                model_folder=None,
            ),
        ),
    ):
        status = get_runtime_status(force_refresh=True)
    assert status.anatomy_weights.status == TsWeightStatus.DOWNLOADING
    clear_weight_override(TsWeightKind.ANATOMY)


def test_refresh_weight_status_clears_override() -> None:
    set_weight_state(
        TsWeightState(
            kind=TsWeightKind.FACE,
            status=TsWeightStatus.FAILED,
            task_id=303,
            model_folder=None,
            detail="network error",
        )
    )
    ready = TsWeightState(
        kind=TsWeightKind.FACE,
        status=TsWeightStatus.READY,
        task_id=303,
        model_folder=Path("/tmp/face"),
        detail="",
    )
    with (
        patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=True),
        patch("anonymizer.controller.tseg.runtime_status.probe_weight_state", return_value=ready),
    ):
        state = refresh_weight_status(TsWeightKind.FACE)
    assert state.status == TsWeightStatus.READY
    status = get_runtime_status()
    assert status.face_weights.status == TsWeightStatus.READY


def test_verify_face_license_uses_offline_check(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_config = MagicMock()
    fake_config.has_valid_license_offline.return_value = ("yes", "valid")
    monkeypatch.setitem(sys.modules, "totalsegmentator", MagicMock())
    monkeypatch.setitem(sys.modules, "totalsegmentator.config", fake_config)
    with patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=True):
        ok, message = verify_face_license()
    assert ok is True
    assert message == "valid"


def test_download_segmentation_model_skips_when_ready() -> None:
    ready = TsWeightState(
        kind=TsWeightKind.ANATOMY,
        status=TsWeightStatus.READY,
        task_id=297,
        model_folder=Path("/models"),
    )
    with (
        patch("anonymizer.controller.tseg.runtime_status.probe_weight_state", return_value=ready),
        patch("anonymizer.controller.tseg.model_cache.download_segmentation_model_weights") as mock_dl,
    ):
        result = download_segmentation_model(TsWeightKind.ANATOMY)
    mock_dl.assert_not_called()
    assert result.status == TsWeightStatus.READY


def test_download_segmentation_model_calls_weights_helper() -> None:
    missing = TsWeightState(
        kind=TsWeightKind.ANATOMY,
        status=TsWeightStatus.MISSING,
        task_id=297,
        model_folder=None,
    )
    ready = TsWeightState(
        kind=TsWeightKind.ANATOMY,
        status=TsWeightStatus.READY,
        task_id=297,
        model_folder=Path("/models"),
    )
    face_missing = TsWeightState(
        kind=TsWeightKind.FACE,
        status=TsWeightStatus.MISSING,
        task_id=303,
        model_folder=None,
    )

    call_count = 0

    def probe_side(kind: TsWeightKind) -> TsWeightState:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return missing
        if kind == TsWeightKind.ANATOMY:
            return ready
        return face_missing

    with (
        patch("anonymizer.controller.tseg.runtime_status.probe_weight_state", side_effect=probe_side),
        patch("anonymizer.controller.tseg.model_cache.download_segmentation_model_weights") as mock_dl,
    ):
        result = download_segmentation_model(TsWeightKind.ANATOMY)
    mock_dl.assert_called_once_with(TsWeightKind.ANATOMY)
    assert result.status == TsWeightStatus.READY


def test_log_runtime_status_emits_harmonize_and_face_lines(caplog: pytest.LogCaptureFixture) -> None:
    status = MagicMock()
    status.totalsegmentator_available = True
    status.harmonize_ready = True
    status.face_blur_ready = False
    status.anatomy_weights = TsWeightState(
        kind=TsWeightKind.ANATOMY,
        status=TsWeightStatus.MISSING,
        task_id=297,
        model_folder=None,
        detail="~400 MB",
    )
    status.face_weights = TsWeightState(
        kind=TsWeightKind.FACE,
        status=TsWeightStatus.UNAVAILABLE,
        task_id=None,
        model_folder=None,
    )
    status.messages = {"face_license": "no license"}

    with patch("anonymizer.controller.tseg.runtime_status.get_runtime_status", return_value=status):
        log_runtime_status()

    assert any("Harmonize: available" in record.message for record in caplog.records)
    assert any("Anatomy segmentation model: not downloaded" in record.message for record in caplog.records)
    assert any("Face Blur: unavailable" in record.message for record in caplog.records)


def test_ai_feature_status_messages_are_clinical() -> None:
    from anonymizer.controller.tseg.runtime_status import (
        TsegRuntimeStatus,
        TsWeightKind,
        TsWeightState,
        TsWeightStatus,
        ai_feature_status_face_blur,
        ai_feature_status_harmonize,
        ai_feature_status_remove_pixel_phi,
    )

    status = TsegRuntimeStatus(
        totalsegmentator_available=True,
        xgboost_available=True,
        face_license_available=False,
        anatomy_weights=TsWeightState(
            kind=TsWeightKind.ANATOMY,
            status=TsWeightStatus.MISSING,
            task_id=297,
            model_folder=None,
            detail="~400 MB",
        ),
        face_weights=TsWeightState(
            kind=TsWeightKind.FACE,
            status=TsWeightStatus.MISSING,
            task_id=303,
            model_folder=None,
            detail="Licensed task",
        ),
        harmonize_ready=False,
        face_blur_ready=False,
        messages={"face_license": "ERROR: A license number has not been set so far."},
    )

    with patch("anonymizer.controller.tseg.runtime_status.get_runtime_status", return_value=status):
        face_msg = ai_feature_status_face_blur()
        harmonize_msg = ai_feature_status_harmonize()

    assert "ERROR" not in face_msg
    assert "license" in face_msg.lower()
    assert "ERROR" not in harmonize_msg
    assert "Download models" in harmonize_msg or "Anatomy segmentation models" in harmonize_msg

    from anonymizer.controller.remove_pixel_phi import OcrModelStatus

    with patch(
        "anonymizer.controller.remove_pixel_phi.probe_ocr_models",
        return_value=(OcrModelStatus.MISSING, "Not downloaded"),
    ):
        ocr_msg = ai_feature_status_remove_pixel_phi()

    assert "ERROR" not in ocr_msg
    assert "Download models" in ocr_msg or "OCR models" in ocr_msg


def test_harmonize_allowed_uses_session_and_runtime_status() -> None:
    from anonymizer.controller.tseg.runtime_status import (
        TsegRuntimeStatus,
        harmonize_allowed,
        set_ai_session,
    )

    set_ai_session(enable_harmonize=False)
    assert harmonize_allowed() is False

    set_ai_session(enable_harmonize=True)
    ready_status = TsegRuntimeStatus(
        totalsegmentator_available=True,
        xgboost_available=True,
        face_license_available=True,
        anatomy_weights=TsWeightState(
            kind=TsWeightKind.ANATOMY,
            status=TsWeightStatus.READY,
            task_id=297,
            model_folder=Path("/tmp/anatomy"),
            detail="",
        ),
        face_weights=TsWeightState(
            kind=TsWeightKind.FACE,
            status=TsWeightStatus.READY,
            task_id=303,
            model_folder=Path("/tmp/face"),
            detail="",
        ),
        harmonize_ready=True,
        face_blur_ready=True,
        messages={},
    )
    with patch("anonymizer.controller.tseg.runtime_status.get_runtime_status", return_value=ready_status):
        assert harmonize_allowed() is True

    not_ready_status = TsegRuntimeStatus(
        totalsegmentator_available=True,
        xgboost_available=False,
        face_license_available=True,
        anatomy_weights=TsWeightState(
            kind=TsWeightKind.ANATOMY,
            status=TsWeightStatus.MISSING,
            task_id=297,
            model_folder=None,
            detail="",
        ),
        face_weights=TsWeightState(
            kind=TsWeightKind.FACE,
            status=TsWeightStatus.READY,
            task_id=303,
            model_folder=Path("/tmp/face"),
            detail="",
        ),
        harmonize_ready=False,
        face_blur_ready=True,
        messages={},
    )
    with patch("anonymizer.controller.tseg.runtime_status.get_runtime_status", return_value=not_ready_status):
        assert harmonize_allowed() is False

    missing_weights_status = TsegRuntimeStatus(
        totalsegmentator_available=True,
        xgboost_available=True,
        face_license_available=True,
        anatomy_weights=TsWeightState(
            kind=TsWeightKind.ANATOMY,
            status=TsWeightStatus.MISSING,
            task_id=297,
            model_folder=None,
            detail="",
        ),
        face_weights=TsWeightState(
            kind=TsWeightKind.FACE,
            status=TsWeightStatus.READY,
            task_id=303,
            model_folder=Path("/tmp/face"),
            detail="",
        ),
        harmonize_ready=True,
        face_blur_ready=True,
        messages={},
    )
    with patch(
        "anonymizer.controller.tseg.runtime_status.get_runtime_status",
        return_value=missing_weights_status,
    ):
        assert harmonize_allowed() is False


def test_init_ai_session_from_runtime_enables_downloaded_models() -> None:
    from anonymizer.controller.remove_pixel_phi import OcrModelStatus
    from anonymizer.controller.tseg.runtime_status import get_ai_session, init_ai_session_from_runtime, set_ai_session

    set_ai_session(remove_pixel_phi=False, enable_harmonize=False, enable_face_blur=False)
    ready_status = TsegRuntimeStatus(
        totalsegmentator_available=True,
        xgboost_available=True,
        face_license_available=True,
        anatomy_weights=TsWeightState(
            kind=TsWeightKind.ANATOMY,
            status=TsWeightStatus.READY,
            task_id=297,
            model_folder=Path("/tmp/anatomy"),
            detail="",
        ),
        face_weights=TsWeightState(
            kind=TsWeightKind.FACE,
            status=TsWeightStatus.READY,
            task_id=303,
            model_folder=Path("/tmp/face"),
            detail="",
        ),
        harmonize_ready=True,
        face_blur_ready=True,
        messages={},
    )
    with (
        patch(
            "anonymizer.controller.tseg.runtime_status.get_runtime_status",
            return_value=ready_status,
        ),
        patch(
            "anonymizer.controller.remove_pixel_phi.probe_ocr_models",
            return_value=(OcrModelStatus.READY, "Downloaded"),
        ),
    ):
        init_ai_session_from_runtime()

    session = get_ai_session()
    assert session.remove_pixel_phi is True
    assert session.enable_harmonize is True
    assert session.enable_face_blur is True


def test_ai_feature_titles_and_descriptions_match_batch_process() -> None:
    from anonymizer.controller.tseg.runtime_status import (
        ai_feature_description_face_blur,
        ai_feature_description_harmonize,
        ai_feature_description_remove_pixel_phi,
        ai_feature_summary_face_blur,
        ai_feature_summary_harmonize,
        ai_feature_summary_remove_pixel_phi,
        ai_feature_title_face_blur,
        ai_feature_title_harmonize,
        ai_feature_title_remove_pixel_phi,
    )

    assert ai_feature_title_remove_pixel_phi() == "Remove Burnt-in Annotation"
    assert ai_feature_title_harmonize() == "Harmonize"
    assert ai_feature_title_face_blur() == "Face De-identify"
    assert ai_feature_description_remove_pixel_phi() == "Burnt-in text overlays in pixel data (OCR-based)."
    assert ai_feature_description_harmonize() == "CT only. Updates SeriesDescription only."
    assert "CT head" in ai_feature_description_face_blur()
    assert ai_feature_summary_remove_pixel_phi() != ai_feature_description_remove_pixel_phi()
    assert ai_feature_summary_harmonize() != ai_feature_description_harmonize()
    assert ai_feature_summary_face_blur() != ai_feature_description_face_blur()
    assert "RadLex" in ai_feature_summary_harmonize()


def test_feature_has_models_helpers() -> None:
    from anonymizer.controller.remove_pixel_phi import OcrModelStatus
    from anonymizer.controller.tseg.runtime_status import (
        TsegRuntimeStatus,
        face_blur_has_models,
        harmonize_has_models,
        remove_pixel_phi_has_models,
    )

    ready_status = TsegRuntimeStatus(
        totalsegmentator_available=True,
        xgboost_available=True,
        face_license_available=True,
        anatomy_weights=TsWeightState(
            kind=TsWeightKind.ANATOMY,
            status=TsWeightStatus.READY,
            task_id=297,
            model_folder=Path("/tmp/anatomy"),
            detail="",
        ),
        face_weights=TsWeightState(
            kind=TsWeightKind.FACE,
            status=TsWeightStatus.MISSING,
            task_id=303,
            model_folder=None,
            detail="",
        ),
        harmonize_ready=True,
        face_blur_ready=True,
        messages={},
    )
    with (
        patch(
            "anonymizer.controller.tseg.runtime_status.get_runtime_status",
            return_value=ready_status,
        ),
        patch(
            "anonymizer.controller.remove_pixel_phi.probe_ocr_models",
            return_value=(OcrModelStatus.READY, "Downloaded"),
        ),
    ):
        assert remove_pixel_phi_has_models() is True
        assert harmonize_has_models() is True
        assert face_blur_has_models() is False
