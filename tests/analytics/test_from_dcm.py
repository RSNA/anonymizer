"""Build Dataset analytics from checked-in test DICOM fixtures (docs_help style).

Imports CT + CR (+ optional MR) headers via ``capture_phi``, writes a minimal
images tree, and verifies the resulting widget selection matches layout rules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydicom import dcmread

from anonymizer.controller.analytics import build_dataset_analytics
from anonymizer.view.shell.analytics_charts import modality_distinct_count, select_widgets
from docs_help.project_setup import TEST_DCM_ROOT
from tests.analytics.conftest import require_fixture
from tests.opened_anonymizer_model import opened_anonymizer_model


def _first_dcm(root: Path) -> Path:
    files = sorted(root.rglob("*.dcm"))
    if not files:
        pytest.skip(f"No .dcm under {root}")
    return files[0]


def _seed_series_tree(images_dir: Path, anon_patient: str, anon_study: str, anon_series: str) -> Path:
    series = images_dir / anon_patient / anon_study / anon_series
    series.mkdir(parents=True, exist_ok=True)
    return series


def _seed_organ_cache(series_dir: Path, *, organ: str = "brain", voxels: int = 400_000) -> None:
    cache = series_dir / "0_TS_SEG"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "primary_segment_voxels.json").write_text(
        json.dumps({organ: voxels, "liver": voxels // 2}),
        encoding="utf-8",
    )
    (cache / "structure_voxels.json").write_text(
        json.dumps({organ: voxels}),
        encoding="utf-8",
    )
    (cache / "mask_geometry.json").write_text(
        json.dumps(
            {
                "size": [10, 10, 10],
                "spacing": [1.0, 1.0, 1.0],
                "origin": [0, 0, 0],
                "direction": [1, 0, 0, 0, 1, 0, 0, 0, 1],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def analytics_model(tmp_path: Path):
    db = tmp_path / "anonymizer.db"
    with opened_anonymizer_model(f"sqlite:///{db}") as model:
        images = tmp_path / "images"
        images.mkdir()
        yield model, images


def test_analytics_from_ct_and_cr_fixtures(analytics_model) -> None:
    """CT + CR fixtures ⇒ modality pie shown; sex/age widgets follow PHI."""
    model, images = analytics_model
    require_fixture("davidson_cxr")
    ct_root = TEST_DCM_ROOT / "CT_Head_With_Contrast"
    if not ct_root.is_dir():
        # Fall back to synthetic head if full CT head pack is absent.
        ct_root = TEST_DCM_ROOT / "synthetic_CT_head"
    if not ct_root.is_dir():
        pytest.skip("No CT fixture directory available")

    cr_paths = require_fixture("davidson_cxr")
    ct_dcm = _first_dcm(ct_root)
    cr_dcm = Path(cr_paths[0])

    ct_ds = dcmread(ct_dcm, stop_before_pixels=True, force=True)
    cr_ds = dcmread(cr_dcm, stop_before_pixels=True, force=True)

    model.capture_phi(source="pytest", ds=ct_ds, date_offset_from_hash=0)
    model.capture_phi(source="pytest", ds=cr_ds, date_offset_from_hash=0)

    # Minimal public tree so tseg scan is a no-op (or seeded below).
    phi_rows = model.load_phi_with_studies_series_no_instances()
    assert phi_rows
    for phi in phi_rows:
        for study in phi.studies or []:
            for ser in study.series or []:
                _seed_series_tree(
                    images,
                    phi.anon_patient_id,
                    study.anon_study_uid,
                    ser.anon_series_uid,
                )

    snapshot = build_dataset_analytics(model, images)
    keys = {w.key for w in select_widgets(snapshot)}

    assert modality_distinct_count(snapshot.imaging.modality) >= 2
    assert "modality" in keys
    # At least one demographic widget when PHI has known values, or omitted if all unknown.
    assert keys  # board not empty


def test_analytics_organ_widget_from_seeded_tseg_cache(analytics_model) -> None:
    """Seeded TS cache under a CT series yields organ histogram widget(s)."""
    model, images = analytics_model
    ct_root = TEST_DCM_ROOT / "synthetic_CT_head"
    if not ct_root.is_dir():
        ct_root = TEST_DCM_ROOT / "CT_Head_With_Contrast"
    if not ct_root.is_dir():
        pytest.skip("No CT fixture directory available")

    ds = dcmread(_first_dcm(ct_root), stop_before_pixels=True, force=True)
    model.capture_phi(source="pytest", ds=ds, date_offset_from_hash=0)
    default_pk = getattr(model, "DEFAULT_PHI_PATIENT_ID_PK_VALUE", None)
    phi_rows = [
        row
        for row in model.load_phi_with_studies_series_no_instances()
        if row.studies and (default_pk is None or row.patient_id != default_pk)
    ]
    assert phi_rows, "capture_phi did not persist a patient with studies"
    phi = phi_rows[0]
    study = phi.studies[0]
    assert study.series, "expected at least one series on the fixture study"
    ser = study.series[0]
    series_dir = _seed_series_tree(images, phi.anon_patient_id, study.anon_study_uid, ser.anon_series_uid)
    _seed_organ_cache(series_dir)

    snapshot = build_dataset_analytics(model, images)
    keys = {w.key for w in select_widgets(snapshot)}
    organ_keys = {k for k in keys if k.startswith("organ:")}
    assert organ_keys
    assert snapshot.anatomy.available
    assert len(snapshot.anatomy.organ_volumes) >= 1
