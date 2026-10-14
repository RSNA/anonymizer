"""TCIA private-tag knowledge base (display names + dispositions)."""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from anonymizer.utils.package_paths import ASSETS_DIR

logger = logging.getLogger(__name__)

_POLICY = ASSETS_DIR / "anonymization_policy"
_CSV = _POLICY / "tcia_private_tag_kb.csv"
_XX_TAG = re.compile(r"^([0-9A-Fa-f]{4})XX([0-9A-Fa-f]{2})$", re.IGNORECASE)

# Retain Safe Private (DICOM 113111): when the same private slot has multiple
# dispositions (typed VR = keep, UN = delete; or creators disagree on XX),
# prefer transform/keep over delete. Lower number wins.
# Used by convert_tcia_private_kb flatten and XX collapse.
ACTION_PRIORITY = {"o": 0, "oi": 0, "h": 1, "k": 2, "d": 3}


def collapse_retain_safe_action(actions: set[str]) -> str | None:
    """Choose one disposition for an XX slot under Retain Safe Private.

    Prefer offset/hash, then keep over delete. Emit ``d`` only when every
    disposition is ``d``.
    """
    cleaned = {a.lower() for a in actions if a}
    if not cleaned:
        return None
    if "o" in cleaned or "oi" in cleaned:
        return "o" if "o" in cleaned else "oi"
    if "h" in cleaned:
        return "h"
    if "k" in cleaned:
        return "k"
    if cleaned <= {"d"}:
        return "d"
    return "k"


def action_beats(candidate: str, incumbent: str) -> bool:
    """True when ``candidate`` should replace ``incumbent`` under ACTION_PRIORITY."""
    a = (candidate or "").strip().lower()
    b = (incumbent or "").strip().lower()
    if a not in ACTION_PRIORITY:
        return False
    if b not in ACTION_PRIORITY:
        return True
    return ACTION_PRIORITY[a] < ACTION_PRIORITY[b]


@dataclass(frozen=True)
class TciaPrivateEntry:
    """One row from ``tcia_private_tag_kb.csv``."""

    group_element: str
    creator: str
    action: str
    note: str
    vr: str = ""

    @property
    def display_name(self) -> str:
        """Same label style as Clinical script ``n=`` (``creator: note``). Never bare ``Private``."""
        if self.creator and self.note:
            return f"{self.creator}: {self.note}"
        if self.creator:
            return self.creator
        if self.note:
            return self.note
        return self.group_element


@lru_cache(maxsize=4)
def load_tcia_private_kb(csv_path: str | None = None) -> tuple[TciaPrivateEntry, ...]:
    """Load TCIA private KB rows (cached)."""
    path = Path(csv_path) if csv_path else _CSV
    if not path.is_file():
        logger.debug("TCIA private KB missing: %s", path)
        return ()
    rows: list[TciaPrivateEntry] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for raw in csv.DictReader(fh):
            ge = (raw.get("group_element") or "").strip().upper().replace(",", "")
            if not ge:
                continue
            rows.append(
                TciaPrivateEntry(
                    group_element=ge,
                    creator=(raw.get("creator") or "").strip(),
                    action=(raw.get("action") or "").strip(),
                    note=(raw.get("note") or "").strip(),
                    vr=(raw.get("vr") or "").strip().upper(),
                )
            )
    return tuple(rows)


def _tag_pattern_matches(pat: str, key: str) -> bool:
    pat_u = pat.upper().replace(",", "")
    if "XX" in pat_u:
        m = _XX_TAG.match(pat_u)
        if m is None:
            return False
        return key[:4] == m.group(1).upper() and key[6:] == m.group(2).upper()
    return pat_u == key


def match_tcia_private(
    tag_hex: str,
    *,
    creator: str = "",
    kb_path: str | None = None,
    entries: tuple[TciaPrivateEntry, ...] | None = None,
) -> TciaPrivateEntry | None:
    """Return the KB entry matching ``tag_hex`` (8 hex) and optional creator.

    When ``creator`` is set, only creator-exact rows match (Clinical Retain Safe).
    When empty, prefer a creator-less row, else the first pattern match.
    ``entries`` (if given) overrides packaged/``kb_path`` loading.
    """
    key = str(tag_hex or "").upper().replace(",", "").replace(" ", "")
    if len(key) != 8:
        return None
    rows = entries if entries is not None else load_tcia_private_kb(kb_path)
    creator_cf = creator.strip().casefold()
    pattern_hits: list[TciaPrivateEntry] = []
    for entry in rows:
        if not _tag_pattern_matches(entry.group_element, key):
            continue
        if creator_cf:
            if entry.creator and entry.creator.casefold() == creator_cf:
                return entry
            continue
        pattern_hits.append(entry)
    if creator_cf:
        return None
    for entry in pattern_hits:
        if not entry.creator:
            return entry
    return pattern_hits[0] if pattern_hits else None


def private_creator_string(ds: object, tag: object) -> str:
    """Return private creator string for ``tag``'s block on ``ds``, if present."""
    try:
        from pydicom.tag import Tag as PydicomTag
    except ImportError:
        return ""
    try:
        if not getattr(tag, "is_private", False):
            return ""
        creator_element = int(tag.element) >> 8
        if creator_element == 0:
            return ""
        creator_tag = PydicomTag(int(tag.group), creator_element)
        if creator_tag not in ds:
            return ""
        value = ds[creator_tag].value
        if value is None:
            return ""
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="replace").strip()
        return str(value).strip()
    except Exception:
        return ""
