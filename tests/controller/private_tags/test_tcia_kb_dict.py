"""Generated KB dict lookup coverage."""

from __future__ import annotations

from anonymizer.controller.private_tags import PrivateTagAction, lookup_private_tag
from anonymizer.controller.private_tags.tcia_kb_data import PRIVATE_KB, PRIVATE_KB_FALLBACK


def test_every_kb_row_matches_lookup() -> None:
    """Each PRIVATE_KB entry is returned by ``lookup_private_tag``."""
    assert len(PRIVATE_KB) > 4000
    for (creator_cf, group, suffix), row in PRIVATE_KB.items():
        hit = lookup_private_tag(
            creator=row.creator, group=group, element_suffix=suffix
        )
        assert hit is not None, row
        assert hit.action is row.action, row
        assert hit.note == row.note, row
        assert creator_cf == (row.creator or "").strip().casefold()


def test_creatorless_fallback_matches_fallback_dict() -> None:
    """Creator-less lookup uses ``PRIVATE_KB_FALLBACK``."""
    assert PRIVATE_KB_FALLBACK
    for (group, suffix), row in list(PRIVATE_KB_FALLBACK.items())[:50]:
        via = lookup_private_tag(group=group, element_suffix=suffix)
        assert via is not None
        assert via.action is row.action
        assert via.note == row.note


def test_unknown_creator_and_slot_miss() -> None:
    """Unknown creator for a known slot, and unknown slots, return None."""
    assert (
        lookup_private_tag(creator="NOPE", group=0x0009, element_suffix=0x0F) is None
    )
    assert lookup_private_tag(creator="ACME", group=0x0011, element_suffix=0x01) is None


def test_same_xx_slot_creator_specific() -> None:
    """Same XX slot: creator A keep vs B remove — lookup is creator-specific."""
    keep = remove = None
    for (_c, group, suffix), entry in PRIVATE_KB.items():
        if group != 0x0009 or suffix != 0x01:
            continue
        if entry.action is PrivateTagAction.KEEP and keep is None:
            keep = entry
        if entry.action is PrivateTagAction.REMOVE and remove is None:
            remove = entry
    assert keep is not None and remove is not None
    hit_k = lookup_private_tag(creator=keep.creator, group=0x0009, element_suffix=0x01)
    hit_d = lookup_private_tag(creator=remove.creator, group=0x0009, element_suffix=0x01)
    assert hit_k is not None and hit_k.action is PrivateTagAction.KEEP
    assert hit_d is not None and hit_d.action is PrivateTagAction.REMOVE
    assert lookup_private_tag(creator="NoSuchCreator_XYZ", group=0x0009, element_suffix=0x01) is None
