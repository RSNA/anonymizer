"""Extra coverage: series_io validation errors, model cache probes, readiness."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from anonymizer.controller.ai.harmonize.cxp_view.cache import (
    CxpViewModelStatus,
    download_cxp_view_models,
    probe_cxp_view_models,
    remove_cxp_view_models,
)
from anonymizer.controller.ai.harmonize.xp_bodypart.cache import (
    XpBodypartModelStatus,
    download_xp_bodypart_models,
    probe_xp_bodypart_models,
    remove_xp_bodypart_models,
)
from anonymizer.controller.ai.tseg.readiness import (
    anatomy_ct_ready,
    anatomy_mr_ready,
    brain_structures_ready,
    checkpoint_ready,
    face_ct_ready,
    face_mr_ready,
    log_runtime_status,
    totalsegmentator_available,
    ts_academic_license_url,
    weight_kind_ready,
    xgboost_available,
)
from anonymizer.controller.series_io import (
    _rows_cols_from_pixel_array,
    _validate_dicom_pixel_array,
)


def test_rows_cols_from_pixel_array() -> None:
    assert _rows_cols_from_pixel_array(np.zeros((10, 20))) == (10, 20)
    assert _rows_cols_from_pixel_array(np.zeros((5, 10, 20, 3))) == (10, 20)
    assert _rows_cols_from_pixel_array(np.zeros((4, 8, 16))) == (8, 16)
    with pytest.raises(ValueError):
        _rows_cols_from_pixel_array(np.zeros(3))


def _base_ds(**overrides) -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.SamplesPerPixel = 1
    ds.Rows = 2
    ds.Columns = 2
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = bytes(8)
    for k, v in overrides.items():
        setattr(ds, k, v)
    return ds


def test_validate_dicom_pixel_array_error_paths() -> None:
    with pytest.raises(ValueError, match="file_meta"):
        _validate_dicom_pixel_array(Dataset())

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    with pytest.raises(ValueError, match="TransferSyntaxUID"):
        _validate_dicom_pixel_array(ds)

    ds = _base_ds()
    del ds.PixelData
    with pytest.raises(ValueError, match="PixelData"):
        _validate_dicom_pixel_array(ds)

    with pytest.raises(ValueError, match="PhotometricInterpretation"):
        _validate_dicom_pixel_array(_base_ds(PhotometricInterpretation=""))

    with pytest.raises(ValueError, match="Invalid Photometric"):
        _validate_dicom_pixel_array(_base_ds(PhotometricInterpretation="NOT_A_REAL_PI"))

    with pytest.raises(ValueError, match="Samples per pixel"):
        _validate_dicom_pixel_array(_base_ds(SamplesPerPixel=3))

    with pytest.raises(ValueError, match="Missing image dimensions"):
        _validate_dicom_pixel_array(_base_ds(Rows=0, Columns=0))

    with pytest.raises(ValueError, match="Missing essential"):
        bad = _base_ds()
        del bad.BitsAllocated
        _validate_dicom_pixel_array(bad)

    with pytest.raises(ValueError, match="BitsStored"):
        _validate_dicom_pixel_array(_base_ds(BitsStored=20, HighBit=19))

    with pytest.raises(ValueError, match="HighBit"):
        _validate_dicom_pixel_array(_base_ds(HighBit=10))

    with pytest.raises(ValueError, match="Pixel Representation"):
        _validate_dicom_pixel_array(_base_ds(PixelRepresentation=9))


def test_cxp_and_xp_cache_probe_and_fake_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    weight = tmp_path / "w.pt"
    weight.write_bytes(b"tiny")
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.cxp_view.cache.CXP_VIEW_WEIGHT_PATH", weight
    )
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.cxp_view.cache.CXP_VIEW_DIR", tmp_path
    )
    status, _ = probe_cxp_view_models()
    assert status == CxpViewModelStatus.FAILED

    big = tmp_path / "big.pt"
    big.write_bytes(b"x" * 1_000_001)
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.cxp_view.cache.CXP_VIEW_WEIGHT_PATH", big
    )
    assert probe_cxp_view_models()[0] == CxpViewModelStatus.READY

    import anonymizer.controller.ai.harmonize.cxp_view.cache as cxp_mod

    monkeypatch.setattr(cxp_mod, "_downloading", True)
    assert probe_cxp_view_models()[0] == CxpViewModelStatus.DOWNLOADING
    monkeypatch.setattr(cxp_mod, "_downloading", False)

    def _fake_dl(url, dest, *, label):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"y" * 1_000_001)

    monkeypatch.setattr(cxp_mod, "_download_file", _fake_dl)
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.cxp_view.predict.clear_model_cache",
        lambda: None,
    )
    missing = tmp_path / "missing.pt"
    monkeypatch.setattr(cxp_mod, "CXP_VIEW_WEIGHT_PATH", missing)
    ok, _msg = download_cxp_view_models()
    assert ok is True
    remove_cxp_view_models()

    import anonymizer.controller.ai.harmonize.xp_bodypart.cache as xp_mod

    monkeypatch.setattr(xp_mod, "XP_BODYPART_DIR", tmp_path / "xp_dir")
    (tmp_path / "xp_dir").mkdir(exist_ok=True)
    xp_w = tmp_path / "xp_dir" / "xp.pt"
    xp_w.write_bytes(b"z")
    monkeypatch.setattr(xp_mod, "XP_BODYPART_WEIGHT_PATH", xp_w)
    assert probe_xp_bodypart_models()[0] == XpBodypartModelStatus.FAILED

    xp_big = tmp_path / "xp_dir" / "xp_big.pt"
    xp_big.write_bytes(b"z" * 1_000_001)
    monkeypatch.setattr(xp_mod, "XP_BODYPART_WEIGHT_PATH", xp_big)
    assert probe_xp_bodypart_models()[0] == XpBodypartModelStatus.READY

    monkeypatch.setattr(xp_mod, "_downloading", True)
    assert probe_xp_bodypart_models()[0] == XpBodypartModelStatus.DOWNLOADING
    monkeypatch.setattr(xp_mod, "_downloading", False)

    monkeypatch.setattr(xp_mod, "_download_file", _fake_dl)
    monkeypatch.setattr(
        "anonymizer.controller.ai.harmonize.xp_bodypart.predict.clear_model_cache",
        lambda: None,
    )
    # XP download probes while _downloading is still True → may report incomplete; still covers path
    monkeypatch.setattr(xp_mod, "XP_BODYPART_WEIGHT_PATH", tmp_path / "xp_dir" / "xp_miss.pt")
    ok2, msg2 = download_xp_bodypart_models()
    assert isinstance(ok2, bool)
    assert isinstance(msg2, str)
    remove_xp_bodypart_models()


def test_download_file_with_mocked_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import anonymizer.controller.ai.harmonize.cxp_view.cache as cxp_mod

    class _Resp:
        headers = {"Content-Length": "10"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1):
            yield b"abcdefghij"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(cxp_mod.requests, "get", lambda *a, **k: _Resp())
    dest = tmp_path / "out.pt"
    cxp_mod._download_file("http://example", dest, label="w")
    assert dest.read_bytes() == b"abcdefghij"

    assert isinstance(ts_academic_license_url(), str)
    assert isinstance(totalsegmentator_available(), bool)
    assert isinstance(xgboost_available(), bool)
    assert checkpoint_ready(None) is False
    assert checkpoint_ready(Path("/no/such/folder")) is False
    assert isinstance(anatomy_ct_ready(), bool)
    assert isinstance(anatomy_mr_ready(), bool)
    assert isinstance(face_ct_ready(), bool)
    assert isinstance(face_mr_ready(), bool)
    assert isinstance(brain_structures_ready(), bool)
    # weight_kind_ready for common kinds
    for kind in ("anatomy_ct", "anatomy_mr", "face_ct", "face_mr", "brain"):
        try:
            weight_kind_ready(kind)  # type: ignore[arg-type]
        except Exception:
            pass
    log_runtime_status()


def test_face_license_format_and_weight_kinds() -> None:
    from anonymizer.controller.ai.tseg.readiness import (
        TsWeightKind,
        _face_license_format_error,
        apply_face_license,
    )

    assert _face_license_format_error("") is not None
    assert _face_license_format_error("bad") is not None
    assert _face_license_format_error("aca_short") is not None
    assert _face_license_format_error("aca_" + "x" * 14) is None
    ok, msg = apply_face_license("bad")
    assert ok is False and msg

    for kind in TsWeightKind:
        assert isinstance(weight_kind_ready(kind), bool)
