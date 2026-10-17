"""SOP Class → IOD allow-list for unexpected public text/date tags."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from functools import lru_cache
from typing import TYPE_CHECKING

from anonymizer.controller.ai.embedded_phi.metadata.extract import MetadataPhiRow
from anonymizer.utils.package_paths import ASSETS_DIR

if TYPE_CHECKING:
    from dicom_validator.validator.dicom_info import DicomInfo
from dicom_validator.spec_reader.edition_reader import EditionReader

logger = logging.getLogger(__name__)

# Bundled under assets/dicom_standard/<edition>/json/ — see SOURCE.md there.
BUNDLED_DICOM_EDITION = "2025e"
_DICOM_STANDARD_ASSETS = ASSETS_DIR / "dicom_standard"

_TAG_KEY = re.compile(
    r"^\(?(?P<g>[0-9A-Fa-f]{4}),?(?P<e>[0-9A-Fa-f]{4})\)?$"
)
_SKIP_ATTR_KEYS = frozenset({"modules", "items", "group_macros", "cond", "type", "name"})


def normalize_iod_tag_key(key: str) -> str | None:
    """Normalize dicom-validator tag keys ``(GGGG,EEEE)`` / ``GGGGEEEE`` → 8 hex."""
    text = str(key or "").strip().upper().replace(" ", "")
    m = _TAG_KEY.match(text)
    if m is None:
        return None
    return f"{m.group('g')}{m.group('e')}"


@lru_cache(maxsize=2)
def load_dicom_info(edition: str | None = None) -> DicomInfo:
    """
    Load DICOM standard JSON via dicom-validator ``EditionReader``.

    Default ``edition`` is the bundled tree under
    ``assets/dicom_standard/`` (``BUNDLED_DICOM_EDITION``, ~2.4 MiB JSON).
    Pass another edition id only when that edition's ``json/`` exists under
    the same assets root (or set ``path`` via tests).
    """

    ed = (edition or BUNDLED_DICOM_EDITION).strip() or BUNDLED_DICOM_EDITION
    reader = EditionReader(path=_DICOM_STANDARD_ASSETS)
    json_dir = reader.json_path(ed)
    if not (json_dir / "iod_info.json").is_file():
        raise FileNotFoundError(
            f"Bundled DICOM edition JSON missing at {json_dir} "
            f"(see assets/dicom_standard/SOURCE.md)"
        )
    info = reader.load_dicom_info(ed)
    logger.info("Loaded dicom-validator DicomInfo for edition %s from %s", ed, json_dir)
    return info


def allowed_tags_for_sop_class(
    dicom_info: DicomInfo,
    sop_class_uid: str,
) -> frozenset[str] | None:
    """
    Return the set of public tags allowed by the IOD for ``sop_class_uid``.

    Returns ``None`` when the SOP Class is unknown (caller should not flag).
    """
    uid = str(sop_class_uid or "").strip()
    if not uid or uid not in dicom_info.iods:
        return None
    iod = dicom_info.iods[uid]
    modules = iod.get("modules") or {}
    tags: set[str] = set()
    for module in modules.values():
        if not isinstance(module, dict):
            continue
        ref = module.get("ref")
        if not ref:
            continue
        mod_attrs = dicom_info.modules.get(ref)
        if isinstance(mod_attrs, dict):
            _collect_module_tags(mod_attrs, tags)
    return frozenset(tags)


def mark_iod_unexpected(
    rows: list[MetadataPhiRow],
    sop_class_uid: str,
    *,
    dicom_info: DicomInfo | None = None,
    edition: str | None = None,
) -> list[MetadataPhiRow]:
    """
    Set ``iod_unexpected`` on public text / ``SEQ(text)`` / DA/DT rows whose tag
    is absent from the SOP Class IOD allow-list. Private rows are never flagged.
    """
    info = dicom_info if dicom_info is not None else load_dicom_info(edition)
    allowed = allowed_tags_for_sop_class(info, sop_class_uid)
    if allowed is None:
        return [replace(r, iod_unexpected=False) for r in rows]

    out: list[MetadataPhiRow] = []
    for row in rows:
        if row.is_private:
            out.append(replace(row, iod_unexpected=False))
            continue
        unexpected = row.tag_hex not in allowed
        out.append(replace(row, iod_unexpected=unexpected))
    return out


def _collect_module_tags(attrs: dict, out: set[str]) -> None:
    """Recursively collect attribute tag keys from a module description dict."""
    for key, value in attrs.items():
        if key in _SKIP_ATTR_KEYS:
            if key == "items" and isinstance(value, dict):
                # Sequence item attrs: either nested under items/items or flat items.
                nested = value.get("items") if "items" in value and isinstance(value.get("items"), dict) else value
                if isinstance(nested, dict):
                    _collect_module_tags(nested, out)
            elif key == "modules" and isinstance(value, dict):
                for mod in value.values():
                    if isinstance(mod, dict) and "ref" in mod:
                        # Functional-group module refs are resolved by the validator;
                        # ignore here (tags appear under sequence items).
                        continue
            continue
        tag_hex = normalize_iod_tag_key(key)
        if tag_hex is not None:
            out.add(tag_hex)
        if isinstance(value, dict) and "items" in value:
            items = value["items"]
            if isinstance(items, dict):
                nested = items.get("items", items) if "group_macros" in items else items
                if isinstance(nested, dict):
                    _collect_module_tags(nested, out)
