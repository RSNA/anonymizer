"""Classify official MIDI validation_results failures into adversarial buckets.

Public API
----------
TAXONOMY_BUCKETS
    residual_phi, over_scrub, uid_action, private_tag, other.

classify_action(action, *, tag_ds, tcia_ptkb) -> str
    Map one official action (+ optional private hints) to a bucket.

build_adversarial_taxonomy(run_dir) -> dict
    Aggregate fails from validation_results.db into counts, samples, harvest rows.

write_adversarial_taxonomy(run_dir) -> Path
    Write adversarial_taxonomy.json + ADVERSARIAL.md under run_dir.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

TAXONOMY_BUCKETS: tuple[str, ...] = (
    "residual_phi",
    "over_scrub",
    "uid_action",
    "private_tag",
    "other",
)

# Official scorer wraps tokens in angle brackets.
_STRIP_BRACKETS = re.compile(r"^<|>$")

# Odd group hex in DICOM tag like <(0019,1000)> → private.
_TAG_DS_RE = re.compile(r"\(([0-9a-fA-F]{4}),([0-9a-fA-F]{4})\)")

_MIN_CLASSIFIED_RATIO = 0.85


def _bare(value: object) -> str:
    s = str(value or "").strip()
    return _STRIP_BRACKETS.sub("", s).strip()


def _is_private_tag_ds(tag_ds: object) -> bool:
    raw = _bare(tag_ds)
    m = _TAG_DS_RE.search(raw)
    if not m:
        return False
    group = int(m.group(1), 16)
    return group % 2 == 1


def classify_action(
    action: str,
    *,
    tag_ds: object = "",
    tcia_ptkb: object = "",
) -> str:
    """
    Map one official validation action to an adversarial bucket.

    Args:
        action: Official action string (often wrapped in <>).
        tag_ds: Tag display string for private-group detection.
        tcia_ptkb: TCIA private-KB category column when present.

    Returns:
        One of TAXONOMY_BUCKETS.
    """
    act = _bare(action).lower()
    ptkb = str(tcia_ptkb or "").strip()
    private_hint = bool(ptkb) or _is_private_tag_ds(tag_ds)

    if act in {"text_removed", "pixels_hidden"}:
        return "private_tag" if private_hint else "residual_phi"
    if act in {"text_retained", "tag_retained", "text_notnull", "pixels_retained"}:
        return "private_tag" if private_hint else "over_scrub"
    if act in {"uid_changed", "uid_consistent", "patid_consistent", "date_shifted"}:
        return "uid_action"
    if private_hint:
        return "private_tag"
    return "other"


def _validation_db(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    primary = run_dir / "official_score" / "midi_b" / "validation_results.db"
    if primary.is_file() and primary.stat().st_size > 0:
        return primary
    raise FileNotFoundError(f"missing/empty validation DB under {run_dir}")


def build_adversarial_taxonomy(run_dir: Path, *, sample_limit: int = 40) -> dict:
    """
    Aggregate official failures into taxonomy counts and harvest candidates.

    Args:
        run_dir: Harness run directory containing official_score/.
        sample_limit: Max sample rows kept per bucket.

    Returns:
        Taxonomy dict ready for JSON serialization.
    """
    db = _validation_db(run_dir)
    con = sqlite3.connect(str(db))
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(validation_results)")}
        has_ptkb = "tcia_ptkb" in cols
        total, passed, failed = con.execute(
            "SELECT COUNT(*), SUM(check_passed = 1), SUM(check_passed = 0) "
            "FROM validation_results"
        ).fetchone()
        total = int(total or 0)
        passed = int(passed or 0)
        failed = int(failed or 0)

        select_cols = "action, tag_ds, tag_name, action_text, file_value, patient"
        if has_ptkb:
            select_cols += ", tcia_ptkb"
        rows = con.execute(
            f"""
            SELECT {select_cols}
            FROM validation_results
            WHERE check_passed = 0
            """
        ).fetchall()
    finally:
        con.close()

    counts: Counter[str] = Counter()
    by_action: Counter[str] = Counter()
    samples: dict[str, list[dict]] = {b: [] for b in TAXONOMY_BUCKETS}
    harvest: list[dict] = []

    for row in rows:
        if has_ptkb:
            action, tag_ds, tag_name, action_text, file_value, patient, tcia_ptkb = row
        else:
            action, tag_ds, tag_name, action_text, file_value, patient = row
            tcia_ptkb = ""
        bucket = classify_action(action, tag_ds=tag_ds, tcia_ptkb=tcia_ptkb)
        counts[bucket] += 1
        by_action[_bare(action) or str(action)] += 1
        if len(samples[bucket]) < sample_limit:
            samples[bucket].append(
                {
                    "action": _bare(action),
                    "tag_ds": _bare(tag_ds),
                    "tag_name": _bare(tag_name),
                    "action_text": _bare(action_text),
                    "file_value": _bare(file_value),
                    "patient": _bare(patient),
                    "tcia_ptkb": str(tcia_ptkb or "").strip() or None,
                }
            )
        # Residual free text still present → live NER harvest candidate.
        if bucket == "residual_phi":
            got = _bare(file_value)
            expect = _bare(action_text)
            if got and got.lower() not in {"none", "null"}:
                harvest.append(
                    {
                        "text": got,
                        "must_detect_substrings": [expect] if expect else [],
                        "must_labels": [],
                        "must_not_detect_substrings": [],
                        "source_patient": _bare(patient),
                        "tag_path": _bare(tag_ds),
                        "tag_name": _bare(tag_name),
                    }
                )

    classified = sum(counts[b] for b in TAXONOMY_BUCKETS if b != "other")
    classified_ratio = (classified / failed) if failed else 1.0
    return {
        "run_dir": str(Path(run_dir).resolve()),
        "validation_db": str(db),
        "totals": {
            "checks": total,
            "passed": passed,
            "failed": failed,
            "pass_pct": (100.0 * passed / total) if total else 0.0,
        },
        "counts": {b: int(counts.get(b, 0)) for b in TAXONOMY_BUCKETS},
        "by_action": dict(by_action.most_common()),
        "classified_ratio": classified_ratio,
        "min_classified_ratio": _MIN_CLASSIFIED_RATIO,
        "samples": samples,
        "ner_harvest": harvest[:200],
    }


def write_adversarial_taxonomy(run_dir: Path) -> Path:
    """
    Write adversarial_taxonomy.json and ADVERSARIAL.md under run_dir.

    Args:
        run_dir: Harness run directory.

    Returns:
        Path to adversarial_taxonomy.json.
    """
    run_dir = Path(run_dir)
    payload = build_adversarial_taxonomy(run_dir)
    json_path = run_dir / "adversarial_taxonomy.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    totals = payload["totals"]
    counts = payload["counts"]
    lines = [
        f"# Adversarial taxonomy — {run_dir.name}",
        "",
        f"**Pass:** {totals['pass_pct']:.2f}% "
        f"({totals['passed']:,} / {totals['checks']:,}; fails {totals['failed']:,})",
        f"**Classified ratio:** {payload['classified_ratio']:.3f} "
        f"(min {payload['min_classified_ratio']})",
        "",
        "## Buckets",
        "",
        "| Bucket | Count |",
        "|---|---:|",
    ]
    for bucket in TAXONOMY_BUCKETS:
        lines.append(f"| `{bucket}` | {counts.get(bucket, 0):,} |")
    lines += [
        "",
        "## Notes",
        "",
        "- `residual_phi`: scrub/remove actions that failed (PHI likely still present).",
        "- `over_scrub`: retain actions that failed (clinical text removed or missing).",
        "- `private_tag`: failures on private groups or TCIA private-KB categories.",
        "- `uid_action`: UID/PatientID consistency or date-shift actions.",
        "",
        f"JSON: `{json_path.name}`",
        "",
    ]
    (run_dir / "ADVERSARIAL.md").write_text("\n".join(lines), encoding="utf-8")

    harvest_path = run_dir / "ner_harvest_candidates.jsonl"
    with harvest_path.open("w", encoding="utf-8") as fh:
        for row in payload.get("ner_harvest") or []:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return json_path
