"""Inventory Synthetic MIDI-B DICOM instances."""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pydicom

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MidiInstance:
    """One Synthetic (challenge input) instance."""

    path: Path
    patient_id: str
    sop_uid: str
    study_uid: str = ""
    series_uid: str = ""
    modality: str = ""


def list_instances(
    synthetic_root: Path,
    *,
    patient_ids: list[str] | None = None,
    limit: int | None = None,
    read_headers: bool = False,
) -> list[MidiInstance]:
    """Walk ``synthetic_root`` and return instances (optionally filtered).

    By default only paths are collected (patient_id = folder name). Set
    ``read_headers=True`` to populate SOP/study/series/modality from DICOM
    (slow on large cohorts; pipeline reads headers again anyway).
    """
    root = Path(synthetic_root)
    if not root.is_dir():
        raise FileNotFoundError(f"synthetic root not found: {root}")

    allow = {str(p).strip() for p in patient_ids} if patient_ids else None
    out: list[MidiInstance] = []

    patient_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    if allow is not None:
        patient_dirs = [p for p in patient_dirs if p.name in allow]
        missing = allow - {p.name for p in patient_dirs}
        if missing:
            logger.warning("patient ids not found under %s: %s", root, sorted(missing))

    for pdir in patient_dirs:
        for path in sorted(pdir.rglob("*.dcm")):
            if read_headers:
                try:
                    ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
                except Exception as exc:
                    logger.warning("skip unreadable %s: %s", path, exc)
                    continue
                sop = str(getattr(ds, "SOPInstanceUID", "") or "").strip()
                if not sop:
                    logger.warning("skip no SOPInstanceUID: %s", path)
                    continue
                out.append(
                    MidiInstance(
                        path=path,
                        patient_id=str(getattr(ds, "PatientID", "") or pdir.name).strip(),
                        sop_uid=sop,
                        study_uid=str(getattr(ds, "StudyInstanceUID", "") or "").strip(),
                        series_uid=str(getattr(ds, "SeriesInstanceUID", "") or "").strip(),
                        modality=str(getattr(ds, "Modality", "") or "").strip(),
                    )
                )
            else:
                # Placeholder sop_uid filled when the pipeline reads the file.
                out.append(
                    MidiInstance(
                        path=path,
                        patient_id=pdir.name,
                        sop_uid="",
                    )
                )
            if limit is not None and len(out) >= limit:
                return out
    return out


def write_inventory(instances: list[MidiInstance], path: Path) -> dict:
    """Write inventory JSON; return summary dict."""
    by_patient = Counter(i.patient_id for i in instances)
    by_mod = Counter(i.modality or "?" for i in instances)
    summary = {
        "n_instances": len(instances),
        "n_patients": len(by_patient),
        "by_modality": dict(by_mod.most_common()),
        "patients": [
            {"patient_id": pid, "n": n} for pid, n in sorted(by_patient.items())
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **summary,
        "instances": [
            {
                "path": str(i.path),
                "patient_id": i.patient_id,
                "sop_uid": i.sop_uid,
                "study_uid": i.study_uid,
                "series_uid": i.series_uid,
                "modality": i.modality,
            }
            for i in instances
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return summary
