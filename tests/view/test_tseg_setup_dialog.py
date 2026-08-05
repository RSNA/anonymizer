"""Tests for TotalSegmentator setup checklist rows and dialog helpers."""

from __future__ import annotations

import os
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
    apply_face_license,
    build_tseg_setup_rows,
    openmp_setup_command,
    validate_face_license_format,
)


def _setup_asset_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "assets" / "ai" / "ocr" / "model").mkdir(parents=True)
    tseg_weights = tmp_path / "assets" / "ai" / "tseg" / "nnunet" / "results"
    tseg_weights.mkdir(parents=True)
    os.environ["TOTALSEG_HOME_DIR"] = str(tmp_path / "assets" / "ai" / "tseg")
    os.environ["TOTALSEG_WEIGHTS_PATH"] = str(tseg_weights)


def _status(
    *,
    totalsegmentator_available: bool = True,
    xgboost_available: bool = True,
    face_license_available: bool = True,
    anatomy_status: TsWeightStatus = TsWeightStatus.READY,
    face_status: TsWeightStatus = TsWeightStatus.READY,
    messages: dict[str, str] | None = None,
) -> TsegRuntimeStatus:
    return TsegRuntimeStatus(
        totalsegmentator_available=totalsegmentator_available,
        xgboost_available=xgboost_available,
        face_license_available=face_license_available,
        anatomy_weights=TsWeightState(
            kind=TsWeightKind.ANATOMY,
            status=anatomy_status,
            task_id=297,
            model_folder=Path("/tmp/anatomy") if anatomy_status == TsWeightStatus.READY else None,
            detail="~400 MB",
        ),
        face_weights=TsWeightState(
            kind=TsWeightKind.FACE,
            status=face_status,
            task_id=303,
            model_folder=Path("/tmp/face") if face_status == TsWeightStatus.READY else None,
            detail="Licensed task",
        ),
        harmonize_ready=totalsegmentator_available and xgboost_available,
        face_blur_ready=totalsegmentator_available and face_license_available,
        messages=messages or {},
    )


def _row(rows, kind: TsegSetupRowKind):
    return next(row for row in rows if row.kind == kind)


def test_build_setup_rows_full_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_asset_dirs(tmp_path, monkeypatch)
    rows = build_tseg_setup_rows(_status())
    assert len(rows) == 6
    assert _row(rows, TsegSetupRowKind.PACKAGE).icon == "✓"
    assert _row(rows, TsegSetupRowKind.OPENMP).icon == "✓"
    assert _row(rows, TsegSetupRowKind.LICENSE).icon == "✓"
    anatomy = _row(rows, TsegSetupRowKind.ANATOMY_MODEL)
    assert anatomy.status_line == "Downloaded"
    assert anatomy.download_enabled is False
    assert _row(rows, TsegSetupRowKind.FACE_MODEL).status_line == "Downloaded"


def test_build_setup_rows_missing_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_asset_dirs(tmp_path, monkeypatch)
    rows = build_tseg_setup_rows(_status(totalsegmentator_available=False, xgboost_available=False))
    assert _row(rows, TsegSetupRowKind.PACKAGE).icon == "○"
    assert "pip install" in _row(rows, TsegSetupRowKind.PACKAGE).fix_line
    assert _row(rows, TsegSetupRowKind.OPENMP).status_line.startswith("Waiting for TotalSegmentator")
    assert _row(rows, TsegSetupRowKind.ANATOMY_MODEL).download_enabled is False
    assert _row(rows, TsegSetupRowKind.FACE_MODEL).download_enabled is False


def test_build_setup_rows_missing_openmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_asset_dirs(tmp_path, monkeypatch)
    rows = build_tseg_setup_rows(
        _status(
            xgboost_available=False,
            anatomy_status=TsWeightStatus.MISSING,
            messages={"xgboost": "need libomp"},
        )
    )
    openmp = _row(rows, TsegSetupRowKind.OPENMP)
    assert openmp.icon == "○"
    assert "need libomp" in openmp.fix_line
    assert _row(rows, TsegSetupRowKind.ANATOMY_MODEL).download_enabled is True


def test_build_setup_rows_anatomy_download_enabled_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_asset_dirs(tmp_path, monkeypatch)
    rows = build_tseg_setup_rows(_status(anatomy_status=TsWeightStatus.MISSING))
    anatomy = _row(rows, TsegSetupRowKind.ANATOMY_MODEL)
    assert anatomy.download_kind == TsWeightKind.ANATOMY
    assert anatomy.download_enabled is True
    assert "Not downloaded" in anatomy.status_line


def test_build_setup_rows_face_download_requires_license(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_asset_dirs(tmp_path, monkeypatch)
    rows = build_tseg_setup_rows(
        _status(
            face_license_available=False,
            face_status=TsWeightStatus.MISSING,
            messages={"face_license": "no license"},
        )
    )
    license_row = _row(rows, TsegSetupRowKind.LICENSE)
    assert license_row.icon == "○"
    assert "Enter your aca_" in license_row.fix_line
    assert _row(rows, TsegSetupRowKind.FACE_MODEL).download_enabled is False


def test_build_setup_rows_face_download_enabled_with_license(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_asset_dirs(tmp_path, monkeypatch)
    rows = build_tseg_setup_rows(_status(face_status=TsWeightStatus.MISSING))
    assert _row(rows, TsegSetupRowKind.FACE_MODEL).download_enabled is True


def test_openmp_setup_command_platform_specific() -> None:
    with patch("anonymizer.controller.tseg.runtime_status.sys.platform", "darwin"):
        assert openmp_setup_command() == "brew install libomp"
    with patch("anonymizer.controller.tseg.runtime_status.sys.platform", "win32"):
        assert "Visual C++" in openmp_setup_command()


def test_validate_face_license_format() -> None:
    assert validate_face_license_format("") is not None
    assert validate_face_license_format("bad") is not None
    assert validate_face_license_format("aca_short") is not None
    assert validate_face_license_format("aca_5Z11SIESU8C5J4") is None


def test_apply_face_license_rejects_invalid_format() -> None:
    ok, message = apply_face_license("aca_bad")
    assert ok is False
    assert "18 characters" in message


def test_apply_face_license_saves_valid_license(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"totalseg_id": "test", "send_usage_stats": true, "prediction_counter": 0}',
        encoding="utf-8",
    )

    fake_config = MagicMock()
    fake_config.get_totalseg_dir.return_value = tmp_path
    fake_config.is_valid_license.return_value = True
    fake_config.has_valid_license_offline.return_value = ("yes", "valid")
    fake_config.setup_totalseg.return_value = None
    monkeypatch.setitem(sys.modules, "totalsegmentator", MagicMock())
    monkeypatch.setitem(sys.modules, "totalsegmentator.config", fake_config)

    with patch("anonymizer.controller.tseg.runtime_status._totalsegmentator_import_ok", return_value=True):
        ok, message = apply_face_license("aca_5Z11SIESU8C5J4")

    assert ok is True
    assert "saved" in message.lower()
    import json

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["license_number"] == "aca_5Z11SIESU8C5J4"


def test_show_ai_features_setup_dialog_creates_modal() -> None:
    from anonymizer.view.tseg_setup_dialog import show_ai_features_setup_dialog

    parent = MagicMock()
    on_changed = MagicMock()
    with patch("anonymizer.view.tseg_setup_dialog.AiFeaturesSetupDialog") as dialog_cls:
        show_ai_features_setup_dialog(parent, on_changed=on_changed)
    dialog_cls.assert_called_once_with(parent, on_changed=on_changed)


def test_ai_features_setup_dialog_is_not_user_resizable() -> None:
    import tkinter as tk

    from anonymizer.view.tseg_setup_dialog import AiFeaturesSetupDialog

    with (
        patch.object(tk.Toplevel, "__init__", return_value=None),
        patch.object(tk.Toplevel, "resizable") as resizable,
        patch.object(tk.Toplevel, "title"),
        patch.object(tk.Toplevel, "protocol"),
        patch.object(tk.Toplevel, "bind"),
        patch.object(tk.Toplevel, "after_idle"),
        patch("anonymizer.view.tseg_setup_dialog.ctk.CTkFrame"),
        patch("anonymizer.view.tseg_setup_dialog.ctk.CTkLabel"),
        patch("anonymizer.view.tseg_setup_dialog.ctk.CTkButton"),
        patch("anonymizer.view.tseg_setup_dialog.AiFeaturesPanel"),
        patch.object(AiFeaturesSetupDialog, "wait_visibility"),
        patch.object(AiFeaturesSetupDialog, "grab_set"),
    ):
        AiFeaturesSetupDialog(MagicMock(), on_changed=MagicMock())

    resizable.assert_called_with(False, False)


def test_ai_features_setup_dialog_fits_to_content() -> None:
    from anonymizer.view.tseg_setup_dialog import AiFeaturesSetupDialog

    parent = MagicMock()
    parent.winfo_rootx.return_value = 0
    parent.winfo_rooty.return_value = 0
    parent.winfo_width.return_value = 900
    parent.winfo_height.return_value = 700

    dialog = AiFeaturesSetupDialog.__new__(AiFeaturesSetupDialog)
    dialog._closing = False
    dialog._geometry_set = False
    dialog.master = parent
    dialog.update_idletasks = MagicMock()
    dialog.winfo_reqwidth = MagicMock(return_value=540)
    dialog.winfo_reqheight = MagicMock(return_value=420)
    dialog.geometry = MagicMock()

    dialog._fit_to_content()

    dialog.geometry.assert_called_once()
    assert dialog.geometry.call_args.args[0].startswith("560x420+")
