"""Extract free-text and date PHI carriers from DICOM metadata (SOP-agnostic).

Omits Private Creator elements (tag.is_private_creator). Integer String (IS)
and Decimal String (DS) are included in Clean Descriptors NER input so
embedded dates and PHI in those values can be detected.

Public API
----------
TEXT_VRS
    Free-text descriptor VRs (LO, LT, ST, SH, UT, UC, UR, PN).

NUMERIC_STRING_VRS
    Integer / decimal string VRs (IS, DS) included in NER input.

NER_INPUT_VRS
    TEXT_VRS | NUMERIC_STRING_VRS — cells eligible for Clean Descriptors NER.

DATE_VRS
    Date VRs (DA, DT) — assessment only; not Clean Descriptors NER.

INTEGER_AND_CODE_STRING_VRS
    IS, DS, CS — metadata extract carriers (CS digit-only; IS/DS full text).

DIGITS_ONLY_VRS
    CS only — Content reduced with digits_only.

DICOM_VR_CODES
    Two-letter DICOM Value Representation codes (PS3.5); always allowed
    in Clean Descriptors post-NER whitelist drop (e.g. Rescale Type "US").

digits_only(text: str) -> str
    Digit characters only; used for CS extract Content.

is_pure_numeric_string_value(value: object) -> bool
    True when value is only float/int-parsable numeric component(s).
    One shared gate for IS and DS (integer and float formats).

is_pure_decimal_string_value(value: object) -> bool
    Alias of is_pure_numeric_string_value (DS/IS share one gate).

omit_pure_numeric_from_descriptor_ner(vr: str, value: object) -> bool
    True when value is pure numeric IS/DS (logging / callers); NER still
    includes IS/DS so embedded PHI in impure values is not the only path.

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
import logging
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from pydicom import config as pydicom_config
from pydicom.dataelem import DataElement
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.tag import BaseTag, Tag
from pydicom.valuerep import VR

from anonymizer.controller.dates import is_date_delta_operation
from anonymizer.controller.private_tags import (
    PrivateTagEntry,
    lookup_private_tag,
    private_creator_string,
)
from anonymizer.utils.dicom_dictionary import display_tag_vr, format_dicom_tag

logger = logging.getLogger(__name__)

TEXT_VRS = frozenset({"LO", "LT", "ST", "SH", "UT", "UC", "UR", "PN"})
NUMERIC_STRING_VRS = frozenset({"IS", "DS"})
NER_INPUT_VRS = TEXT_VRS | NUMERIC_STRING_VRS
DATE_VRS = frozenset({"DA", "DT"})
INTEGER_AND_CODE_STRING_VRS = frozenset({"IS", "DS", "CS"})
# CS code strings stay digit-only for assessment; IS/DS keep full text for NER.
DIGITS_ONLY_VRS = frozenset({"CS"})
# PS3.5 two-letter VR codes (pydicom SSOT). Post-NER allow: untag spans that
# are only a VR code (e.g. Rescale Type value "US") so OpenMed false hits drop.
DICOM_VR_CODES = frozenset(
    name for name in (member.name for member in VR) if len(name) == 2 and name.isalpha()
)

# Legal characters in one IS/DS numeric component (DICOM + whitespace).
_NUMERIC_COMPONENT_CHARS = frozenset("0123456789+-eE. \t")


def digits_only(text: str) -> str:
    """Keep digit characters only.

    Used for CS extract Content. IS/DS keep original text for NER.

    Args:
        text: Raw cell or tag string.

    Returns:
        Concatenation of characters where str.isdigit is true.
    """
    return "".join(filter(str.isdigit, str(text or "")))


def is_pure_numeric_string_value(value: object) -> bool:
    """
    True when value is only legal numeric component(s) (int or float tokens).

    Shared gate for IS and DS. Any letter outside e/E, other junk, or a
    non-numeric component fails so hidden text still reaches NER.

    Args:
        value: Raw pydicom element value, sequence of components, or text.

    Returns:
        True when every component parses with float and uses only numeric chars.
    """
    components = _numeric_components(value)
    if not components:
        return False
    return all(_is_pure_numeric_component(part) for part in components)


def is_pure_decimal_string_value(value: object) -> bool:
    """Alias of is_pure_numeric_string_value (one gate for IS and DS)."""
    return is_pure_numeric_string_value(value)


def omit_pure_numeric_from_descriptor_ner(vr: str, value: object) -> bool:
    """
    True when an IS/DS value is pure numeric (no embedded letters/junk).

    Kept for logging and callers that distinguish pure geometry/counts from
    impure strings. Clean Descriptors NER input includes all IS/DS via
    NER_INPUT_VRS; embedded dates/PHI in impure values are detected there.

    Args:
        vr: DICOM VR.
        value: Raw element value or text.

    Returns:
        True when VR is IS/DS and value is only float/int-parsable component(s).
    """
    code = str(vr or "").upper()
    if code not in NUMERIC_STRING_VRS:
        return False
    return is_pure_numeric_string_value(value)


def _numeric_components(value: object) -> list[str] | None:
    """Split an IS/DS value into stripped component strings."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        text = _as_str(value)
        return [text] if text else None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts = [str(item).strip() for item in value]
        parts = [part for part in parts if part]
        return parts or None
    text = _as_str(value)
    if not text:
        return None
    # str(MultiValue) / list repr from callers that only have text.
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return None
        return [part.strip() for part in inner.split(",") if part.strip()]
    # DICOM multi-value separator.
    if "\\" in text:
        parts = [part.strip() for part in text.split("\\") if part.strip()]
        return parts or None
    return [text]


def _is_pure_numeric_component(text: str) -> bool:
    """True when one IS/DS component is float-safe with no non-numeric junk."""
    s = str(text or "").strip()
    if not s:
        return False
    if any(ch not in _NUMERIC_COMPONENT_CHARS for ch in s):
        return False
    if any(ch.isalpha() and ch not in "eE" for ch in s):
        return False
    try:
        float(s)
    except ValueError:
        return False
    return True


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
    """Set the leaf string at tag_path (e.g. ContentSequence[0].TextValue).

    IS/DS use raw `_value` assignment so blanked Content that is no longer a
    legal numeric string can still be written after Clean Descriptors.
    """
    parent, name = _resolve_leaf_parent(ds, tag_path)
    tag = _tag_from_path_name(name)
    if tag is not None:
        _set_element_text(parent[tag], new_text)
        return
    if name in parent:
        _set_element_text(parent[name], new_text)
        return
    setattr(parent, name, new_text)


def _set_element_text(elem: DataElement, new_text: str) -> None:
    """Write string Content onto a DataElement (raw for IS/DS)."""
    vr = str(elem.VR or "").upper()
    if vr in NUMERIC_STRING_VRS:
        elem._value = new_text
        return
    previous = pydicom_config.settings.writing_validation_mode
    pydicom_config.settings.writing_validation_mode = pydicom_config.IGNORE
    try:
        elem.value = new_text
    except (ValueError, TypeError, OverflowError):
        elem._value = new_text
    finally:
        pydicom_config.settings.writing_validation_mode = previous



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
    if (
        vr not in TEXT_VRS
        and vr not in DATE_VRS
        and vr not in INTEGER_AND_CODE_STRING_VRS
    ):
        return None
    # Private Creator strings name the private block (vendor/registry IDs).
    # Omit from Clean Descriptors / Metadata NER so vendor tokens (e.g. MITRA)
    # are not blanked as false FIRST_NAME; real PHI stays in private data
    # elements, which are still extracted.
    if bool(getattr(elem.tag, "is_private_creator", False)):
        return None
    text = _as_str(elem.value)
    # CS: digit Content only. IS/DS keep original text for NER (embedded PHI).
    if vr in DIGITS_ONLY_VRS:
        text = digits_only(text)
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
