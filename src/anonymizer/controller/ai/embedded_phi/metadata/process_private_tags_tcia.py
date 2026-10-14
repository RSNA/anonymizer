"""TCIA Private Tag KB: disposition helpers + creator-aware Dataset apply.

Public API
----------
``process_private_tags_tcia(ds, *, kb_path=None, dateinc=None, uid_map=None)``
    Apply TCIA Private KB dispositions to private elements in ``ds`` (in place).
    Returns the same ``Dataset``. Public tags and PixelData are untouched.

``clinical_dateinc_days(path=None)``
    Trial-wide DATEINC days from ``clinical_dateinc.txt``.

``incrementdate_operand(days=None)``
    CTP ``@incrementdate(this,N)`` string.

``tcia_disposition_to_operand(action, *, vr="", note="", dateinc=None)``
    Map KB disposition to a CTP script operand (Embedded PHI apply).

``collapse_retain_safe_action(actions)``
    XX-slot collapse for Clinical script compile (k beats d).

Clinical ingest leaves privates untouched; this module is Embedded PHI step 2.
"""

from __future__ import annotations

import datetime as _dt
import logging
from collections.abc import MutableMapping
from functools import lru_cache
from pathlib import Path

from pydicom.dataset import Dataset
from pydicom.tag import BaseTag
from pydicom.uid import generate_uid

from anonymizer.controller.ai.embedded_phi.metadata.tcia_kb import (
    load_tcia_private_kb,
    match_tcia_private,
    private_creator_string,
)
from anonymizer.utils.package_paths import ASSETS_DIR

logger = logging.getLogger(__name__)

_DATE_VRS = frozenset({"DA", "DT", "TM"})
_DATEINC_PATH = ASSETS_DIR / "anonymization_policy" / "clinical_dateinc.txt"
_ANONYMIZER_PRIVATE_GROUP = 0x0013

# ---------------------------------------------------------------------------
# Disposition helpers (formerly controller.tcia_disposition)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def clinical_dateinc_days(path: str | None = None) -> int:
    """Load trial-wide DATEINC days from ``clinical_dateinc.txt`` (TCIA @DATEINC)."""
    p = Path(path) if path else _DATEINC_PATH
    if not p.is_file():
        raise FileNotFoundError(f"Clinical DATEINC file missing: {p}")
    for line in p.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        return int(text)
    raise ValueError(f"No DATEINC integer in {p}")


def incrementdate_operand(days: int | None = None) -> str:
    """CTP ``@incrementdate(this,N)`` using Clinical DATEINC when ``days`` is omitted."""
    n = clinical_dateinc_days() if days is None else int(days)
    return f"@incrementdate(this,{n})"


def tcia_disposition_to_operand(
    action: str,
    *,
    vr: str = "",
    note: str = "",
    dateinc: int | None = None,
) -> str | None:
    """Map TCIA ``private_disposition`` to a CTP script operand string.

    Returns ``""`` for keep, ``None`` for unknown/skipped dispositions.
    ``o``/``oi`` → ``@incrementdate(this,DATEINC)`` only for date VRs (or Date/Time notes).
    ``h`` → ``@uid`` only for UI / UID-named tags; otherwise ``@remove()``.
    """
    a = (action or "").strip().lower()
    vr_u = (vr or "").strip().upper()
    note_u = (note or "").upper()
    if a == "k":
        return ""
    if a == "d":
        return "@remove()"
    if a == "h":
        if vr_u == "UI" or "UID" in note_u:
            return "@uid"
        return "@remove()"
    if a in ("o", "oi"):
        if vr_u in _DATE_VRS or any(tok in note_u for tok in ("DATE", "TIME", "DATETIME")):
            return incrementdate_operand(dateinc)
        return "@remove()"
    return None


# ---------------------------------------------------------------------------
# Dataset apply
# ---------------------------------------------------------------------------


def _tag_hex(tag: BaseTag) -> str:
    return f"{int(tag.group):04X}{int(tag.element):04X}"


def _is_private_creator(tag: BaseTag) -> bool:
    if not getattr(tag, "is_private", False):
        return False
    if hasattr(tag, "is_private_creator"):
        return bool(tag.is_private_creator)
    # Odd group, element 0x0010–0x00FF are creator IDs.
    return 0x0010 <= int(tag.element) <= 0x00FF


def _shift_dicom_date(value: object, days: int) -> str:
    """Shift DA/DT/TM-like string by ``days``, preserving time suffix."""
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    text = str(value or "").strip()
    if not text:
        return text
    try:
        if len(text) >= 14 and text[:14].isdigit():
            dt = _dt.datetime.strptime(text[:14], "%Y%m%d%H%M%S")
            return (dt + _dt.timedelta(days=days)).strftime("%Y%m%d%H%M%S") + text[14:]
        if len(text) >= 8 and text[:8].isdigit():
            d = _dt.datetime.strptime(text[:8], "%Y%m%d")
            return (d + _dt.timedelta(days=days)).strftime("%Y%m%d") + text[8:]
        # TM alone — leave unchanged (day offset not meaningful without date).
        return text
    except ValueError:
        return text


def _remap_uid(value: object, uid_map: MutableMapping[str, str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    if raw not in uid_map:
        uid_map[raw] = generate_uid()
    return uid_map[raw]


def process_private_tags_tcia(
    ds: Dataset,
    *,
    kb_path: str | Path | None = None,
    dateinc: int | None = None,
    uid_map: MutableMapping[str, str] | None = None,
) -> Dataset:
    """Apply TCIA Private KB dispositions to private elements in ``ds`` (in place).

    Args:
        ds: DICOM dataset to mutate. PixelData and public tags are not modified.
        kb_path: Optional path to ``tcia_private_tag_kb.csv``; default packaged KB.
        dateinc: Day offset for ``o``/``oi`` on date VRs; default ``clinical_dateinc_days()``.
        uid_map: Optional PHI→anon UID remapping for ``h`` dispositions. When omitted,
            a local dict is used so repeats inside this Dataset stay stable.

    Returns:
        The same ``ds`` object after private-tag processing.

    Side effects:
        Deletes or rewrites private data elements per KB. Private creator IDs
        (``gggg,00xx``) are always retained. Anonymizer private group ``0x0013`` is
        skipped. Unknown / blank / ``na`` / no KB hit → remove.
    """
    sop = str(getattr(ds, "SOPInstanceUID", "") or "")[:32] or "?"
    path_str = str(kb_path) if kb_path else None
    days = clinical_dateinc_days() if dateinc is None else int(dateinc)
    local_uid: MutableMapping[str, str] = uid_map if uid_map is not None else {}
    entries = load_tcia_private_kb(path_str)

    counts = {
        "kept": 0,
        "removed": 0,
        "uid": 0,
        "dateinc": 0,
        "unknown_removed": 0,
        "skipped_0013": 0,
    }
    logger.debug(
        "step2.private_kb: start sop=%s kb=%s dateinc=%d entries=%d",
        sop,
        path_str or "packaged",
        days,
        len(entries),
    )

    def walk(current: Dataset) -> None:
        to_delete: list[BaseTag] = []
        for elem in list(current):
            tag = elem.tag
            if not getattr(tag, "is_private", False):
                if str(getattr(elem, "VR", "") or "").upper() == "SQ" and elem.value:
                    for item in elem.value:
                        if isinstance(item, Dataset):
                            walk(item)
                continue
            if int(tag.group) == _ANONYMIZER_PRIVATE_GROUP:
                counts["skipped_0013"] += 1
                continue
            if _is_private_creator(tag):
                continue
            if str(getattr(elem, "VR", "") or "").upper() == "SQ" and elem.value:
                for item in elem.value:
                    if isinstance(item, Dataset):
                        walk(item)
                # Fall through: disposition may still remove the SQ element itself.

            creator = private_creator_string(current, tag)
            hex8 = _tag_hex(tag)
            hit = match_tcia_private(
                hex8, creator=creator, entries=entries
            )
            action = (hit.action if hit else "").strip().lower()
            vr = str(getattr(elem, "VR", "") or "").upper()
            note = hit.note if hit else ""

            if action == "k":
                counts["kept"] += 1
                continue

            if action == "h":
                if vr == "UI" or "UID" in (note or "").upper():
                    elem.value = _remap_uid(elem.value, local_uid)
                    counts["uid"] += 1
                    continue
                to_delete.append(tag)
                counts["removed"] += 1
                continue

            if action in ("o", "oi"):
                if vr in _DATE_VRS:
                    elem.value = _shift_dicom_date(elem.value, days)
                    counts["dateinc"] += 1
                    continue
                # Numeric "date" privates (e.g. SL YYYYMMDD) — shift as int, keep VR.
                if vr in {"SL", "UL", "IS"} and any(
                    tok in (note or "").upper() for tok in ("DATE", "TIME", "DATETIME")
                ):
                    try:
                        as_int = int(str(elem.value).strip())
                        shifted = _shift_dicom_date(f"{as_int:08d}", days)
                        elem.value = int(shifted[:8])
                        counts["dateinc"] += 1
                        continue
                    except (TypeError, ValueError):
                        pass
                to_delete.append(tag)
                counts["removed"] += 1
                continue

            if action == "d":
                to_delete.append(tag)
                counts["removed"] += 1
                continue

            # Unknown / blank / na / no hit → remove
            to_delete.append(tag)
            counts["unknown_removed"] += 1

        for tag in to_delete:
            if tag in current:
                del current[tag]
        # Private creator IDs (gggg,00xx) are always retained (TCIA / PseudoPHI gold).

    walk(ds)
    logger.info(
        "step2.private_kb: sop=%s kept=%d removed=%d uid=%d dateinc=%d "
        "unknown_removed=%d skipped_0013=%d",
        sop,
        counts["kept"],
        counts["removed"],
        counts["uid"],
        counts["dateinc"],
        counts["unknown_removed"],
        counts["skipped_0013"],
    )
    return ds

