"""Push remaining readiness / version / dicom coverage over the 80% line."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.ai.tseg.readiness import (
    TsWeightKind,
    download_segmentation_model,
    get_stored_face_license,
    remove_segmentation_model,
    verify_face_license,
)
from anonymizer.utils import version as version_mod
from anonymizer.utils.dicom import get_wl_ww
from anonymizer.utils.version import _pyproject_names_package, _version_from_pyproject, get_version


def test_download_segmentation_model_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.readiness.weight_kind_ready",
        lambda kind, mode=None: True,
    )
    assert download_segmentation_model(TsWeightKind.ANATOMY, on_complete=called.append) is True
    assert called == [True]

    called.clear()
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.readiness.weight_kind_ready",
        lambda kind, mode=None: False,
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.readiness.totalsegmentator_available",
        lambda: False,
    )
    assert download_segmentation_model(TsWeightKind.FACE, on_complete=called.append) is False
    assert called == [False]

    called.clear()
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.readiness.totalsegmentator_available",
        lambda: True,
    )

    def _boom(kind):
        raise RuntimeError("no net")

    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.model_cache.download_segmentation_model_weights",
        _boom,
    )
    assert download_segmentation_model(TsWeightKind.ANATOMY_MR, on_complete=called.append) is False
    assert called == [False]

    called.clear()
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.model_cache.download_segmentation_model_weights",
        lambda kind: None,
    )
    # Still not ready after "download"
    assert download_segmentation_model(TsWeightKind.BRAIN_STRUCTURES, on_complete=called.append) is False
    assert called == [False]


def test_remove_segmentation_model_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    folder = tmp_path / "weights"
    folder.mkdir()
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.model_cache.harmonize_ts_task_ids",
        lambda: (1,),
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.model_cache.mr_anatomy_task_ids",
        lambda: (2,),
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.model_cache.face_task_ids",
        lambda: (3,),
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.model_cache.mr_face_task_ids",
        lambda: (4,),
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.model_cache.resolve_harmonize_model_folder",
        lambda task_id: folder,
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.readiness.resolve_model_folder",
        lambda *a, **k: folder,
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.model_cache.clear_predictor_cache",
        lambda: None,
    )
    # Each call removes the folder; recreate between kinds
    for kind in (
        TsWeightKind.ANATOMY,
        TsWeightKind.ANATOMY_MR,
        TsWeightKind.FACE,
        TsWeightKind.FACE_MR,
        TsWeightKind.BRAIN_STRUCTURES,
    ):
        folder.mkdir(exist_ok=True)
        (folder / "x").write_text("1")
        assert remove_segmentation_model(kind) is True
        assert not folder.exists() or not any(folder.iterdir())


def test_face_license_getters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "anonymizer.controller.ai.tseg.readiness.totalsegmentator_available",
        lambda: False,
    )
    assert get_stored_face_license() == ""
    ok, msg = verify_face_license()
    assert ok is False


def test_version_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    poetry = tmp_path / "pyproject.toml"
    poetry.write_text(
        '[tool.poetry]\nname = "rsna-anonymizer"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    assert _pyproject_names_package(poetry) is True
    assert _version_from_pyproject(poetry) == "9.9.9"

    pep621 = tmp_path / "pep.toml"
    pep621.write_text('[project]\nname = "other"\nversion = "1.0"\n', encoding="utf-8")
    assert _pyproject_names_package(pep621) is False

    assert get_version()  # from real checkout

    monkeypatch.setattr(version_mod, "find_project_pyproject", lambda: None)
    with patch.object(version_mod.importlib.metadata, "version", side_effect=version_mod.importlib.metadata.PackageNotFoundError("x")):
        with pytest.raises(FileNotFoundError):
            get_version()


def test_apply_face_license_mocked_totalseg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from anonymizer.controller.ai.tseg import readiness as ready_mod

    monkeypatch.setattr(ready_mod, "totalsegmentator_available", lambda: True)

    cfg = MagicMock()
    cfg.get_totalseg_dir.return_value = tmp_path
    cfg.is_valid_license.return_value = True
    cfg.setup_totalseg.return_value = None
    cfg.has_valid_license_offline.return_value = ("yes", "ok")
    cfg.get_license_number.return_value = "aca_" + "y" * 14

    monkeypatch.setitem(__import__("sys").modules, "totalsegmentator", MagicMock())
    monkeypatch.setitem(__import__("sys").modules, "totalsegmentator.config", cfg)

    ok, _msg = ready_mod.apply_face_license("aca_" + "x" * 14)
    assert isinstance(ok, bool)

    cfg.is_valid_license.return_value = False
    ok2, _msg2 = ready_mod.apply_face_license("aca_" + "z" * 14)
    assert ok2 is False

    cfg.is_valid_license.return_value = True
    assert isinstance(ready_mod.get_stored_face_license(), str)
    assert isinstance(ready_mod.verify_face_license()[0], bool)
    assert isinstance(ready_mod.face_license_available(), bool)


def test_xp_download_file_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import anonymizer.controller.ai.harmonize.xp_bodypart.cache as xp_mod

    class _Resp:
        headers = {"Content-Length": "5"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1):
            yield b"abcde"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(xp_mod.requests, "get", lambda *a, **k: _Resp())
    dest = tmp_path / "xp.pt"
    xp_mod._download_file("http://example", dest, label="xp")
    assert dest.read_bytes() == b"abcde"

    # already-ready short-circuit
    monkeypatch.setattr(xp_mod, "probe_xp_bodypart_models", lambda: (xp_mod.XpBodypartModelStatus.READY, "ok"))
    ok, msg = xp_mod.download_xp_bodypart_models()
    assert ok is True

    from pydicom import Dataset

    ds = Dataset()
    ds.BitsAllocated = 8
    wl, ww = get_wl_ww(ds)
    assert wl == pytest.approx(127.5)
    assert ww == pytest.approx(255.0)

    ds16 = Dataset()
    ds16.BitsAllocated = 16
    assert get_wl_ww(ds16)[0] == pytest.approx(32768.0)

    ds12 = Dataset()
    ds12.BitsAllocated = 12
    assert get_wl_ww(ds12)[1] == pytest.approx(4096.0)

    ds10 = Dataset()
    ds10.BitsAllocated = 10
    assert get_wl_ww(ds10)[0] == pytest.approx(512.0)

    ds32 = Dataset()
    ds32.BitsAllocated = 32
    assert get_wl_ww(ds32)[1] == pytest.approx(4294967295.0)

    bad = Dataset()
    bad.BitsAllocated = 7
    with pytest.raises(ValueError):
        get_wl_ww(bad)

    ds.WindowCenter = [40, 400]
    ds.WindowWidth = [400, 2000]
    wl2, ww2 = get_wl_ww(ds)
    assert wl2 == pytest.approx(40.0)
    assert ww2 == pytest.approx(400.0)

    ds.WindowWidth = 0.5
    assert get_wl_ww(ds)[1] == pytest.approx(1.0)
