"""Extract free-text and date PHI carriers from DICOM metadata (SOP-agnostic).

Public API
----------
TEXT_VRS
    Text vrs.

DATE_VRS
    Date vrs.

SKIP_TEXT_KEYWORDS
    Skip text keywords.

VR_SEQ_TEXT
    Vr seq text (default 'SEQ(text)').

ResolveKeep
    Resolvekeep.

SpanFragment
    One leaf value inside a compiled SEQ(text) cell.

MetadataPhiRow
    One Metadata assessment row (flat text/date or compiled sequence text).

is_anonymizer_stamp_row(row: MetadataPhiRow) -> bool
    Detect PatientIdentityRemoved / DeidentificationMethod(+CodeSeq) / 0013 site block.

is_anonymizer_field(*, tag: str='', name: str='', tag_path: str='') -> bool
    True for de-identification stamps / anonymizer-added private group (0013).

extract_metadata_phi_rows(ds: Dataset, *, resolve_keep: ResolveKeep | None=None) -> list[MetadataPhiRow]
    Walk ds and return PHI-oriented metadata rows (top-level + SEQ(text)).

apply_text_at_path(ds: Dataset, tag_path: str, new_text: str) -> None
    Set the leaf string at tag_path (e.g. ContentSequence[0].TextValue).

scrub_span_in_row(ds: Dataset, row: MetadataPhiRow, start: int, end: int, replacement: str) -> str
    Replace [start:end) inside a SEQ(text) row by writing replacement

element_display_name(ds: Dataset, elem: DataElement) -> str
    Public Name column label (TCIA / creator / dictionary); never bare Private.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from pydicom.dataelem import DataElement
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.tag import BaseTag, Tag

from anonymizer.controller.dates import is_date_delta_operation
from anonymizer.controller.private_tags import (
    PrivateTagEntry,
    lookup_private_tag,
    private_creator_string,
)
from anonymizer.utils.dicom_dictionary import display_tag_vr, format_dicom_tag

logger = logging.getLogger(__name__)

TEXT_VRS = frozenset({"LO", "LT", "ST", "SH", "UT", "UC", "UR", "PN"})
DATE_VRS = frozenset({"DA", "DT"})
# Code-set plumbing — not free-text PHI carriers inside Concept Name sequences.
# Public: the metadata NER pre-filter skips these same keywords (single source).
SKIP_TEXT_KEYWORDS = frozenset(
    {
        "CodeValue",
        "CodingSchemeDesignator",
        "CodingSchemeVersion",
        "CodingSchemeUID",
        "ContextUID",
        "MappingResource",
        "MappingResourceUID",
        "ValueType",
        "RelationshipType",
        "ContinuityOfContent",
    }
)
_SEQ_VR = "SQ"
VR_SEQ_TEXT = "SEQ(text)"
_FRAGMENT_SEP = " • "
_HEX_NAME = re.compile(r"^\([0-9A-Fa-f]{4},[0-9A-Fa-f]{4}\)$")
_PLAIN_HEX_NAME = re.compile(r"^[0-9A-Fa-f]{4},[0-9A-Fa-f]{4}$")
_PATH_SEGMENT = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*|\([0-9A-Fa-f]{4},[0-9A-Fa-f]{4}\)|[0-9A-Fa-f]{4},[0-9A-Fa-f]{4})"
    r"(?:\[(?P<index>\d+)\])?$"
)


def _tag_from_path_name(name: str) -> BaseTag | None:
    """DICOM tag for a (GGGG,EEEE) or GGGG,EEEE path segment, else None."""
    if _HEX_NAME.match(name):
        return Tag(int(name[1:5], 16), int(name[6:10], 16))
    if _PLAIN_HEX_NAME.match(name):
        return Tag(int(name[:4], 16), int(name[5:], 16))
    return None

ResolveKeep = Callable[[str], str | None]


@dataclass(frozen=True)
class SpanFragment:
    """One leaf value inside a compiled SEQ(text) cell."""

    start: int
    end: int
    tag_path: str
    leaf_text: str


# Tags / keywords written by the anonymizer as de-identification stamps (not source PHI).
_ANONYMIZER_STAMP_TAGS = frozenset(
    {
        "00120062",  # PatientIdentityRemoved
        "00120063",  # DeidentificationMethod
        "00120064",  # DeidentificationMethodCodeSequence
    }
)
_ANONYMIZER_STAMP_KEYWORDS = frozenset(
    {
        "PatientIdentityRemoved",
        "DeidentificationMethod",
        "DeIdentificationMethod",
        "DeidentificationMethodCodeSequence",
        "DeIdentificationMethodCodeSequence",
        "DeIdentificationMethodCodeSeq",
    }
)
# Site / project private block added by AnonymizerController after script walk.
_ANONYMIZER_PRIVATE_GROUP = "0013"


@dataclass(frozen=True)
class MetadataPhiRow:
    """One Metadata assessment row (flat text/date or compiled sequence text)."""

    tag: str
    vr: str
    name: str
    text: str
    is_private: bool
    tag_path: str
    date_shift_covered: bool = False
    tcia_action: str | None = None
    iod_unexpected: bool = False
    script_operation: str | None = None
    spans: tuple[SpanFragment, ...] = field(default_factory=tuple)

    @property
    def is_seq_text(self) -> bool:
        return self.vr == VR_SEQ_TEXT

    @property
    def is_date(self) -> bool:
        return self.vr in DATE_VRS

    @property
    def tag_hex(self) -> str:
        """Eight-hex tag without comma (GGGGEEEE)."""
        return self.tag.replace(",", "").upper()

    @property
    def is_anonymizer_field(self) -> bool:
        """True for de-identification stamps / anonymizer-added metadata."""
        return is_anonymizer_stamp_row(self)


def is_anonymizer_stamp_row(row: MetadataPhiRow) -> bool:
    """Detect PatientIdentityRemoved / DeidentificationMethod(+CodeSeq) / 0013 site block."""
    return is_anonymizer_field(tag=row.tag, name=row.name, tag_path=row.tag_path)


def is_anonymizer_field(*, tag: str = "", name: str = "", tag_path: str = "") -> bool:
    """True for de-identification stamps / anonymizer-added private group (0013)."""
    hex8 = str(tag or "").replace(",", "").replace(" ", "").upper()
    if len(hex8) == 8 and hex8 in _ANONYMIZER_STAMP_TAGS:
        return True
    if len(hex8) == 8 and hex8.startswith(_ANONYMIZER_PRIVATE_GROUP):
        return True
    root = str(tag_path or name or "").split("[", 1)[0].split(".", 1)[0]
    return root in _ANONYMIZER_STAMP_KEYWORDS

@dataclass(frozen=True)
class _LeafText:
    tag_path: str
    text: str
    concept: str = ""


def extract_metadata_phi_rows(
    ds: Dataset,
    *,
    resolve_keep: ResolveKeep | None = None,
) -> list[MetadataPhiRow]:
    """Walk ds and return PHI-oriented metadata rows (top-level + SEQ(text))."""
    rows: list[MetadataPhiRow] = []
    for elem in ds:
        if elem.VR == _SEQ_VR:
            seq_row = _build_seq_text_row(ds, elem)
            if seq_row is not None:
                rows.append(seq_row)
            seq_val = elem.value if isinstance(elem.value, DicomSequence) else ()
            rows.extend(
                _iter_seq_date_rows(
                    seq_val,
                    prefix=_elem_path_token(elem),
                    resolve_keep=resolve_keep,
                    root_ds=ds,
                )
            )
            continue
        leaf = _leaf_row(
            elem,
            path=_elem_path_token(elem),
            resolve_keep=resolve_keep,
            root_ds=ds,
        )
        if leaf is not None:
            rows.append(leaf)
    return rows


def apply_text_at_path(ds: Dataset, tag_path: str, new_text: str) -> None:
    """Set the leaf string at tag_path (e.g. ContentSequence[0].TextValue)."""
    parent, name = _resolve_leaf_parent(ds, tag_path)
    tag = _tag_from_path_name(name)
    if tag is not None:
        parent[tag].value = new_text
        return
    if name in parent:
        parent[name].value = new_text
        return
    setattr(parent, name, new_text)


def scrub_span_in_row(
    ds: Dataset,
    row: MetadataPhiRow,
    start: int,
    end: int,
    replacement: str,
) -> str:
    """
    Replace [start:end) inside a SEQ(text) row by writing replacement
    to the owning leaf; return the rebuilt compiled text.
    """
    if not row.is_seq_text:
        raise ValueError("scrub_span_in_row requires a SEQ(text) row")
    if start < 0 or end > len(row.text) or start >= end:
        raise ValueError(f"Invalid span [{start}:{end}) for text length {len(row.text)}")
    target: SpanFragment | None = None
    for span in row.spans:
        if span.start <= start and end <= span.end:
            target = span
            break
    if target is None:
        raise ValueError(f"No leaf span covers [{start}:{end})")
    apply_text_at_path(ds, target.tag_path, replacement)
    for again in extract_metadata_phi_rows(ds):
        if again.tag_path == row.tag_path and again.is_seq_text:
            return again.text
    return replacement


def _build_seq_text_row(ds: Dataset, elem: DataElement) -> MetadataPhiRow | None:
    if not isinstance(elem.value, DicomSequence) or not elem.value:
        return None
    root_token = _elem_path_token(elem)
    leaves = list(_iter_seq_text_leaves(elem.value, prefix=root_token))
    if not leaves:
        return None
    compiled, spans = _compile_fragments(leaves)
    tag_hex = f"{int(elem.tag):08X}"
    is_private = bool(elem.tag.is_private)
    creator = private_creator_string(ds, elem.tag) if is_private else ""
    tcia = _private_kb_entry(elem.tag, creator) if is_private else None
    name = _display_name(
        elem,
        is_private=is_private,
        tcia_name=tcia.display_name if tcia else None,
        creator=creator,
    )
    return MetadataPhiRow(
        tag=format_dicom_tag(tag_hex),
        vr=VR_SEQ_TEXT,
        name=name,
        text=compiled,
        is_private=is_private,
        tag_path=root_token,
        tcia_action=tcia.action.value if tcia else None,
        spans=spans,
    )


def _leaf_row(
    elem: DataElement,
    *,
    path: str,
    resolve_keep: ResolveKeep | None,
    root_ds: Dataset,
) -> MetadataPhiRow | None:
    vr = str(elem.VR or "")
    if vr not in TEXT_VRS and vr not in DATE_VRS:
        return None
    text = _as_str(elem.value)
    if not text:
        return None
    tag_hex = f"{int(elem.tag):08X}"
    is_private = bool(elem.tag.is_private)
    creator = private_creator_string(root_ds, elem.tag) if is_private else ""
    tcia = _private_kb_entry(elem.tag, creator) if is_private else None
    name = _display_name(
        elem,
        is_private=is_private,
        tcia_name=tcia.display_name if tcia else None,
        creator=creator,
    )
    script_operation: str | None = None
    covered = False
    if resolve_keep is not None:
        script_operation = resolve_keep(tag_hex)
        if vr in DATE_VRS:
            covered = is_date_delta_operation(script_operation)
    return MetadataPhiRow(
        tag=format_dicom_tag(tag_hex),
        vr=vr if vr in DATE_VRS else (display_tag_vr(tag_hex) or vr),
        name=name,
        text=text,
        is_private=is_private,
        tag_path=path,
        date_shift_covered=covered,
        tcia_action=tcia.action.value if tcia else None,
        script_operation=script_operation,
    )


def _iter_seq_text_leaves(seq: DicomSequence, *, prefix: str) -> Iterator[_LeafText]:
    for i, item in enumerate(seq):
        if not isinstance(item, Dataset):
            continue
        item_prefix = f"{prefix}[{i}]"
        concept = _concept_meaning(item)
        for elem in item:
            token = _elem_path_token(elem)
            path = f"{item_prefix}.{token}"
            if elem.VR == _SEQ_VR and isinstance(elem.value, DicomSequence):
                yield from _iter_seq_text_leaves(elem.value, prefix=path)
                continue
            if str(elem.VR or "") in TEXT_VRS:
                if elem.keyword and elem.keyword in SKIP_TEXT_KEYWORDS:
                    continue
                text = _as_str(elem.value)
                if text:
                    yield _LeafText(tag_path=path, text=text, concept=concept)


def _iter_seq_date_rows(
    seq: DicomSequence,
    *,
    prefix: str,
    resolve_keep: ResolveKeep | None,
    root_ds: Dataset,
) -> Iterator[MetadataPhiRow]:
    for i, item in enumerate(seq):
        if not isinstance(item, Dataset):
            continue
        item_prefix = f"{prefix}[{i}]"
        for elem in item:
            token = _elem_path_token(elem)
            path = f"{item_prefix}.{token}"
            if elem.VR == _SEQ_VR and isinstance(elem.value, DicomSequence):
                yield from _iter_seq_date_rows(
                    elem.value,
                    prefix=path,
                    resolve_keep=resolve_keep,
                    root_ds=root_ds,
                )
                continue
            if str(elem.VR or "") in DATE_VRS:
                row = _leaf_row(elem, path=path, resolve_keep=resolve_keep, root_ds=root_ds)
                if row is not None:
                    yield row


def _compile_fragments(leaves: Sequence[_LeafText]) -> tuple[str, tuple[SpanFragment, ...]]:
    parts: list[str] = []
    spans: list[SpanFragment] = []
    pos = 0
    for leaf in leaves:
        label = (leaf.concept or "").strip()
        prefix = f"[{label}] " if label else ""
        piece = f"{prefix}{leaf.text}"
        if parts:
            parts.append(_FRAGMENT_SEP)
            pos += len(_FRAGMENT_SEP)
        start = pos + len(prefix)
        end = start + len(leaf.text)
        spans.append(SpanFragment(start=start, end=end, tag_path=leaf.tag_path, leaf_text=leaf.text))
        parts.append(piece)
        pos += len(piece)
    return "".join(parts), tuple(spans)


def _concept_meaning(item: Dataset) -> str:
    seq = getattr(item, "ConceptNameCodeSequence", None)
    if not seq:
        return ""
    for code in seq:
        meaning = _as_str(getattr(code, "CodeMeaning", ""))
        if meaning:
            return meaning
    return ""


def _elem_path_token(elem: DataElement) -> str:
    if elem.keyword:
        return str(elem.keyword)
    return format_dicom_tag(f"{int(elem.tag):08X}")


def element_display_name(ds: Dataset, elem: DataElement) -> str:
    """Public Name column label (TCIA / creator / dictionary); never bare Private."""
    is_private = bool(elem.tag.is_private)
    creator = private_creator_string(ds, elem.tag) if is_private else ""
    tcia = _private_kb_entry(elem.tag, creator) if is_private else None
    return _display_name(
        elem,
        is_private=is_private,
        tcia_name=tcia.display_name if tcia else None,
        creator=creator,
    )


def _display_name(
    elem: DataElement,
    *,
    is_private: bool,
    tcia_name: str | None,
    creator: str,
) -> str:
    tag_label = format_dicom_tag(f"{int(elem.tag):08X}")
    if is_private:
        tcia = str(tcia_name or "").strip()
        if tcia and tcia.casefold() != "private":
            return tcia
        meta = str(elem.name or "").strip()
        if meta and not _is_generic_private_name(meta):
            return f"{creator}: {meta}" if creator else meta
        if creator:
            return f"{creator} {tag_label}"
        return tag_label
    if elem.keyword:
        meta_name = elem.name
        return str(meta_name) if meta_name else str(elem.keyword)
    return str(elem.name) if elem.name else tag_label


def _is_generic_private_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return True
    folded = text.casefold()
    if folded in {"private", "unknown"}:
        return True
    return bool(text.startswith("[") and text.endswith("]"))


def _private_kb_entry(tag: BaseTag, creator: str) -> PrivateTagEntry | None:
    """Knowledge-base row for a private data element, or None."""
    return lookup_private_tag(
        creator=creator,
        group=tag.group,
        element_suffix=tag.element & 0xFF,
    )


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8", errors="replace").strip()
        except Exception:
            return ""
    return str(value).strip()


def _resolve_leaf_parent(ds: Dataset, tag_path: str) -> tuple[Dataset, str]:
    parts = tag_path.split(".")
    if not parts:
        raise ValueError("Empty tag path")
    cur: Dataset | DicomSequence | object = ds
    for segment in parts[:-1]:
        m = _PATH_SEGMENT.match(segment)
        if m is None:
            raise ValueError(f"Bad path segment: {segment}")
        name = m.group("name")
        index = m.group("index")
        cur = _get_named(cur, name)
        if index is not None:
            cur = cur[int(index)]
    last = parts[-1]
    m = _PATH_SEGMENT.match(last)
    if m is None or m.group("index") is not None:
        raise ValueError(f"Path must end on a leaf attribute: {tag_path}")
    if not isinstance(cur, Dataset):
        raise ValueError(f"Parent is not a dataset for {tag_path}")
    return cur, m.group("name")


def _get_named(obj: object, name: str) -> object:
    tag = _tag_from_path_name(name)
    if tag is not None:
        if not isinstance(obj, Dataset):
            raise ValueError(f"Cannot index tag {name} on {type(obj)}")
        return obj[tag].value
    if isinstance(obj, Dataset):
        return getattr(obj, name)
    raise ValueError(f"Cannot get {name} from {type(obj)}")
