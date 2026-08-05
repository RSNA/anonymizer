"""Tests for RadLex Playbook harmonization codes and series-description formatting."""

from __future__ import annotations

from dataclasses import replace

import pytest

from anonymizer.controller.tseg.dicom_geometry import SeriesGeometryResult
from anonymizer.controller.tseg.radlex_playbook import (
    IV_CONTRAST_PLAYBOOK_CODES,
    build_harmonized_series_description,
    build_localizer_harmonized_series_description,
    build_playbook_attributes,
    format_playbook_series_description,
    harmonize_analysis_rows,
    map_anatomic_plane_code,
    map_body_part_code,
    map_iv_contrast_code,
    map_series_type_code,
    playbook_iv_contrast_row_values,
    series_type_label,
)
from anonymizer.controller.tseg.segment import TS_result


def _geometry(*, plane: str = "axial", plane_confidence: float = 0.99) -> SeriesGeometryResult:
    angles = {"axial": 5.0, "coronal": 85.0, "sagittal": 85.0}
    if plane == "sagittal":
        angles = {"axial": 85.0, "coronal": 85.0, "sagittal": 5.0}
    if plane == "coronal":
        angles = {"axial": 85.0, "coronal": 5.0, "sagittal": 85.0}
    if plane == "oblique":
        angles = {"axial": 20.0, "coronal": 70.0, "sagittal": 70.0}
    return SeriesGeometryResult(
        plane=plane,  # type: ignore[arg-type]
        plane_confidence=plane_confidence,
        slice_normal_lps=(0.0, 0.0, 1.0),
        plane_angles_deg=angles,
        dimensionality="volume_3d",
        n_slices=24,
        through_plane_extent_mm=120.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=True,
        metadata_suspect=False,
        method="dicom_headers",
        notes="",
    )


def _tseg(
    *,
    body_parts_present: str = "Chest",
    contrast_phase: str = "native",
    iv_contrast: bool = False,
    structures_present: dict[str, int] | None = None,
) -> TS_result:
    return TS_result(
        series_directory=__import__("pathlib").Path("/tmp/series"),
        dominant_region=body_parts_present.split("+")[0],
        body_parts_present=body_parts_present,
        multi_region="+" in body_parts_present,
        region_fraction=0.91,
        iv_contrast=iv_contrast,
        contrast_phase=contrast_phase,
        phase_probability=0.88 if contrast_phase else 0.0,
        radlex_series_description="",
        structures_present=structures_present or {},
    )


@pytest.mark.parametrize(
    ("regions", "structures", "expected"),
    [
        ("Head", {"brain": 50000}, "Brain"),
        ("Head", {"skull": 50000}, "Head"),
        ("Head", {}, "Brain"),
        ("Chest", {}, "Ch"),
        ("Abdomen", {}, "Abd"),
        ("Chest+Abdomen", {}, "Ch+Abd"),
    ],
)
def test_map_body_part_code(regions: str, structures: dict[str, int], expected: str) -> None:
    assert map_body_part_code(regions, structures) == expected


def test_map_anatomic_plane_code_cardinal() -> None:
    assert map_anatomic_plane_code(_geometry(plane="axial")) == "Ax"
    assert map_anatomic_plane_code(_geometry(plane="sagittal")) == "Sag"
    assert map_anatomic_plane_code(_geometry(plane="coronal")) == "Cor"


def test_map_anatomic_plane_code_oblique_uses_nearest_cardinal() -> None:
    assert map_anatomic_plane_code(_geometry(plane="oblique")) == "Ax_Obl"


@pytest.mark.parametrize(
    ("phase", "iv_contrast", "expected"),
    [
        ("native", False, "WO"),
        ("portal_venous", True, "PortVen"),
        ("arterial_early", True, "EarlyArt"),
        ("arterial_late", True, "LateArt"),
        ("arterial", True, "Art"),
        ("venous", True, "Ven"),
        ("delayed", True, "Delay"),
        ("pulmonary_arterial", True, "PulmArt"),
        ("nephrogenic", True, "Neph"),
        ("cortomedullary", True, "CortMed"),
        ("equilibrium", True, "Equil"),
        ("excretory", True, "Excretory"),
        ("dynamic", True, "Dyn"),
        ("unknown_phase", True, "W"),
        ("unknown_phase", False, "WO"),
        ("", True, "W"),
        ("", False, "WO"),
    ],
)
def test_map_iv_contrast_code(phase: str, iv_contrast: bool, expected: str) -> None:
    assert map_iv_contrast_code(_tseg(contrast_phase=phase, iv_contrast=iv_contrast)) == expected
    assert expected in IV_CONTRAST_PLAYBOOK_CODES


def test_iv_contrast_playbook_vocab_matches_radlex() -> None:
    assert IV_CONTRAST_PLAYBOOK_CODES == frozenset(
        {
            "WO",
            "W",
            "Art",
            "Ven",
            "Delay",
            "EarlyArt",
            "LateArt",
            "PulmArt",
            "PortVen",
            "Neph",
            "CortMed",
            "Equil",
            "Excretory",
            "Dyn",
        }
    )


def test_iv_contrast_labels_cover_playbook_vocab() -> None:
    from anonymizer.controller.tseg.radlex_playbook import _IV_CONTRAST_LABELS, _TS_CONTRAST_PHASE_TO_CODE

    assert set(_IV_CONTRAST_LABELS) == IV_CONTRAST_PLAYBOOK_CODES
    assert set(_TS_CONTRAST_PHASE_TO_CODE.values()).issubset(IV_CONTRAST_PLAYBOOK_CODES)


def test_contrast_series_playbook_row_uses_radlex_iv_contrast_code() -> None:
    attributes = build_playbook_attributes(
        _tseg(body_parts_present="Chest", contrast_phase="portal_venous", iv_contrast=True),
        _geometry(plane="axial"),
    )
    element, code, value, evidence, source = playbook_iv_contrast_row_values(attributes)
    assert element == "IV Contrast Phase"
    assert code == "PortVen"
    assert value == "Portal venous"
    assert code in IV_CONTRAST_PLAYBOOK_CODES
    assert "portal venous" in evidence
    assert "TotalSegmentator contrast" in source


def test_harmonize_analysis_rows_iv_contrast_code_is_radlex_vocab() -> None:
    attributes = build_playbook_attributes(
        _tseg(body_parts_present="Chest", contrast_phase="portal_venous", iv_contrast=True),
        _geometry(plane="axial"),
    )
    contrast_row = harmonize_analysis_rows(attributes, geometry=_geometry(plane="axial"))[2]
    assert contrast_row[1] == "PortVen"
    assert contrast_row[1] in IV_CONTRAST_PLAYBOOK_CODES


def test_build_harmonized_series_description_head_native_axial() -> None:
    description, attributes = build_harmonized_series_description(
        _tseg(
            body_parts_present="Head",
            contrast_phase="native",
            structures_present={"brain": 50000},
        ),
        _geometry(plane="axial"),
    )
    assert description == "Brain Ax WO"
    assert attributes.body_part_code == "Brain"
    assert attributes.iv_contrast_code == "WO"
    assert attributes.anatomic_plane_code == "Ax"


def test_build_harmonized_series_description_chest_portal_oblique() -> None:
    geometry = _geometry(plane="oblique")
    attributes = build_playbook_attributes(
        _tseg(body_parts_present="Chest", contrast_phase="portal_venous", iv_contrast=True),
        geometry,
    )
    assert attributes.anatomic_plane_code == "Ax_Obl"
    assert format_playbook_series_description(attributes, geometry) == "Ch Ax_Obl PortVen"


def test_native_series_description_includes_wo_contrast_element() -> None:
    geometry = _geometry(plane="axial")
    attributes = build_playbook_attributes(
        _tseg(body_parts_present="Chest", contrast_phase="native"),
        geometry,
    )
    assert attributes.iv_contrast_code == "WO"
    assert format_playbook_series_description(attributes, geometry) == "Ch Ax WO"


def test_localizer_series_description_omits_plane() -> None:
    geometry = replace(_geometry(plane="axial"), dimensionality="localizer_2d")
    attributes = build_playbook_attributes(
        _tseg(body_parts_present="Chest", contrast_phase="native"),
        geometry,
    )
    assert format_playbook_series_description(attributes, geometry) == "Ch WO Localizer"


def test_localizer_harmonized_from_dicom_body_part() -> None:
    from pydicom import Dataset

    geometry = replace(_geometry(plane="axial"), dimensionality="localizer_2d")
    ds = Dataset()
    ds.BodyPartExamined = "CHEST"
    ds.SeriesDescription = "SCOUT TOPOGRAM"

    description, attributes = build_localizer_harmonized_series_description(ds, geometry)

    assert description == "Ch WO Localizer"
    assert attributes.body_part_code == "Ch"
    assert attributes.iv_contrast_code == "WO"
    assert attributes.anatomic_plane_code == ""
    assert attributes.series_type_code == "Localizer"


@pytest.mark.parametrize(
    ("geometry_kwargs", "dicom_fields", "expected"),
    [
        ({}, {}, ""),
        (
            {"provenance": "derived_3d_render"},
            {"SeriesDescription": "Chest MIP"},
            "Postprocess",
        ),
        (
            {"dimensionality": "projection_2d", "provenance": "derived_secondary"},
            {"ImageType": ["DERIVED", "SECONDARY"]},
            "Screenshot",
        ),
        (
            {},
            {"SeriesDescription": "PET/CT FUSION"},
            "Fused",
        ),
        (
            {},
            {"SeriesDescription": "CONTRAST DOSE SHEET"},
            "Contrast_Dose",
        ),
        (
            {},
            {"SeriesDescription": "BOLUS MONITOR"},
            "Monitoring",
        ),
    ],
)
def test_map_series_type_code(
    geometry_kwargs: dict[str, object],
    dicom_fields: dict[str, object],
    expected: str,
) -> None:
    from pydicom import Dataset

    geometry = replace(_geometry(), **geometry_kwargs)
    ds = Dataset()
    for keyword, value in dicom_fields.items():
        setattr(ds, keyword, value)
    assert map_series_type_code(ds, geometry) == expected


def test_series_type_label_uses_playbook_definition() -> None:
    assert series_type_label("Localizer") == "Exam localizer"
    assert series_type_label("") == "—"
