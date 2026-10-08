"""Build eval JSONL from Open-i reports + TCIA DICOM SR (local paths).

Outputs under fixtures/en_US/real/:
  openi_fp_negatives.jsonl   — raw FINDINGS/IMPRESSION (expect near-zero PHI)
  openi_seeded_gold.jsonl    — real report scaffolds + injected fake PHI (recall)
  tcia_sr_date_gold.jsonl    — narrative dates from TCIA SR TextValue
  tcia_sr_fp_negatives.jsonl — study/series descriptions + narratives (FP check)
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from prototyping.metadata_phi.datasets import DEFAULT_OPENI_DIR, DEFAULT_TCIA_SR_DIR
from prototyping.metadata_phi.datasets.openi import iter_reports

_FIXTURES_REAL = Path(__file__).resolve().parents[1] / "fixtures" / "en_US" / "real"

_DATE_IN_NARRATIVE = re.compile(
    r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"
)

# Injected PHI templates — fake only; never real patient data.
_SEED_POOL = [
    {
        "prefix": "Patient {name} DOB {dob}. Address {addr}. ",
        "name": "Helen Park",
        "dob": "03/14/1962",
        "addr": "12 Oak Street, Boston, MA 02108",
        "spans": [
            ("Helen Park", "NAME"),
            ("03/14/1962", "DATE"),
            ("12 Oak Street, Boston, MA 02108", "LOCATION"),
        ],
    },
    {
        "prefix": "Referring Dr. {name}. Lives at {addr}. Exam date {dob}. ",
        "name": "Robert Chen",
        "dob": "2024-11-03",
        "addr": "2200 Market Street, Philadelphia, PA 19103",
        "spans": [
            ("Robert Chen", "NAME"),
            ("2200 Market Street, Philadelphia, PA 19103", "LOCATION"),
            ("2024-11-03", "DATE"),
        ],
    },
    {
        "prefix": "Patient: {name}. Home {addr}. DOB {dob}. ",
        "name": "Maria Santos",
        "dob": "07/22/1975",
        "addr": "4821 Willow Creek Drive, Austin, TX 78745",
        "spans": [
            ("Maria Santos", "NAME"),
            ("4821 Willow Creek Drive, Austin, TX 78745", "LOCATION"),
            ("07/22/1975", "DATE"),
        ],
    },
]


def _span(text: str, fragment: str, label: str) -> dict:
    start = text.index(fragment)
    return {"label": label, "start": start, "end": start + len(fragment)}


def build_openi(
    openi_dir: Path,
    out_dir: Path,
    *,
    fp_limit: int = 400,
    seed_limit: int = 120,
    seed: int = 42,
) -> None:
    reports = iter_reports(openi_dir)
    rng = random.Random(seed)
    # Prefer longer findings for seeding
    candidates = [r for r in reports if len(r.findings) >= 40]
    rng.shuffle(candidates)

    fp_rows = []
    for r in candidates[:fp_limit]:
        text = r.body
        fp_rows.append({"id": r.id, "text": text, "source": "openi", "path": str(r.path)})

    seed_rows = []
    for i, r in enumerate(candidates[:seed_limit]):
        tmpl = _SEED_POOL[i % len(_SEED_POOL)]
        prefix = tmpl["prefix"].format(name=tmpl["name"], dob=tmpl["dob"], addr=tmpl["addr"])
        # Keep FINDINGS body (real language); put injected PHI in a header block.
        body = f"FINDINGS: {r.findings}"
        if r.impression:
            body += f"\nIMPRESSION: {r.impression}"
        text = prefix + body
        spans = [_span(text, frag, lab) for frag, lab in tmpl["spans"]]
        seed_rows.append(
            {
                "id": f"openi_seed_{r.id}",
                "text": text,
                "spans": spans,
                "notes": "Open-i findings scaffold + injected fake PHI",
                "source": "openi_seeded",
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "openi_fp_negatives.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in fp_rows) + "\n", encoding="utf-8"
    )
    (out_dir / "openi_seeded_gold.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in seed_rows) + "\n", encoding="utf-8"
    )
    print(f"Open-i FP negatives: {len(fp_rows)} → {out_dir / 'openi_fp_negatives.jsonl'}")
    print(f"Open-i seeded gold:  {len(seed_rows)} → {out_dir / 'openi_seeded_gold.jsonl'}")


def build_tcia(
    tcia_dir: Path,
    out_dir: Path,
    *,
    limit: int = 300,
    scan_all_for_dates: bool = True,
) -> None:
    """
    Scan SR files for DATE gold (often sparse — e.g. only tcga_brca narratives).

    ``limit`` caps the FP corpus size; date gold uses a full scan when
    ``scan_all_for_dates`` is true so dated reports are not missed by sort order.
    """
    from prototyping.metadata_phi.datasets.tcia_sr import iter_sr_files, load_sr

    all_paths = iter_sr_files(tcia_dir, limit=None if scan_all_for_dates else limit)
    date_gold = []
    fp_candidates = []
    for path in all_paths:
        doc = load_sr(path)
        narr = doc.narrative_text
        if not narr.strip():
            continue
        fp_candidates.append(
            {
                "id": doc.path.stem,
                "text": narr,
                "source": "tcia_sr",
                "path": str(doc.path),
            }
        )
        dates = list(_DATE_IN_NARRATIVE.finditer(narr))
        if not dates:
            continue
        spans = [{"label": "DATE", "start": m.start(), "end": m.end()} for m in dates]
        date_gold.append(
            {
                "id": f"tcia_{doc.path.stem}",
                "text": narr,
                "spans": spans,
                "notes": "TCIA SR narrative calendar dates; no NAME gold (de-id research IDs)",
                "source": "tcia_sr",
            }
        )

    # Stratify FP sample across collections when possible
    rng = random.Random(42)
    rng.shuffle(fp_candidates)
    fp_rows = fp_candidates[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tcia_sr_fp_negatives.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in fp_rows) + "\n", encoding="utf-8"
    )
    (out_dir / "tcia_sr_date_gold.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in date_gold) + "\n", encoding="utf-8"
    )
    print(f"TCIA SR FP corpus:   {len(fp_rows)} → {out_dir / 'tcia_sr_fp_negatives.jsonl'}")
    print(f"TCIA SR DATE gold:   {len(date_gold)} → {out_dir / 'tcia_sr_date_gold.jsonl'}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--openi-dir", type=Path, default=Path(DEFAULT_OPENI_DIR))
    p.add_argument("--tcia-dir", type=Path, default=Path(DEFAULT_TCIA_SR_DIR))
    p.add_argument("--out-dir", type=Path, default=_FIXTURES_REAL)
    p.add_argument("--openi-fp-limit", type=int, default=400)
    p.add_argument("--openi-seed-limit", type=int, default=120)
    p.add_argument("--tcia-limit", type=int, default=300)
    args = p.parse_args(argv)

    if args.openi_dir.is_dir():
        build_openi(
            args.openi_dir,
            args.out_dir,
            fp_limit=args.openi_fp_limit,
            seed_limit=args.openi_seed_limit,
        )
    else:
        print(f"SKIP Open-i: missing {args.openi_dir}")

    if args.tcia_dir.is_dir():
        build_tcia(args.tcia_dir, args.out_dir, limit=args.tcia_limit)
    else:
        print(f"SKIP TCIA SR: missing {args.tcia_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
