"""CLI: run / eval / sweep EasyOCR settings on MIDI-B pixel_phi."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PKG = Path(__file__).resolve().parent
_DEFAULT_GOLD = _PKG / "gold" / "113575183.json"
_DEFAULT_SWEEP = _PKG / "sweeps" / "efficient_corpus.json"
_DEFAULT_CHEST_SWEEP = _PKG / "sweeps" / "chest_markers.json"
_DEFAULT_MANIFEST = Path("/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/pixel_phi/manifest.json")
_DEFAULT_DCM = Path(
    "/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/pixel_phi/test/113575183/"
    "11-11-2013-NA-XR CHEST 1 VIEW AP for 486-93-8764-77898/"
    "20131111.000000-AP-54935/1-1.dcm"
)
_EXPERIMENT_LOG = _PKG / "PIXEL_PHI_EASYOCR_EXPERIMENT.md"
_OUT_DIR = _PKG / "out"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _append_experiment(md: str) -> None:
    header_needed = not _EXPERIMENT_LOG.is_file()
    with _EXPERIMENT_LOG.open("a", encoding="utf-8") as f:
        if header_needed:
            f.write("# Pixel PHI EasyOCR experiment log\n\n")
            f.write(
                "Tune `readtext` kwargs for MIDI-B `pixel_phi` gold boxes. "
                "Prefer ≥95% case accuracy at **relative_cost ≤ product baseline** "
                "(~3.0 for non-US with rotation TTA). Promote winners into "
                "`detect_text._easyocr_readtext`.\n\n"
            )
        f.write(md)
        f.write("\n")


def _dcm_path(args: argparse.Namespace) -> Path:
    path = Path(args.dcm) if args.dcm else _DEFAULT_DCM
    if not path.is_file():
        raise SystemExit(f"DICOM not found: {path}")
    return path


def cmd_run(args: argparse.Namespace) -> int:
    from prototyping.ocr.pixel_phi_easyocr.pipeline import (
        ensure_anonymizer_cwd,
        load_ocr_pixels,
        run_easyocr,
        write_overlay_png,
    )
    from prototyping.ocr.pixel_phi_easyocr.score import (
        GoldSpec,
        format_score_markdown,
        score_run,
    )

    ensure_anonymizer_cwd()
    gold = GoldSpec.from_mapping(_load_json(Path(args.gold)))
    dcm = _dcm_path(args)
    overrides: dict[str, Any] = {}
    if args.params_json:
        overrides = dict(_load_json(Path(args.params_json)).get("easyocr") or {})
    ds, pixels = load_ocr_pixels(dcm)
    modality = str(ds.get("Modality", "") or "CR")
    result = run_easyocr(pixels, modality=modality, overrides=overrides)
    report = score_run(
        params_key=result.params_key,
        raw_hits=result.raw,
        filtered_hits=result.filtered,
        gold=gold,
    )
    print(format_score_markdown(report))
    print("easyocr_raw:", json.dumps(result.easyocr_raw, indent=2))
    if args.out:
        out = Path(args.out)
        write_overlay_png(pixels, result.raw, out, title=result.params_key[:80])
        print("overlay:", out)
    _append_experiment(
        f"## run {datetime.now(timezone.utc).isoformat()}\n\n"
        f"dcm=`{dcm}`\n\n"
        + format_score_markdown(report)
    )
    return 0 if report.passed else 1


def _grid_points(grid_doc: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    if grid_doc.get("baseline") is not None:
        base = grid_doc["baseline"] or {}
        points.append(
            {
                "name": str(base.get("name") or "baseline"),
                "easyocr": dict(base.get("easyocr") or {}),
            }
        )
    for i, point in enumerate(grid_doc.get("grid") or []):
        points.append(
            {
                "name": str(point.get("name") or f"grid_{i}"),
                "easyocr": dict(point.get("easyocr") or {}),
            }
        )
    return points


def cmd_eval(args: argparse.Namespace) -> int:
    """Evaluate one config (default: product baseline) on the full corpus."""
    from prototyping.ocr.pixel_phi_easyocr.corpus import load_pixel_phi_cases
    from prototyping.ocr.pixel_phi_easyocr.cost import product_baseline_cost
    from prototyping.ocr.pixel_phi_easyocr.eval_corpus import eval_overrides_on_corpus
    from prototyping.ocr.pixel_phi_easyocr.pipeline import ensure_anonymizer_cwd, get_ocr_reader
    from prototyping.ocr.pixel_phi_easyocr.score import format_corpus_markdown

    ensure_anonymizer_cwd()
    cases = load_pixel_phi_cases(Path(args.manifest))
    overrides: dict[str, Any] = {}
    if args.params_json:
        overrides = dict(_load_json(Path(args.params_json)).get("easyocr") or {})
    reader = get_ocr_reader()
    report = eval_overrides_on_corpus(
        cases,
        overrides,
        reader=reader,
        target_accuracy=float(args.target),
    )
    print(format_corpus_markdown(report))
    print(
        f"product_baseline_cost≈{product_baseline_cost():.2f} "
        f"this_cost={report.relative_cost:.2f}"
    )
    out = Path(args.out) if args.out else _OUT_DIR / "eval_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "params_key": report.params_key,
                "overrides": report.overrides,
                "case_accuracy": report.case_accuracy,
                "box_recall": report.box_recall,
                "relative_cost": report.relative_cost,
                "met_target": report.met_target,
                "failures": [
                    {
                        "case_id": c.case_id,
                        "modality": c.modality,
                        "miss": [m.gold_text for m in c.box_matches if not m.matched],
                        "raw": c.raw_texts,
                    }
                    for c in report.cases
                    if not c.passed
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("wrote", out)
    _append_experiment(
        f"## eval {datetime.now(timezone.utc).isoformat()}\n\n" + format_corpus_markdown(report)
    )
    return 0 if report.met_target else 1


def cmd_sweep(args: argparse.Namespace) -> int:
    """Sweep efficient grid across full pixel_phi corpus; pick best under cost cap."""
    from prototyping.ocr.pixel_phi_easyocr.corpus import load_pixel_phi_cases
    from prototyping.ocr.pixel_phi_easyocr.cost import product_baseline_cost
    from prototyping.ocr.pixel_phi_easyocr.eval_corpus import eval_overrides_on_corpus, rank_key
    from prototyping.ocr.pixel_phi_easyocr.pipeline import ensure_anonymizer_cwd, get_ocr_reader
    from prototyping.ocr.pixel_phi_easyocr.score import format_corpus_markdown

    ensure_anonymizer_cwd()
    grid_doc = _load_json(Path(args.grid))
    points = _grid_points(grid_doc)
    target = float(args.target if args.target is not None else grid_doc.get("target_accuracy") or 0.95)
    max_cost = float(
        args.max_cost
        if args.max_cost is not None
        else grid_doc.get("max_relative_cost") or (product_baseline_cost() + 0.5)
    )
    cases = load_pixel_phi_cases(Path(args.manifest))
    reader = get_ocr_reader()
    out_root = Path(args.out) if args.out else _OUT_DIR / "sweep_corpus"
    out_root.mkdir(parents=True, exist_ok=True)

    lines = [
        f"## corpus sweep {datetime.now(timezone.utc).isoformat()}\n",
        f"manifest=`{args.manifest}` n_cases={len(cases)} n_configs={len(points)} "
        f"target={target:.0%} max_rel_cost={max_cost:.2f}\n",
        "memory: one frame at a time; torch cache cleared after each image\n",
    ]
    reports = []
    for point in points:
        name = point["name"]
        overrides = point["easyocr"]
        print(f"\n=== {name} ===", flush=True)
        report = eval_overrides_on_corpus(
            cases,
            overrides,
            reader=reader,
            target_accuracy=target,
        )
        # Stamp name into key for readability
        report.params_key = f"{name}:{report.params_key}"
        print(format_corpus_markdown(report), flush=True)
        lines.append(format_corpus_markdown(report))
        reports.append(report)
        (out_root / f"{name}.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "overrides": report.overrides,
                    "case_accuracy": report.case_accuracy,
                    "box_recall": report.box_recall,
                    "relative_cost": report.relative_cost,
                    "met_target": report.met_target,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    eligible = [r for r in reports if r.relative_cost <= max_cost]
    pool = eligible or reports
    best = max(pool, key=rank_key)
    best_path = out_root / "best_params.json"
    best_path.write_text(
        json.dumps(
            {
                "params_key": best.params_key,
                "score_case_accuracy": best.case_accuracy,
                "box_recall": best.box_recall,
                "relative_cost": best.relative_cost,
                "product_baseline_cost": product_baseline_cost(),
                "max_relative_cost": max_cost,
                "met_target": best.met_target,
                "easyocr": best.overrides,
                "merge_hint": (
                    "Apply non-empty keys into detect_text._easyocr_readtext only if "
                    "relative_cost stays ≤ product baseline when possible."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = (
        f"\n**Best under cost cap {max_cost:.2f}:** `{best.params_key}` "
        f"acc={best.case_accuracy:.1%} box={best.box_recall:.1%} "
        f"cost={best.relative_cost:.2f} met_target={best.met_target}\n\n"
        f"Wrote `{best_path}`\n"
    )
    print(summary)
    lines.append(summary)
    _append_experiment("\n".join(lines))
    return 0 if best.met_target else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pixel_phi_easyocr",
        description="Efficient EasyOCR tuning for MIDI-B pixel_phi (95% case accuracy target).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Single DICOM / gold JSON (FTA smoke)")
    run_p.add_argument("--dcm", type=str, default=None)
    run_p.add_argument("--gold", type=str, default=str(_DEFAULT_GOLD))
    run_p.add_argument("--params-json", type=str, default=None)
    run_p.add_argument("--out", type=str, default=None)
    run_p.set_defaults(func=cmd_run)

    eval_p = sub.add_parser("eval", help="One config on all pixel_phi cases")
    eval_p.add_argument("--manifest", type=str, default=str(_DEFAULT_MANIFEST))
    eval_p.add_argument("--params-json", type=str, default=None)
    eval_p.add_argument("--target", type=float, default=0.95)
    eval_p.add_argument("--out", type=str, default=None)
    eval_p.set_defaults(func=cmd_eval)

    sweep_p = sub.add_parser("sweep", help="Efficient grid × full corpus")
    sweep_p.add_argument("--manifest", type=str, default=str(_DEFAULT_MANIFEST))
    sweep_p.add_argument("--grid", type=str, default=str(_DEFAULT_SWEEP))
    sweep_p.add_argument("--target", type=float, default=None)
    sweep_p.add_argument("--max-cost", type=float, default=None, help="Max relative_cost to accept")
    sweep_p.add_argument("--out", type=str, default=None)
    sweep_p.set_defaults(func=cmd_sweep)

    init_p = sub.add_parser(
        "initials",
        help="Focused FTA/R deskew: gold crop + fine angles (not 90° TTA)",
    )
    init_p.add_argument("--dcm", type=str, default=None)
    init_p.add_argument(
        "--angles",
        type=str,
        default="0,15,30,45,60,-15,-30,-45,-60,90,-90",
    )
    init_p.add_argument("--out", type=str, default=None)
    init_p.set_defaults(func=cmd_initials)

    return parser


def cmd_initials(args: argparse.Namespace) -> int:
    """Crop gold FTA / top-left and sweep fine deskew angles."""
    from prototyping.ocr.pixel_phi_easyocr.initials_rotation import (
        _DEFAULT_DCM,
        main as initials_main,
    )

    argv = ["--dcm", args.dcm or str(_DEFAULT_DCM), "--angles", args.angles]
    if args.out:
        argv.extend(["--out", args.out])
    if args.verbose:
        argv.append("-v")
    return initials_main(argv)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
