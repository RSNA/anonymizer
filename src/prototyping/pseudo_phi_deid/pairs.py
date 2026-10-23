"""Pair Evaluation ↔ DeIdentified via UID + PatientID crosswalks only."""

import csv
from dataclasses import dataclass
from pathlib import Path

import pydicom

from prototyping.pseudo_phi_deid.paths import (
    DEFAULT_DEID_DIR,
    DEFAULT_EVAL_DIR,
    DEFAULT_PATID_CROSSWALK,
    DEFAULT_UID_CROSSWALK,
)


@dataclass(frozen=True, slots=True)
class InstancePair:
    eval_path: Path
    gold_path: Path
    eval_patient_id: str
    gold_patient_id: str
    eval_sop_uid: str
    gold_sop_uid: str
    modality: str = ""


def load_patid_crosswalk(path: Path | None = None) -> dict[str, str]:
    cw = path or DEFAULT_PATID_CROSSWALK
    out: dict[str, str] = {}
    with cw.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ev = (row.get("evaluation") or "").strip()
            de = (row.get("de-identified") or "").strip()
            if ev and de:
                out[ev] = de
    return out


def load_uid_crosswalk(path: Path | None = None) -> dict[str, str]:
    cw = path or DEFAULT_UID_CROSSWALK
    out: dict[str, str] = {}
    with cw.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ev = (row.get("evaluation") or "").strip()
            de = (row.get("de-identified") or "").strip()
            if ev and de:
                out[ev] = de
    return out


def index_by_sop(root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in root.rglob("*.dcm"):
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        except Exception:
            continue
        sop = str(getattr(ds, "SOPInstanceUID", "") or "").strip()
        if sop:
            index[sop] = path
    return index


def list_eval_patient_ids(eval_dir: Path | None = None) -> list[str]:
    root = eval_dir or DEFAULT_EVAL_DIR
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))


def pair_all(
    *,
    eval_dir: Path | None = None,
    deid_dir: Path | None = None,
    patient_ids: list[str] | None = None,
) -> tuple[list[InstancePair], list[dict]]:
    """
    Return (pairs, unpaired_records).

    Unpaired records list Evaluation SOPs with no gold path (missing files / crosswalk gaps).
    """
    eval_root = eval_dir or DEFAULT_EVAL_DIR
    deid_root = deid_dir or DEFAULT_DEID_DIR
    pats = load_patid_crosswalk()
    uids = load_uid_crosswalk()
    gold_by_sop = index_by_sop(deid_root)
    ids = patient_ids or list_eval_patient_ids(eval_root)
    pairs: list[InstancePair] = []
    unpaired: list[dict] = []

    for pid in ids:
        patient_dir = eval_root / pid
        if not patient_dir.is_dir():
            unpaired.append({"kind": "missing_patient_dir", "eval_patient_id": pid})
            continue
        gold_pid = pats.get(pid, "")
        for eval_path in sorted(patient_dir.rglob("*.dcm")):
            try:
                ds = pydicom.dcmread(str(eval_path), stop_before_pixels=True, force=True)
            except Exception as exc:
                unpaired.append(
                    {
                        "kind": "unreadable",
                        "eval_patient_id": pid,
                        "path": str(eval_path),
                        "error": str(exc),
                    }
                )
                continue
            eval_sop = str(getattr(ds, "SOPInstanceUID", "") or "").strip()
            modality = str(getattr(ds, "Modality", "") or "")
            if not eval_sop:
                unpaired.append(
                    {
                        "kind": "no_sop",
                        "eval_patient_id": pid,
                        "path": str(eval_path),
                    }
                )
                continue
            gold_sop = uids.get(eval_sop)
            if not gold_sop:
                unpaired.append(
                    {
                        "kind": "no_uid_crosswalk",
                        "eval_patient_id": pid,
                        "eval_sop_uid": eval_sop,
                        "path": str(eval_path),
                    }
                )
                continue
            gold_path = gold_by_sop.get(gold_sop)
            if gold_path is None:
                unpaired.append(
                    {
                        "kind": "gold_file_missing",
                        "eval_patient_id": pid,
                        "eval_sop_uid": eval_sop,
                        "gold_sop_uid": gold_sop,
                        "path": str(eval_path),
                    }
                )
                continue
            pairs.append(
                InstancePair(
                    eval_path=eval_path,
                    gold_path=gold_path,
                    eval_patient_id=pid,
                    gold_patient_id=gold_pid or str(getattr(ds, "PatientID", "")),
                    eval_sop_uid=eval_sop,
                    gold_sop_uid=gold_sop,
                    modality=modality,
                )
            )
    return pairs, unpaired
