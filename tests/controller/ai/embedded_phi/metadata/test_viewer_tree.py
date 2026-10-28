"""Unit tests: Horos-style metadata tree builder."""

from pathlib import Path

from pydicom import dcmread
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.ai.embedded_phi.metadata.viewer_tree import (
    ITEM_NAME,
    STRUCTURAL_TAG,
    VALUE_NAME,
    MetadataTreeNode,
    build_metadata_tree,
    filter_metadata_tree,
    flatten_tree_paths,
    is_private_metadata_tag,
)
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

DAVIDSON_CXR = (
    CONTROLLER_TEST_DCM_FILES_DIR
    / "davidson_cxr"
    / "davidson_cxr_monochrome1_uncompressed.dcm"
)


def _sc_dataset() -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    # Endian / VR come from TransferSyntaxUID (pydicom 3+; avoid deprecated Dataset flags).
    return ds


def _walk(node: MetadataTreeNode):
    yield node
    for child in node.children:
        yield from _walk(child)


def test_build_tree_multivalue_and_sequence_item_shape() -> None:
    ds = _sc_dataset()
    ds.ImageType = ["DERIVED", "PRIMARY", "MPR"]
    item = Dataset()
    item.ReferencedSOPClassUID = "1.2.840.10008.3.1.2.3.1"
    item.ReferencedSOPInstanceUID = generate_uid()
    ds.ReferencedStudySequence = Sequence([item])

    roots = build_metadata_tree(ds)
    by_path = {n.tag_path: n for n in roots}

    image_type = by_path["ImageType"]
    assert image_type.content == "DERIVED\\PRIMARY\\MPR"
    assert len(image_type.children) == 3
    assert all(c.name == VALUE_NAME and c.tag == STRUCTURAL_TAG for c in image_type.children)
    assert [c.content for c in image_type.children] == ["DERIVED", "PRIMARY", "MPR"]

    seq = by_path["ReferencedStudySequence"]
    assert seq.content == ""
    assert len(seq.children) == 1
    item_node = seq.children[0]
    assert item_node.name == ITEM_NAME
    assert item_node.tag == STRUCTURAL_TAG
    child_paths = {c.tag_path.split(".")[-1] for c in item_node.children}
    assert "ReferencedSOPClassUID" in child_paths
    assert "ReferencedSOPInstanceUID" in child_paths


def test_filter_metadata_tree_keeps_ancestors() -> None:
    ds = _sc_dataset()
    item = Dataset()
    item.CodeMeaning = "Brain: Contrasted"
    ds.ProcedureCodeSequence = Sequence([item])
    roots = build_metadata_tree(ds)
    filtered = filter_metadata_tree(roots, "contrasted")
    assert len(filtered) == 1
    assert filtered[0].tag_path == "ProcedureCodeSequence"
    assert filtered[0].children[0].name == ITEM_NAME
    assert any("Contrasted" in c.content for c in filtered[0].children[0].children)


def test_analyse_davidson_cxr_metadata_tree_includes_description() -> None:
    """Analyse davidson_cxr: full tree includes description-like content and non-text tags."""
    path = Path(DAVIDSON_CXR)
    assert path.is_file(), f"Missing checked-in test DICOM: {path}"
    ds = dcmread(str(path), stop_before_pixels=True, force=True)
    roots = build_metadata_tree(ds)
    paths = set(flatten_tree_paths(roots))
    all_nodes = [n for r in roots for n in _walk(r)]

    # Description-like content or tag present (portable CXR / series labels).
    has_description = (
        "SeriesDescription" in paths
        or "StudyDescription" in paths
        or any(
            "description" in n.name.casefold()
            or "davidson" in n.content.casefold()
            or "chest" in n.content.casefold()
            or "portable" in n.content.casefold()
            for n in all_nodes
        )
    )
    assert has_description

    # Not PHI-only: identity / image geometry tags appear.
    assert "SOPClassUID" in paths or "Modality" in paths
    assert "Rows" in paths or "Columns" in paths or "SOPInstanceUID" in paths


def test_include_file_meta_and_empty_filter() -> None:
    ds = _sc_dataset()
    ds.Modality = "OT"
    roots = build_metadata_tree(ds, include_file_meta=True)
    paths = set(flatten_tree_paths(roots))
    assert any(p.startswith("file_meta.") for p in paths)
    assert filter_metadata_tree(roots, "") == roots
    assert filter_metadata_tree(roots, "   ") == roots


def test_is_private_metadata_tag() -> None:
    assert is_private_metadata_tag("0009,0010")
    assert is_private_metadata_tag("(0009,1001)")
    assert not is_private_metadata_tag("0008,0018")
    assert not is_private_metadata_tag(STRUCTURAL_TAG)
    assert not is_private_metadata_tag("")


def test_filter_metadata_tree_hides_private_tags() -> None:
    ds = _sc_dataset()
    ds.Modality = "OT"
    block = ds.private_block(0x0009, "ACME_VENDOR", create=True)
    block.add_new(0x10, "LO", "secret")
    roots = build_metadata_tree(ds)
    all_paths = set(flatten_tree_paths(roots))
    assert any(is_private_metadata_tag(n.tag) for r in roots for n in _walk(r))
    public_only = filter_metadata_tree(roots, "", include_private=False)
    public_paths = set(flatten_tree_paths(public_only))
    assert "Modality" in public_paths
    assert public_paths < all_paths
    assert not any(is_private_metadata_tag(n.tag) for r in public_only for n in _walk(r))


def test_pixel_data_summary_node() -> None:
    ds = _sc_dataset()
    ds.Rows = 2
    ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData = b"\x00\x01\x02\x03"
    roots = build_metadata_tree(ds)
    by_path = {n.tag_path: n for n in roots}
    assert "PixelData" in by_path
    content = by_path["PixelData"].content
    assert content
    assert "\\x00" not in content  # summarized, not raw dump
