"""Horos-style DICOM metadata tree for one dataset (view-only)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydicom.dataelem import DataElement
from pydicom.dataset import Dataset
from pydicom.multival import MultiValue
from pydicom.sequence import Sequence as DicomSequence
from pydicom.tag import Tag
from pydicom.valuerep import PersonName

from anonymizer.controller.ai.embedded_phi.metadata.extract import element_display_name
from anonymizer.controller.anonymizer_script import format_dicom_tag

STRUCTURAL_TAG = "-"
ITEM_NAME = "item"
VALUE_NAME = "value"
_SEQ_VR = "SQ"
_PIXEL_DATA_TAG = Tag(0x7FE0, 0x0010)


@dataclass
class MetadataTreeNode:
    """One row in the Metadata tree viewer."""

    name: str
    tag: str
    vr: str
    content: str
    tag_path: str
    children: tuple[MetadataTreeNode, ...] = field(default_factory=tuple)


def build_metadata_tree(
    ds: Dataset,
    *,
    include_file_meta: bool = False,
) -> list[MetadataTreeNode]:
    """
    Walk ``ds`` into a Horos-like tree: SQ → ``item`` children, VM>1 → ``value`` children.

    Pixel Data is summarized (VR / length) without dumping bytes.
    """
    roots: list[MetadataTreeNode] = []
    if include_file_meta and getattr(ds, "file_meta", None):
        for elem in ds.file_meta:
            roots.append(_element_node(ds.file_meta, elem, prefix="file_meta"))
    for elem in ds:
        roots.append(_element_node(ds, elem, prefix=""))
    return roots


def filter_metadata_tree(
    nodes: Sequence[MetadataTreeNode],
    query: str,
) -> list[MetadataTreeNode]:
    """Keep nodes matching ``query`` (case-insensitive) and ancestors of matches."""
    needle = str(query or "").strip().lower()
    if not needle:
        return list(nodes)
    out: list[MetadataTreeNode] = []
    for node in nodes:
        filtered = _filter_node(node, needle)
        if filtered is not None:
            out.append(filtered)
    return out


def flatten_tree_paths(nodes: Sequence[MetadataTreeNode]) -> list[str]:
    """All ``tag_path`` values depth-first (tests / search helpers)."""
    paths: list[str] = []

    def walk(n: MetadataTreeNode) -> None:
        paths.append(n.tag_path)
        for child in n.children:
            walk(child)

    for node in nodes:
        walk(node)
    return paths


def _filter_node(node: MetadataTreeNode, needle: str) -> MetadataTreeNode | None:
    child_hits = [c for c in (_filter_node(ch, needle) for ch in node.children) if c is not None]
    self_hit = needle in " ".join(
        (node.name, node.tag, node.vr, node.content, node.tag_path)
    ).lower()
    if not self_hit and not child_hits:
        return None
    if child_hits and not self_hit:
        return MetadataTreeNode(
            name=node.name,
            tag=node.tag,
            vr=node.vr,
            content=node.content,
            tag_path=node.tag_path,
            children=tuple(child_hits),
        )
    if child_hits:
        return MetadataTreeNode(
            name=node.name,
            tag=node.tag,
            vr=node.vr,
            content=node.content,
            tag_path=node.tag_path,
            children=tuple(child_hits),
        )
    return node


def _element_node(ds: Dataset, elem: DataElement, *, prefix: str) -> MetadataTreeNode:
    tag_hex = f"{int(elem.tag):08X}"
    tag_label = format_dicom_tag(tag_hex)
    name = element_display_name(ds, elem)
    vr = str(elem.VR or "")
    token = str(elem.keyword) if elem.keyword else tag_label
    path = f"{prefix}.{token}" if prefix else token

    if elem.tag == _PIXEL_DATA_TAG:
        return MetadataTreeNode(
            name=name,
            tag=tag_label,
            vr=vr or "OB",
            content=_pixel_data_summary(elem),
            tag_path=path,
        )

    if vr == _SEQ_VR or isinstance(elem.value, DicomSequence):
        children: list[MetadataTreeNode] = []
        seq = elem.value if isinstance(elem.value, DicomSequence) else ()
        for i, item in enumerate(seq):
            item_path = f"{path}[{i}]"
            item_children: list[MetadataTreeNode] = []
            if isinstance(item, Dataset):
                for nested in item:
                    item_children.append(_element_node(item, nested, prefix=item_path))
            children.append(
                MetadataTreeNode(
                    name=ITEM_NAME,
                    tag=STRUCTURAL_TAG,
                    vr="",
                    content="",
                    tag_path=item_path,
                    children=tuple(item_children),
                )
            )
        return MetadataTreeNode(
            name=name,
            tag=tag_label,
            vr=vr or _SEQ_VR,
            content="",
            tag_path=path,
            children=tuple(children),
        )

    values = _split_values(elem)
    if len(values) > 1:
        joined = "\\".join(values)
        value_children = tuple(
            MetadataTreeNode(
                name=VALUE_NAME,
                tag=STRUCTURAL_TAG,
                vr="",
                content=part,
                tag_path=f"{path}[{i}]",
            )
            for i, part in enumerate(values)
        )
        return MetadataTreeNode(
            name=name,
            tag=tag_label,
            vr=vr,
            content=joined,
            tag_path=path,
            children=value_children,
        )

    return MetadataTreeNode(
        name=name,
        tag=tag_label,
        vr=vr,
        content=values[0] if values else "",
        tag_path=path,
    )


def _pixel_data_summary(elem: DataElement) -> str:
    vr = str(elem.VR or "OB")
    try:
        length = int(getattr(elem, "VM", 0) or 0)
    except Exception:
        length = 0
    try:
        raw_len = len(elem.value)  # type: ignore[arg-type]
        return f"{vr} · {raw_len} bytes"
    except Exception:
        if length:
            return f"{vr} · VM={length}"
        return f"{vr} · (pixel data)"


def _split_values(elem: DataElement) -> list[str]:
    value = elem.value
    if value is None:
        return []
    if isinstance(value, PersonName):
        return [str(value)]
    if isinstance(value, (MultiValue, list, tuple)):
        return [_format_atomic(v) for v in value]
    text = _format_atomic(value)
    if "\\" in text and str(elem.VR or "") in {"CS", "DS", "IS", "SS", "US", "FD", "FL"}:
        # Already a single string with backslash VM — split for value children.
        parts = [p for p in text.split("\\")]
        if len(parts) > 1:
            return parts
    return [text] if text else []


def _format_atomic(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) > 64:
            return f"0x{raw[:16].hex()}… ({len(raw)} bytes)"
        try:
            return raw.decode("utf-8", errors="replace").strip()
        except Exception:
            return f"0x{raw.hex()}"
    if isinstance(value, PersonName):
        return str(value)
    return str(value).strip()
