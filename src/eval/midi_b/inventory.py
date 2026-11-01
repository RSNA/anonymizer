"""Stage patient-folder subsets of a MIDI-B synthetic root for smoke runs."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path


def stage_import_subset(
    source_root: Path,
    dest_root: Path,
    *,
    patient_ids: Sequence[str],
) -> Path:
    """
    Copy selected patient folders into dest_root for --import-dir.

    Args:
        source_root: Full synthetic tree.
        dest_root: Empty directory to fill.
        patient_ids: Patient folder names to include (required).

    Returns:
        dest_root after copy.

    Raises:
        ValueError: When patient_ids is empty.
    """
    if not patient_ids:
        raise ValueError("stage_import_subset requires patient_ids")

    source_root = Path(source_root)
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    copied = 0

    for pid in patient_ids:
        src = source_root / pid
        if not src.is_dir():
            matches = [m for m in source_root.rglob(pid) if m.is_dir()]
            if not matches:
                continue
            src = matches[0]
        for path in sorted(src.rglob("*.dcm")):
            if not path.is_file():
                continue
            rel = path.relative_to(source_root)
            out = dest_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
            copied += 1

    _write_inventory(dest_root, patient_ids=list(patient_ids), n_files=copied)
    return dest_root


def _write_inventory(
    dest_root: Path,
    *,
    patient_ids: list[str],
    n_files: int,
) -> None:
    payload = {"patient_ids": patient_ids, "n_files": n_files}
    (dest_root / "inventory.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
