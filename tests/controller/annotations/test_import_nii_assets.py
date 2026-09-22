"""Import tests using real public tool-export samples under segment_imports/."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.ai.tseg.seg_retention import MASK_GEOMETRY_FILENAME, mask_geometry_from_image
from anonymizer.controller.annotations import (
    ImportProfile,
    import_folder_binary_masks,
    import_label_nifti,
    load_annotate_session,
    parse_itk_snap_label_file,
    parse_nnunet_dataset_json,
)
from anonymizer.controller.annotations.import_nii import detect_and_import
from tests.controller.paths import CONTROLLER_ASSETS

SEGMENT_IMPORTS = CONTROLLER_ASSETS / "segment_imports"


def _session_for_reference(tmp_path: Path, reference: sitk.Image):
    series = tmp_path / "series"
    series.mkdir()
    cache = resolve_series_cache_dir(series)
    cache.mkdir(parents=True)
    sitk.WriteImage(reference, str(cache / "volume.nii.gz"), True)
    (cache / MASK_GEOMETRY_FILENAME).write_text(
        __import__("json").dumps(mask_geometry_from_image(reference)) + "\n",
        encoding="utf-8",
    )
    session = load_annotate_session(cache)
    assert session is not None
    return session


def test_asset_itk_snap_mri_crop(tmp_path: Path) -> None:
    seg = SEGMENT_IMPORTS / "itk_snap" / "MRIcrop-seg.nii.gz"
    label = SEGMENT_IMPORTS / "itk_snap" / "MRIcrop-seg.label"
    if not seg.is_file() or not label.is_file():
        pytest.skip("ITK-SNAP MRI-crop assets missing")

    parsed = parse_itk_snap_label_file(label)
    assert "caudates" in {e.name for e in parsed.values()}
    assert "hippo-L" in {e.name for e in parsed.values()}

    ref = sitk.ReadImage(str(seg))
    session = _session_for_reference(tmp_path, ref)
    result = import_label_nifti(session, seg, profile=ImportProfile.ITK_SNAP)
    assert result.profile == ImportProfile.ITK_SNAP
    assert len(result.entries) >= 5
    assert int(np.count_nonzero(session.labels)) > 0
    # Names come from official .label sidecar
    names = {e.name for e in result.entries}
    assert names & {p.name for p in parsed.values()}


def test_asset_nnunet_msd_hippocampus(tmp_path: Path) -> None:
    case = SEGMENT_IMPORTS / "nnunet" / "labelsTr" / "hippocampus_001.nii.gz"
    ds_v2 = SEGMENT_IMPORTS / "nnunet" / "dataset.json"
    ds_msd = SEGMENT_IMPORTS / "nnunet" / "dataset_msd.json"
    if not case.is_file() or not ds_v2.is_file():
        pytest.skip("nnU-Net / MSD hippocampus assets missing")

    v2 = parse_nnunet_dataset_json(ds_v2)
    assert v2[1].name == "Anterior"
    assert v2[2].name == "Posterior"
    if ds_msd.is_file():
        msd = parse_nnunet_dataset_json(ds_msd)
        assert msd[1].name == "Anterior"

    ref = sitk.ReadImage(str(case))
    session = _session_for_reference(tmp_path, ref)
    result = import_label_nifti(session, case, profile=ImportProfile.NNUNET)
    assert {e.name for e in result.entries} == {"Anterior", "Posterior"}
    assert int(np.count_nonzero(session.labels)) > 0


def test_asset_totalsegmentator_folder(tmp_path: Path) -> None:
    folder = SEGMENT_IMPORTS / "totalsegmentator" / "folder"
    masks = sorted(folder.glob("*.nii.gz")) if folder.is_dir() else []
    if len(masks) < 2:
        pytest.skip("TotalSegmentator folder assets missing")

    ref = sitk.ReadImage(str(masks[0]))
    session = _session_for_reference(tmp_path, ref)
    result = import_folder_binary_masks(session, folder)
    assert result.profile == ImportProfile.FOLDER_TS
    assert {e.name for e in result.entries} >= {"liver", "aorta", "spleen"}
    assert int(np.count_nonzero(session.labels)) > 0


def test_asset_totalsegmentator_ml(tmp_path: Path) -> None:
    seg = SEGMENT_IMPORTS / "totalsegmentator" / "ml" / "seg.nii.gz"
    if not seg.is_file():
        pytest.skip("TotalSegmentator multilabel asset missing")

    ref = sitk.ReadImage(str(seg))
    session = _session_for_reference(tmp_path, ref)
    result = import_label_nifti(session, seg, profile=ImportProfile.AUTO)
    assert len(result.entries) >= 1
    # class_map.json maps 5 → liver
    assert any(e.name == "liver" for e in result.entries)


def test_asset_slicer_nrrd_labelmap(tmp_path: Path) -> None:
    nrrd = SEGMENT_IMPORTS / "slicer" / "example_labelmap.seg.nrrd"
    tiny = SEGMENT_IMPORTS / "slicer" / "TinyPatient_Structures.seg.nrrd"
    path = tiny if tiny.is_file() else nrrd
    if not path.is_file():
        pytest.skip("Slicer NRRD asset missing — drop TinyPatient_Structures.seg.nrrd into slicer/")

    ref = sitk.ReadImage(str(path))
    session = _session_for_reference(tmp_path, ref)
    result = detect_and_import(session, paths=[path], profile=ImportProfile.MULTILABEL)
    assert len(result.entries) >= 1
    assert int(np.count_nonzero(session.labels)) > 0


def test_asset_mitk_nrrd_labelmap(tmp_path: Path) -> None:
    path = SEGMENT_IMPORTS / "mitk" / "labelmap.nrrd"
    if not path.is_file():
        pytest.skip("MITK NRRD asset missing")

    ref = sitk.ReadImage(str(path))
    session = _session_for_reference(tmp_path, ref)
    result = detect_and_import(session, paths=[path], profile=ImportProfile.MULTILABEL)
    assert len(result.entries) >= 1
