"""TCIA private-tag knowledge base (Retain Safe Private + metadata UX).

Public API
----------
collapse_retain_safe_action(actions: set[PrivateTagAction]) -> PrivateTagAction | None
    Select one action for an XX slot under Retain Safe Private.

lookup_private_tag(*, creator: str='', group: int, element_suffix: int) -> PrivateTagEntry | None
    Look up one private slot in the generated knowledge-base dict.

private_creator_string(ds: Dataset, tag: BaseTag) -> str
    Return the private creator string for tag's block on ds.

private_tag_operation(ds: Dataset, elem: DataElement, *, retain_uids: bool, date_delta: int | None) -> str
    Return the operation for one private element.
"""
import logging

from pydicom.dataelem import DataElement
from pydicom.dataset import Dataset
from pydicom.tag import BaseTag, Tag

from anonymizer.controller.dates import incrementdate_operand
from anonymizer.controller.private_tags.tcia_kb_data import (
    PRIVATE_KB,
    PRIVATE_KB_FALLBACK,
    PrivateTagAction,
    PrivateTagEntry,
)

logger = logging.getLogger(__name__)

_DATE_VRS = frozenset({"DA", "DT", "TM"})
_INT_DATE_VRS = frozenset({"SL", "UL", "IS"})
_ANONYMIZER_PRIVATE_GROUP = 0x0013

# Prefer transform, then keep, then remove. Used when collapsing XX slots at
# knowledge-base build time.
_ACTION_PRIORITY: tuple[PrivateTagAction, ...] = (
    PrivateTagAction.DATE_DELTA,
    PrivateTagAction.UID,
    PrivateTagAction.KEEP,
    PrivateTagAction.REMOVE,
)


def collapse_retain_safe_action(actions: set[PrivateTagAction]) -> PrivateTagAction | None:
    """
    Select one action for an XX slot under Retain Safe Private.

    Returns the earliest member of _ACTION_PRIORITY present in
    actions, or None when actions is empty.

    Args:
        actions: Distinct actions for one group/suffix slot.

    Returns:
        The selected action, or None.
    """
    if not actions:
        return None
    for action in _ACTION_PRIORITY:
        if action in actions:
            return action
    return PrivateTagAction.KEEP


def lookup_private_tag(
    *,
    creator: str = "",
    group: int,
    element_suffix: int,
) -> PrivateTagEntry | None:
    """
    Look up one private slot in the generated knowledge-base dict.

    Args:
        creator: Private creator string from the dataset (case-insensitive).
        group: Private group number (odd).
        element_suffix: Low byte of the element number (EE of GGGGXXEE).

    Returns:
        The stored entry, or None when the slot is unknown. With a creator,
        only a creator-exact row matches; without one, the creator-less
        fallback applies.
    """
    creator_cf = (creator or "").strip().casefold()
    if creator_cf:
        return PRIVATE_KB.get((creator_cf, group, element_suffix))
    return PRIVATE_KB_FALLBACK.get((group, element_suffix))


def private_creator_string(ds: Dataset, tag: BaseTag) -> str:
    """
    Return the private creator string for tag's block on ds.

    Args:
        ds: Dataset containing the creator element.
        tag: Private data element tag whose block is identified.

    Returns:
        Creator LO text, or "" when the tag is not private, the block
        number is zero, or the creator element is absent or empty.
    """
    if not tag.is_private:
        return ""
    creator_element = tag.element >> 8
    if creator_element == 0:
        return ""
    creator_tag = Tag(tag.group, creator_element)
    if creator_tag not in ds:
        return ""
    value = ds[creator_tag].value
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def private_tag_operation(
    ds: Dataset,
    elem: DataElement,
    *,
    retain_uids: bool,
    date_delta: int | None,
) -> str:
    """
    Return the operation for one private element.

    Resolution order (KB_OPERATION):

    1. tag.group == 0x0013 returns "@keep". Group 0x0013 holds the
       private block this application writes into anonymized files.
    2. tag.is_private_creator returns "@keep". The creator string
       is the lookup key for every other element in the block.
    3. entry = kb[(creator, group, suffix)].
    4. No entry: log tag, creator, VR; return "@remove()".
    5. entry.action:
       - KEEP → "@keep"
       - REMOVE → "@remove()"
       - UID → "@keep" when retain_uids is true; else "@uid"
         when the element is a UID element (VR UI or note contains
         "UID"), else "@remove()"
       - DATE_DELTA → date operand when the element is a date element
         and date_delta is not None, else "@remove()". A date
         element is VR DA, DT, or TM, or VR SL, UL, or IS with a note
         containing "DATE", "TIME", or "DATETIME".

    Args:
        ds: Dataset containing elem; used for the creator string lookup.
        elem: The private element to resolve.
        retain_uids: True when Retain UIDs is selected on the project.
        date_delta: Resolved day delta for this file, or None.

    Returns:
        "@keep", "@remove()", "@uid", or
        "@incrementdate(this,N)".
    """
    tag = elem.tag

    if tag.group == _ANONYMIZER_PRIVATE_GROUP:
        return "@keep"
    if tag.is_private_creator:
        return "@keep"

    creator = private_creator_string(ds, tag)
    entry = lookup_private_tag(
        creator=creator,
        group=tag.group,
        element_suffix=tag.element & 0xFF,
    )
    vr = str(elem.VR or "").upper()
    if entry is None:
        logger.info(
            f"SAFE_PRIVATE unknown private tag removed: {_tag_hex(tag)} "
            f"creator={creator!r} VR={vr}"
        )
        return "@remove()"

    note_u = entry.note.upper()
    if entry.action is PrivateTagAction.KEEP:
        return "@keep"
    if entry.action is PrivateTagAction.REMOVE:
        return "@remove()"
    if entry.action is PrivateTagAction.UID:
        if retain_uids:
            return "@keep"
        if vr == "UI" or "UID" in note_u:
            return "@uid"
        return "@remove()"
    if entry.action is PrivateTagAction.DATE_DELTA:
        if date_delta is None:
            return "@remove()"
        if vr in _DATE_VRS:
            return incrementdate_operand(date_delta)
        if vr in _INT_DATE_VRS and any(
            word in note_u for word in ("DATE", "TIME", "DATETIME")
        ):
            return incrementdate_operand(date_delta)
        return "@remove()"
    return "@remove()"


def _tag_hex(tag: BaseTag) -> str:
    """Eight-hex uppercase tag string."""
    return f"{tag.group:04X}{tag.element:04X}"


