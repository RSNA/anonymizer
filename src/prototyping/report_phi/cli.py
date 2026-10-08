"""CLI for Encapsulated PDF report PHI EasyOCR × OpenMed experiment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_DEFAULT_GOLD = _PKG / "gold" / "fl_health_cxr.json"
_DEFAULT_SWEEP = _PKG / "sweeps" / "easyocr_openmed.json"
_EXPERIMENT_LOG = _PKG / "REPORT_PHI_EXPERIMENT.md"

_DEFAULT_FIXTURE = Path(
    "/Users/michaelevans/Documents/RSNA Anonymizer/REPORT_TEST/public/"
    "995199-000001/1.2.826.0.1.3680043.10.474.2.995199.2.46787453282255868296646804/"
    "1.2.826.0.1.3680043.10.474.2.995199.2.64504571244824006491674486/"
    "1.2.826.0.1.3680043.10.474.2.995199.2.15316485913428634760002231.dcm"
)


def _fixture(args: argparse.Namespace) -> Path:
    env = os.environ.get("REPORT_PHI_FIXTURE")
    path = Path(args.fixture) if getattr(args, "fixture", None) else None
    if path is None and env:
        path = Path(env)
    if path is None:
        path = _DEFAULT_FIXTURE
    if not path.is_file():
        raise SystemExit(f"Fixture not found: {path} (set --fixture or REPORT_PHI_FIXTURE)")
    return path


def _load_grid(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _params_from_mapping(m: dict) -> "RunParams":
    from prototyping.report_phi.pipeline import RunParams

    return RunParams(
        easyocr=dict(m.get("easyocr") or {}),
        aggregation_strategy=str(m.get("aggregation_strategy") or "max"),
        min_score=float(m.get("min_score") or 0.0),
    )


def _append_experiment(md: str) -> None:
    header_needed = not _EXPERIMENT_LOG.is_file()
    with _EXPERIMENT_LOG.open("a", encoding="utf-8") as f:
        if header_needed:
            f.write("# Report PHI experiment log\n\n")
            f.write("EasyOCR + OpenMed API params only; PHONE regex only.\n\n")
        f.write(md)
        f.write("\n")


def cmd_run(args: argparse.Namespace) -> int:
    from prototyping.report_phi.overlay import write_overlays
    from prototyping.report_phi.pipeline import run_detect
    from prototyping.report_phi.score import (
        format_score_markdown,
        load_gold,
        score_hits,
    )

    fixture = _fixture(args)
    gold = load_gold(Path(args.gold))
    if args.params_json:
        mapping = json.loads(args.params_json)
    else:
        grid = _load_grid(Path(args.grid))
        mapping = grid.get("baseline") or {}
    params = _params_from_mapping(mapping)
    result = run_detect(fixture, params, locale=args.locale)
    report = score_hits(result.hits, gold)
    report.gold_path = Path(args.gold)
    print(format_score_markdown(report, params_key=params.key()))
    for h in result.hits:
        print(f"  HIT {h.source} {h.label} {h.text!r} rect={h.rect}")
    if args.out:
        paths = write_overlays(result.pdf_bytes, result.hits, Path(args.out), stem="run")
        print("overlays:", ", ".join(str(p) for p in paths))
    _append_experiment(
        f"## run {datetime.now(timezone.utc).isoformat()}\n\n"
        + format_score_markdown(report, params_key=params.key())
    )
    return 0 if report.passed else 1


def cmd_sweep(args: argparse.Namespace) -> int:
    from prototyping.report_phi.overlay import write_overlays
    from prototyping.report_phi.pipeline import run_detect
    from prototyping.report_phi.score import (
        format_score_markdown,
        load_gold,
        score_hits,
    )

    fixture = _fixture(args)
    gold = load_gold(Path(args.gold))
    grid_doc = _load_grid(Path(args.grid))
    points = list(grid_doc.get("grid") or [])
    if grid_doc.get("baseline"):
        points = [grid_doc["baseline"], *points]
    out_root = Path(args.out) if args.out else _PKG / "out" / "sweep"
    out_root.mkdir(parents=True, exist_ok=True)

    best_ratio = -1.0
    best_key = ""
    best_passed = False
    best_mapping: dict | None = None
    lines = [
        f"## sweep {datetime.now(timezone.utc).isoformat()}\n",
        f"fixture=`{fixture}` gold=`{args.gold}` n={len(points)}\n",
    ]

    for i, mapping in enumerate(points):
        params = _params_from_mapping(mapping)
        print(f"[{i + 1}/{len(points)}] {params.key()}", flush=True)
        result = run_detect(fixture, params, locale=args.locale)
        report = score_hits(result.hits, gold)
        md = format_score_markdown(report, params_key=params.key())
        print(md)
        lines.append(md)
        stem = f"p{i:02d}"
        write_overlays(result.pdf_bytes, result.hits, out_root, stem=stem)
        (out_root / f"{stem}_hits.json").write_text(
            json.dumps(
                [
                    {
                        "label": h.label,
                        "text": h.text,
                        "source": h.source,
                        "rect": list(h.rect),
                    }
                    for h in result.hits
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        if report.ratio > best_ratio or (report.passed and not best_passed):
            best_ratio = report.ratio
            best_key = params.key()
            best_passed = report.passed
            best_mapping = mapping

    lines.append(f"\n**Best:** `{best_key}` ratio={best_ratio:.2f} passed={best_passed}\n")
    if best_mapping is not None:
        (out_root / "best_params.json").write_text(
            json.dumps(best_mapping, indent=2), encoding="utf-8"
        )
        lines.append(f"Wrote `{out_root / 'best_params.json'}`\n")
    _append_experiment("\n".join(lines))
    print(f"Best: {best_key} ratio={best_ratio:.2f} passed={best_passed}")
    return 0 if best_passed else 1


def cmd_overlay(args: argparse.Namespace) -> int:
    from prototyping.report_phi.overlay import write_overlays
    from prototyping.report_phi.pipeline import run_detect

    fixture = _fixture(args)
    grid = _load_grid(Path(args.grid))
    params = _params_from_mapping(grid.get("baseline") or {})
    result = run_detect(fixture, params, locale=args.locale)
    paths = write_overlays(
        result.pdf_bytes, result.hits, Path(args.out), stem="overlay"
    )
    for p in paths:
        print(p)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Report Encapsulated PDF PHI experiment")
    p.add_argument("--fixture", type=Path, default=None, help="DICOM DOC or .pdf")
    p.add_argument("--gold", type=Path, default=_DEFAULT_GOLD)
    p.add_argument("--grid", type=Path, default=_DEFAULT_SWEEP)
    p.add_argument("--locale", default="en_US")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Single run (baseline or --params-json)")
    r.add_argument("--params-json", default=None, help="Inline JSON RunParams mapping")
    r.add_argument("--out", type=Path, default=None, help="Overlay output dir")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("sweep", help="Sweep EasyOCR × OpenMed grid")
    s.add_argument("--out", type=Path, default=None)
    s.set_defaults(func=cmd_sweep)

    o = sub.add_parser("overlay", help="Baseline detect + overlay PNG")
    o.add_argument("--out", type=Path, required=True)
    o.set_defaults(func=cmd_overlay)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
