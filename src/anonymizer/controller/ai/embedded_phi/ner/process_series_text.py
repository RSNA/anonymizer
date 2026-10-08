"""Text batch: scan / replace hitchhiker tags + SR text across a series; capture PHI-only strings."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from pydicom import dcmread
from pydicom.errors import InvalidDicomError

from anonymizer.controller.ai.embedded_phi.ner.detect_phi import removed_texts, scan_slots
from anonymizer.controller.ai.embedded_phi.ner.dicom_text_attributes import iter_hitchhiker_slots
from anonymizer.controller.ai.embedded_phi.ner.replace import ReplaceMode, apply_scans
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import SyntheticPhiFactory
from anonymizer.controller.ai.embedded_phi.report.report_sr import iter_sr_slots
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.utils.storage import get_dcm_files

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TextBatchResult:
    instances_scanned: int = 0
    instances_changed: int = 0
    removed: list[str] = field(default_factory=list)


def process_series_text(
    series_path: Path,
    *,
    mode: ReplaceMode = "blank",
    anon_model: AnonymizerModel | None = None,
    synth: SyntheticPhiFactory | None = None,
    dry_run: bool = False,
) -> TextBatchResult:
    """
    Scan every instance for hitchhiker + SR free text. Unless ``dry_run``, replace PHI, save the file,
    and (with ``anon_model``) store the removed entity text only.
    """
    result = TextBatchResult()
    for dcm_path in sorted(get_dcm_files(series_path)):
        try:
            ds = dcmread(dcm_path)
        except (InvalidDicomError, OSError):
            continue
        result.instances_scanned += 1
        slots = [*iter_hitchhiker_slots(ds), *iter_sr_slots(ds)]
        scans = [s for s in scan_slots(slots) if s.entities]
        if not scans:
            continue
        texts = removed_texts(scans)
        if dry_run:
            result.removed.extend(t for t in texts if t not in result.removed)
            continue
        apply_scans(scans, mode=mode, synth=synth)
        ds.save_as(dcm_path)
        result.instances_changed += 1
        result.removed.extend(t for t in texts if t not in result.removed)
        if anon_model is not None:
            anon_model.set_instance_embedded_phi(str(ds.SOPInstanceUID), texts)
    return result
