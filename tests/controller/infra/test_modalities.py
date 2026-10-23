"""Pure-function coverage for modalities helpers (no mocks)."""

import pytest

import anonymizer.utils.modalities as modalities_module
from anonymizer.mcp.modality_tokens import resolve_modality_code, resolve_project_modalities
from anonymizer.utils.modalities import (
    DEFAULT_PROJECT_MODALITIES,
    XR_MODALITIES,
    ContentClass,
    Modality,
    get_modality_catalog,
)


def test_removed_modality_helpers_not_exported() -> None:
    """Legacy parse/predicate helpers must not reappear on ``modalities``."""
    for name in (
        "parse_modality",
        "has_harmonize_path",
        "is_xr_modality",
        "same_2d_playbook",
        "_HARMONIZE_PATH_MODALITIES",
        "_XR_PLAYBOOK_MODALITIES",
        "content_class",
        "get_modalities",
    ):
        assert not hasattr(modalities_module, name), name


def test_get_modality_catalog():
    data = get_modality_catalog()
    assert isinstance(data, dict)
    expected = {
        Modality.CR,
        Modality.DX,
        Modality.IO,
        Modality.MG,
        Modality.CT,
        Modality.MR,
        Modality.US,
        Modality.PT,
        Modality.NM,
        Modality.SC,
        Modality.SR,
        Modality.PR,
        Modality.PDF,
        Modality.OT,
        Modality.DOC,
    }
    assert set(data.keys()) == expected
    sr_uids = data[Modality.SR].sop_class_uids
    # Retain profile enables SR → must accept all …88.* storage classes (dose SRs included).
    assert "1.2.840.10008.5.1.4.1.1.88.67" in sr_uids  # X-Ray Radiation Dose SR
    assert "1.2.840.10008.5.1.4.1.1.88.68" in sr_uids  # Radiopharmaceutical Radiation Dose SR
    assert "1.2.840.10008.5.1.4.1.1.88.73" in sr_uids  # Patient Radiation Dose SR
    assert "1.2.840.10008.5.1.4.1.1.88.76" in sr_uids  # Enhanced X-Ray Radiation Dose SR
    assert all(u.startswith("1.2.840.10008.5.1.4.1.1.88.") for u in sr_uids)
    assert len(sr_uids) >= 20
    assert data[Modality.CT].content_class is ContentClass.D3
    assert data[Modality.PT].content_class is ContentClass.D3
    assert data[Modality.CR].content_class is ContentClass.D2
    assert data[Modality.SC].content_class is ContentClass.D2
    assert data[Modality.SR].content_class is ContentClass.TEXT
    assert get_modality_catalog()[Modality.CT].harmonize is True
    assert get_modality_catalog()[Modality.US].harmonize is True
    assert get_modality_catalog()[Modality.SR].harmonize is True
    assert get_modality_catalog()[Modality.SC].harmonize is False
    assert get_modality_catalog()[Modality.PT].harmonize is False


def test_from_code_and_catalog_content_class() -> None:
    catalog = get_modality_catalog()
    assert Modality.from_code("ct") is None
    assert Modality.from_code("mri") is None
    assert Modality.from_code("MR") is Modality.MR
    assert Modality.from_code(None) is None
    assert Modality.from_code("") is None
    assert catalog[Modality.CT].content_class is ContentClass.D3
    assert catalog[Modality.MR].content_class is ContentClass.D3
    assert catalog[Modality.CR].content_class is ContentClass.D2
    assert catalog[Modality.SR].content_class is ContentClass.TEXT
    assert Modality.CR in XR_MODALITIES
    assert Modality.DX in XR_MODALITIES
    assert Modality.MG not in XR_MODALITIES
    assert DEFAULT_PROJECT_MODALITIES == (Modality.CR, Modality.DX, Modality.CT, Modality.MR)


def test_xr_modalities_set() -> None:
    """CR and DX are the shared XR modality set."""
    assert XR_MODALITIES == frozenset({Modality.CR, Modality.DX})
    assert Modality.US not in XR_MODALITIES


def test_resolve_modality_code_and_project_modalities() -> None:
    assert resolve_modality_code("CT") == "CT"
    assert resolve_modality_code("computed tomography") == "CT"
    resolved = resolve_project_modalities(["CT", "MR", "defaults"])
    assert resolved is not None
    assert "CT" in resolved
    assert "MR" in resolved
    assert "CR" in resolved
    with pytest.raises(ValueError, match="Unknown modality"):
        resolve_project_modalities(["bogus"])
