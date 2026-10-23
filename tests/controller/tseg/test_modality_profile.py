"""Tests for modality profile resolution."""

from anonymizer.utils.modalities import ContentClass, Modality, get_modality_catalog


def test_from_code_exact_dicom_codes_only():
    assert Modality.from_code("mri") is None
    assert Modality.from_code("MR") is Modality.MR
    assert Modality.from_code("ct") is None
    assert Modality.from_code("CT") is Modality.CT
    assert Modality.from_code(None) is None


def test_content_class_for_catalog_modalities():
    catalog = get_modality_catalog()
    assert catalog[Modality.CT].content_class is ContentClass.D3
    assert catalog[Modality.MR].content_class is ContentClass.D3
    assert catalog[Modality.US].content_class is ContentClass.D2
    assert catalog[Modality.DX].content_class is ContentClass.D2
