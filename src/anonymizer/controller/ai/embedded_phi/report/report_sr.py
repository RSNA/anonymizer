"""Structured Report (SR) text: ContentSequence walk → ``TextSlot`` list → save."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pydicom import Dataset, dcmread
from pydicom.errors import InvalidDicomError

from anonymizer.controller.ai.embedded_phi.ner.detect_phi import SlotScan
from anonymizer.controller.ai.embedded_phi.report.content_text import TextSlot
from anonymizer.utils.storage import get_dcm_files

logger = logging.getLogger(__name__)

# Value types whose payload is free text; TEXT → TextValue, PNAME → PersonName.
_TEXT_ATTRS = {"TEXT": "TextValue", "PNAME": "PersonName"}


def iter_sr_slots(ds: Dataset, *, key_prefix: str = "") -> Iterator[TextSlot]:
    """Depth-first walk of ``ContentSequence`` yielding a slot per TEXT / PNAME content item."""

    def _walk(container: Dataset, path: tuple[int, ...]) -> Iterator[TextSlot]:
        for idx, item in enumerate(container.get("ContentSequence", []) or []):
            here = (*path, idx)
            attr = _TEXT_ATTRS.get(str(item.get("ValueType", "")).strip().upper())
            if attr and attr in item:
                value = str(item.get(attr, "") or "")

                def _write(new: str, _item: Dataset = item, _attr: str = attr) -> None:
                    setattr(_item, _attr, new)

                concept = ""
                for cn in item.get("ConceptNameCodeSequence", []) or []:
                    concept = str(cn.get("CodeMeaning", "") or "")
                    break
                yield TextSlot(
                    key=f"{key_prefix}{'.'.join(map(str, here))}:{attr}",
                    context=concept,
                    text=value,
                    write=_write,
                )
            yield from _walk(item, here)

    yield from _walk(ds, ())


@dataclass(slots=True)
class SrDocument:
    """All SR instances of a series, loaded for review."""

    series_path: Path
    datasets: dict[Path, Dataset] = field(default_factory=dict)
    slots: list[TextSlot] = field(default_factory=list)
    dirty: set[Path] = field(default_factory=set)
    _slot_paths: dict[str, Path] = field(default_factory=dict)

    def path_for(self, slot: TextSlot) -> Path:
        return self._slot_paths[slot.key]

    def mark_changed(self, scans: list[SlotScan]) -> None:
        for scan in scans:
            if scan.entities:
                self.dirty.add(self.path_for(scan.slot))

    def save(self) -> list[Path]:
        saved: list[Path] = []
        for path in sorted(self.dirty):
            self.datasets[path].save_as(path)
            saved.append(path)
        self.dirty.clear()
        return saved


def is_sr_dataset(ds: Dataset) -> bool:
    return str(ds.get("Modality", "")).upper() == "SR" or "ContentSequence" in ds


def load_sr_document(series_path: Path) -> SrDocument:
    """Read every SR instance in ``series_path`` and collect text slots (key includes the file name)."""
    doc = SrDocument(series_path=Path(series_path))
    for dcm_path in sorted(get_dcm_files(series_path)):
        try:
            ds = dcmread(dcm_path)
        except (InvalidDicomError, OSError):
            logger.warning("report_sr: skipping unreadable %s", dcm_path)
            continue
        if not is_sr_dataset(ds):
            continue
        doc.datasets[dcm_path] = ds
        for slot in iter_sr_slots(ds, key_prefix=f"{dcm_path.name}#"):
            doc.slots.append(slot)
            doc._slot_paths[slot.key] = dcm_path
    return doc
