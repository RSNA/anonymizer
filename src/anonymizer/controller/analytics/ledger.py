"""Project-level series anatomy ledger for Dataset analytics.

Per-series ``organ_volumes_ml.json`` remains the volume source of truth. This
ledger stores compact anatomy rows so Dashboard Refresh can assemble charts
without walking ``images/`` at thousands of series.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

LEDGER_DIRNAME = "analytics"
LEDGER_FILENAME = "series_ledger.jsonl"


def ledger_path_for_images_dir(images_dir: Path) -> Path:
    """Resolve the project analytics ledger path for an images tree.

    Prefer ``{storage}/analytics/series_ledger.jsonl`` when ``images_dir`` is the
    project public tree (sibling of the project model). Otherwise keep the ledger
    under ``images_dir/analytics/`` so ad-hoc/test roots stay self-contained.
    """
    images_dir = Path(images_dir).resolve()
    storage_dir = images_dir.parent
    project_markers = (
        "ProjectModel.json",
        "ProjectModel.pkl",
    )
    if any((storage_dir / name).exists() for name in project_markers):
        return storage_dir / LEDGER_DIRNAME / LEDGER_FILENAME
    return images_dir / LEDGER_DIRNAME / LEDGER_FILENAME


@dataclass(frozen=True)
class SeriesLedgerRow:
    """One segmented series contribution to anatomy analytics."""

    anon_series_uid: str
    anon_patient_id: str
    modality: str
    head_limited: bool
    regions: tuple[str, ...]
    organs_ml: Mapping[str, float]
    updated_at: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "anon_series_uid": self.anon_series_uid,
            "anon_patient_id": self.anon_patient_id,
            "modality": self.modality,
            "head_limited": bool(self.head_limited),
            "regions": list(self.regions),
            "organs_ml": {str(k): float(v) for k, v in sorted(self.organs_ml.items()) if float(v) > 0},
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_json_dict(payload: Mapping[str, Any]) -> SeriesLedgerRow | None:
        uid = str(payload.get("anon_series_uid") or "").strip()
        patient = str(payload.get("anon_patient_id") or "").strip()
        if not uid or not patient:
            return None
        modality = str(payload.get("modality") or "").strip().upper() or "Unknown"
        regions_raw = payload.get("regions") or []
        if not isinstance(regions_raw, list):
            return None
        regions = tuple(str(r) for r in regions_raw if str(r).strip())
        organs_raw = payload.get("organs_ml") or {}
        if not isinstance(organs_raw, Mapping):
            return None
        organs: dict[str, float] = {}
        for key, value in organs_raw.items():
            try:
                ml = float(value)
            except (TypeError, ValueError):
                continue
            if ml > 0:
                organs[str(key)] = ml
        updated = str(payload.get("updated_at") or "")
        return SeriesLedgerRow(
            anon_series_uid=uid,
            anon_patient_id=patient,
            modality=modality,
            head_limited=bool(payload.get("head_limited")),
            regions=regions,
            organs_ml=organs,
            updated_at=updated,
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ledger_exists(images_dir: Path) -> bool:
    return ledger_path_for_images_dir(images_dir).is_file()


def read_ledger_rows(images_dir: Path) -> dict[str, SeriesLedgerRow]:
    """Load ledger keyed by ``anon_series_uid`` (last line wins on duplicates)."""
    path = ledger_path_for_images_dir(images_dir)
    if not path.is_file():
        return {}
    rows: dict[str, SeriesLedgerRow] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Analytics ledger: could not read %s: %s", path, exc)
        return {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Analytics ledger: skip bad JSON at %s:%d", path, line_no)
            continue
        if not isinstance(payload, dict):
            continue
        row = SeriesLedgerRow.from_json_dict(payload)
        if row is None:
            continue
        rows[row.anon_series_uid] = row
    return rows


def write_ledger_rows(images_dir: Path, rows: Mapping[str, SeriesLedgerRow]) -> Path:
    """Atomically rewrite the ledger (sorted by series uid for stable diffs)."""
    path = ledger_path_for_images_dir(images_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    lines = [
        json.dumps(rows[uid].to_json_dict(), separators=(",", ":")) + "\n"
        for uid in sorted(rows.keys())
    ]
    try:
        tmp_path.write_text("".join(lines), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise
    return path


def upsert_series_row(images_dir: Path, row: SeriesLedgerRow) -> Path:
    """Insert or replace one series row in the project ledger."""
    rows = read_ledger_rows(images_dir)
    rows[row.anon_series_uid] = row
    return write_ledger_rows(images_dir, rows)


def replace_ledger_rows(images_dir: Path, rows: Mapping[str, SeriesLedgerRow]) -> Path:
    """Full rewrite used by legacy rebuild."""
    return write_ledger_rows(images_dir, dict(rows))
