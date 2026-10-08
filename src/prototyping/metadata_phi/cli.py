"""CLI for DICOM metadata / report PHI NER experiment."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from prototyping.metadata_phi.engines.base import available_engines, get_engine
from prototyping.metadata_phi.eval import (
    aggregate,
    format_report,
    load_gold,
    radiology_fp_count,
    score_example,
)
from prototyping.metadata_phi.locale_registry import list_locales
from prototyping.metadata_phi.pipeline import analyze_file, analyze_text

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Metadata / SR / PDF PHI NER experiment")
    p.add_argument("--locale", default="en_US", help="Locale pack (default en_US)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze-text", help="Analyze a text string")
    a.add_argument("text")
    a.add_argument("--engine", default="regex_spacy", choices=available_engines())
    a.add_argument("--no-guard", action="store_true")

    f = sub.add_parser("analyze-file", help="Extract + analyze a DICOM file")
    f.add_argument("path", type=Path)
    f.add_argument("--engine", default="regex_spacy", choices=available_engines())
    f.add_argument("--no-guard", action="store_true")

    e = sub.add_parser("eval", help="Score engines against gold JSONL")
    e.add_argument(
        "--gold",
        type=Path,
        default=_FIXTURES / "en_US" / "gold.jsonl",
        help="Gold JSONL path",
    )
    e.add_argument(
        "--engines",
        nargs="+",
        default=["regex_spacy", "presidio_transformers", "obi_deid", "longformer_deid"],
        help="Engines to score",
    )
    e.add_argument("--no-guard", action="store_true")
    e.add_argument(
        "--radiology-negatives",
        type=Path,
        default=_FIXTURES / "en_US" / "radiology_negatives.jsonl",
        help="JSONL of {text} radiology description negatives",
    )
    e.add_argument(
        "--write-report",
        type=Path,
        default=None,
        help="Optional path to write markdown score tables",
    )

    pin = sub.add_parser(
        "pin-models",
        help="Download clinical DeID weights into METADATA_PHI_MODEL_CACHE (offline reuse)",
    )
    pin.add_argument(
        "--kind",
        choices=["deid", "longformer", "both"],
        default="deid",
        help="Which locale-pack model id to pin (default deid)",
    )

    prep = sub.add_parser(
        "prep-real-data",
        help="Build Open-i + TCIA SR eval JSONL under fixtures/en_US/real/",
    )
    prep.add_argument("--openi-dir", type=Path, default=None)
    prep.add_argument("--tcia-dir", type=Path, default=None)
    prep.add_argument("--out-dir", type=Path, default=_FIXTURES / "en_US" / "real")
    prep.add_argument("--openi-fp-limit", type=int, default=400)
    prep.add_argument("--openi-seed-limit", type=int, default=120)
    prep.add_argument("--tcia-limit", type=int, default=300)

    corpus = sub.add_parser(
        "prep-eval-corpus",
        help="Build fair eval corpus under fixtures/en_US/corpus/ (FP + hard/easy gold)",
    )
    corpus.add_argument("--out-dir", type=Path, default=_FIXTURES / "en_US" / "corpus")
    corpus.add_argument("--heldout-dir", type=Path, default=_FIXTURES / "en_US" / "heldout")
    corpus.add_argument("--openi-dir", type=Path, default=None)
    corpus.add_argument("--tcia-dir", type=Path, default=None)
    corpus.add_argument("--rexerr-dir", type=Path, default=None)
    corpus.add_argument("--pseudo-phi-dir", type=Path, default=None)
    corpus.add_argument("--pseudo-phi-deid-dir", type=Path, default=None)
    corpus.add_argument("--herolim-dir", type=Path, default=None)
    corpus.add_argument("--midi-b-dir", type=Path, default=None)
    corpus.add_argument("--embedded-limit", type=int, default=500)
    corpus.add_argument("--embedded-rexerr-limit", type=int, default=800)
    corpus.add_argument("--cued-limit", type=int, default=200)
    corpus.add_argument("--rexerr-fp-limit", type=int, default=5000)

    er = sub.add_parser(
        "eval-real",
        help="Eval NAME/DATE/LOCATION on Open-i seeded gold + TCIA SR date gold + FP corpora",
    )
    er.add_argument("--real-dir", type=Path, default=_FIXTURES / "en_US" / "real")
    er.add_argument(
        "--engines",
        nargs="+",
        default=["regex_spacy", "presidio_transformers", "obi_deid"],
    )
    er.add_argument("--no-guard", action="store_true")
    er.add_argument("--write-report", type=Path, default=None)

    pds = sub.add_parser(
        "prep-phi-dataset",
        help="Build definitive length-stratified phi_text_eval.jsonl",
    )
    pds.add_argument(
        "--out",
        type=Path,
        default=_FIXTURES / "en_US" / "dataset" / "phi_text_eval.jsonl",
    )
    pds.add_argument("--openi-dir", type=Path, default=None)
    pds.add_argument("--rexerr-dir", type=Path, default=None)
    pds.add_argument("--seed", type=int, default=42)

    eds = sub.add_parser(
        "eval-dataset",
        help="Accuracy + confusion matrices on phi_text_eval.jsonl",
    )
    eds.add_argument(
        "--dataset",
        type=Path,
        default=_FIXTURES / "en_US" / "dataset" / "phi_text_eval.jsonl",
    )
    eds.add_argument(
        "--engines",
        nargs="+",
        default=["patterns", "spacy_ner", "presidio_transformers", "openmed_pii"],
    )
    eds.add_argument("--no-guard", action="store_true")
    eds.add_argument(
        "--write-report",
        type=Path,
        default=_FIXTURES / "en_US" / "dataset" / "eval_dataset.md",
    )

    eh = sub.add_parser(
        "eval-heldout",
        help="MIDI-B 2024 VAL held-out final check (de-id false-alarm rate)",
    )
    eh.add_argument("--midi-b-dir", type=Path, default=None)
    eh.add_argument(
        "--engines",
        nargs="+",
        default=["patterns", "spacy_ner", "presidio_transformers", "openmed_pii"],
    )
    eh.add_argument("--no-guard", action="store_true")
    eh.add_argument(
        "--write-report",
        type=Path,
        default=_FIXTURES / "en_US" / "heldout" / "midi_b_2024_val" / "eval_heldout.md",
    )

    scrub = sub.add_parser(
        "scrub-file",
        help="Experiment keep-and-scrub: redact PHI in DICOM free text → output file",
    )
    scrub.add_argument("path", type=Path)
    scrub.add_argument("--out", type=Path, required=True)
    scrub.add_argument("--engine", default="presidio_transformers", choices=available_engines())
    scrub.add_argument("--no-guard", action="store_true")

    ec = sub.add_parser(
        "eval-corpus",
        help="(Secondary) Fair corpus eval under fixtures/en_US/corpus/",
    )
    ec.add_argument("--corpus-dir", type=Path, default=_FIXTURES / "en_US" / "corpus")
    ec.add_argument(
        "--engines",
        nargs="+",
        default=["patterns", "spacy_ner", "presidio_transformers"],
        help=(
            "Default: patterns (regex-only), spacy_ner (spaCy-only), "
            "presidio_transformers (Presidio DATE_TIME/phone on for free text; "
            "UID tags/spans excluded)"
        ),
    )
    ec.add_argument("--no-guard", action="store_true")
    ec.add_argument(
        "--write-report",
        type=Path,
        default=_FIXTURES / "en_US" / "corpus" / "eval_corpus.md",
    )
    ec.add_argument(
        "--fp-rexerr-limit",
        type=int,
        default=1500,
        help="Cap ReXErr false-alarm docs for runtime (default 1500)",
    )
    ec.add_argument(
        "--fp-openi-limit",
        type=int,
        default=1500,
        help="Cap Open-i false-alarm docs for runtime (default 1500)",
    )

    sub.add_parser("list-engines", help="List engine names and availability")
    sub.add_parser("list-locales", help="List registered locale packs")
    return p


def _cmd_analyze_text(args: argparse.Namespace) -> int:
    spans = analyze_text(
        args.text,
        engine=args.engine,
        locale=args.locale,
        apply_guard=not args.no_guard,
    )
    for s in spans:
        frag = args.text[s.start : s.end]
        print(json.dumps({"label": s.label, "text": frag, "start": s.start, "end": s.end, "score": s.score}))
    return 0


def _cmd_analyze_file(args: argparse.Namespace) -> int:
    results = analyze_file(
        args.path,
        engine=args.engine,
        locale=args.locale,
        apply_guard=not args.no_guard,
    )
    for chunk, spans in results:
        print(f"# {chunk.tag_or_path}")
        for s in spans:
            frag = chunk.text[s.start : s.end]
            print(
                json.dumps(
                    {
                        "tag": chunk.tag_or_path,
                        "label": s.label,
                        "text": frag,
                        "start": s.start,
                        "end": s.end,
                        "score": s.score,
                        "raw_label": s.raw_label,
                    }
                )
            )
    return 0


def _load_negatives(path: Path) -> list[str]:
    if not path.is_file():
        return []
    texts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        texts.append(json.loads(line)["text"])
    return texts


def _cmd_eval(args: argparse.Namespace) -> int:
    gold = load_gold(args.gold)
    negatives = _load_negatives(args.radiology_negatives)
    reports: list[str] = []

    for name in args.engines:
        eng = get_engine(name)
        available = eng.is_available()
        t0 = time.perf_counter()
        per_ex = []
        for ex in gold:
            pred = analyze_text(
                ex.text,
                engine=eng,
                locale=args.locale,
                apply_guard=not args.no_guard,
            )
            per_ex.append(score_example(ex.spans, pred))
        elapsed = time.perf_counter() - t0
        scores = aggregate(per_ex)

        rad_preds = []
        for text in negatives:
            rad_preds.append(
                (
                    text,
                    analyze_text(
                        text,
                        engine=eng,
                        locale=args.locale,
                        apply_guard=not args.no_guard,
                    ),
                )
            )
        rad_fp = radiology_fp_count(rad_preds)
        extra = (
            f"engine={name} available={available} locale={args.locale} "
            f"seconds={elapsed:.3f} radiology_fp={rad_fp}"
        )
        reports.append(format_report(name, scores, extra=extra))
        print(reports[-1])
        print()

    if args.write_report:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text("\n\n".join(reports) + "\n", encoding="utf-8")
        print(f"Wrote report → {args.write_report}")

    return 0


def _cmd_list_engines(_: argparse.Namespace) -> int:
    for name in available_engines():
        eng = get_engine(name)
        err = getattr(eng, "_error", None)
        suffix = f"\terror={err}" if err else ""
        print(f"{name}\tavailable={eng.is_available()}{suffix}")
    return 0


def _cmd_pin_models(args: argparse.Namespace) -> int:
    from prototyping.metadata_phi.model_cache import model_cache_dir, pin_deid_model

    kinds = ["deid", "longformer"] if args.kind == "both" else [args.kind]
    print(f"Cache dir: {model_cache_dir()}")
    for kind in kinds:
        path = pin_deid_model(args.locale, kind=kind)
        print(f"Pinned {kind} → {path}")
    return 0


def _cmd_prep_real_data(args: argparse.Namespace) -> int:
    from prototyping.metadata_phi.datasets import DEFAULT_OPENI_DIR, DEFAULT_TCIA_SR_DIR
    from prototyping.metadata_phi.datasets.build_real_eval import build_openi, build_tcia

    openi = args.openi_dir or Path(DEFAULT_OPENI_DIR)
    tcia = args.tcia_dir or Path(DEFAULT_TCIA_SR_DIR)
    out = args.out_dir
    if openi.is_dir():
        build_openi(
            openi,
            out,
            fp_limit=args.openi_fp_limit,
            seed_limit=args.openi_seed_limit,
        )
    else:
        print(f"SKIP Open-i: missing {openi}")
    if tcia.is_dir():
        build_tcia(tcia, out, limit=args.tcia_limit)
    else:
        print(f"SKIP TCIA SR: missing {tcia}")
    return 0


def _cmd_prep_eval_corpus(args: argparse.Namespace) -> int:
    from prototyping.metadata_phi.datasets import (
        DEFAULT_HEROLIM_SR_DIR,
        DEFAULT_MIDI_B_VAL_DIR,
        DEFAULT_OPENI_DIR,
        DEFAULT_PSEUDO_PHI_DEID_DIR,
        DEFAULT_PSEUDO_PHI_EVAL_DIR,
        DEFAULT_REXERR_DIR,
        DEFAULT_TCIA_SR_DIR,
    )
    from prototyping.metadata_phi.datasets.build_eval_corpus import main as build_corpus

    argv = [
        "--out-dir",
        str(args.out_dir),
        "--heldout-dir",
        str(args.heldout_dir),
        "--openi-dir",
        str(args.openi_dir or DEFAULT_OPENI_DIR),
        "--tcia-dir",
        str(args.tcia_dir or DEFAULT_TCIA_SR_DIR),
        "--rexerr-dir",
        str(args.rexerr_dir or DEFAULT_REXERR_DIR),
        "--pseudo-phi-eval-dir",
        str(args.pseudo_phi_dir or DEFAULT_PSEUDO_PHI_EVAL_DIR),
        "--pseudo-phi-deid-dir",
        str(args.pseudo_phi_deid_dir or DEFAULT_PSEUDO_PHI_DEID_DIR),
        "--herolim-dir",
        str(args.herolim_dir or DEFAULT_HEROLIM_SR_DIR),
        "--midi-b-dir",
        str(args.midi_b_dir or DEFAULT_MIDI_B_VAL_DIR),
        "--embedded-limit",
        str(args.embedded_limit),
        "--embedded-rexerr-limit",
        str(args.embedded_rexerr_limit),
        "--cued-limit",
        str(args.cued_limit),
        "--rexerr-fp-limit",
        str(args.rexerr_fp_limit),
    ]
    return build_corpus(argv)


def _score_gold_file(path: Path, eng, *, locale: str, apply_guard: bool):
    gold = load_gold(path)
    per = [
        score_example(
            ex.spans,
            analyze_text(ex.text, engine=eng, locale=locale, apply_guard=apply_guard),
        )
        for ex in gold
    ]
    return aggregate(per), len(gold)


def _cmd_prep_phi_dataset(args: argparse.Namespace) -> int:
    from prototyping.metadata_phi.datasets import DEFAULT_OPENI_DIR, DEFAULT_REXERR_DIR
    from prototyping.metadata_phi.datasets.build_phi_text_dataset import main as build_ds

    argv = [
        "--out",
        str(args.out),
        "--openi-dir",
        str(args.openi_dir or DEFAULT_OPENI_DIR),
        "--rexerr-dir",
        str(args.rexerr_dir or DEFAULT_REXERR_DIR),
        "--seed",
        str(args.seed),
    ]
    return build_ds(argv)


def _cmd_eval_dataset(args: argparse.Namespace) -> int:
    from prototyping.metadata_phi.eval_dataset import run_dataset_eval

    if not args.dataset.is_file():
        print(
            f"Missing {args.dataset}. Run: python -m prototyping.metadata_phi prep-phi-dataset"
        )
        return 1
    report = run_dataset_eval(
        args.dataset,
        engines=args.engines,
        locale=args.locale,
        apply_guard=not args.no_guard,
    )
    print(report)
    if args.write_report:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text(report, encoding="utf-8")
        print(f"Wrote report → {args.write_report}")
    return 0


def _cmd_eval_heldout(args: argparse.Namespace) -> int:
    from prototyping.metadata_phi.datasets import DEFAULT_MIDI_B_VAL_DIR
    from prototyping.metadata_phi.eval_heldout import run_midi_b_heldout

    midi = args.midi_b_dir or Path(DEFAULT_MIDI_B_VAL_DIR)
    if not Path(midi).is_dir():
        print(f"Missing MIDI-B dir: {midi}")
        return 1
    report = run_midi_b_heldout(
        Path(midi),
        engines=args.engines,
        locale=args.locale,
        apply_guard=not args.no_guard,
    )
    print(report)
    if args.write_report:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text(report, encoding="utf-8")
        print(f"Wrote report → {args.write_report}")
    return 0


def _cmd_scrub_file(args: argparse.Namespace) -> int:
    from prototyping.metadata_phi.scrub import scrub_dicom_file

    result = scrub_dicom_file(
        args.path,
        args.out,
        engine=args.engine,
        locale=args.locale,
        apply_guard=not args.no_guard,
    )
    print(json.dumps(result))
    return 0


def _cmd_eval_corpus(args: argparse.Namespace) -> int:
    from prototyping.metadata_phi.eval_corpus import run_corpus_eval

    corpus = args.corpus_dir
    if not corpus.is_dir():
        print(f"Missing corpus dir {corpus}. Run: python -m prototyping.metadata_phi prep-eval-corpus")
        return 1
    report = run_corpus_eval(
        corpus,
        engines=args.engines,
        locale=args.locale,
        apply_guard=not args.no_guard,
        fp_limits={
            "fp_rexerr.jsonl": args.fp_rexerr_limit,
            "fp_openi.jsonl": args.fp_openi_limit,
        },
    )
    print(report)
    if args.write_report:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text(report, encoding="utf-8")
        print(f"Wrote report → {args.write_report}")
    return 0


def _cmd_eval_real(args: argparse.Namespace) -> int:
    real = args.real_dir
    openi_gold = real / "openi_seeded_gold.jsonl"
    tcia_gold = real / "tcia_sr_date_gold.jsonl"
    openi_fp = real / "openi_fp_negatives.jsonl"
    tcia_fp = real / "tcia_sr_fp_negatives.jsonl"
    for required in (openi_gold, tcia_gold, openi_fp, tcia_fp):
        if not required.is_file():
            print(f"Missing {required}. Run: python -m prototyping.metadata_phi prep-real-data")
            return 1

    reports: list[str] = []
    for name in args.engines:
        eng = get_engine(name)
        available = eng.is_available()
        t0 = time.perf_counter()

        openi_scores, n_openi = _score_gold_file(
            openi_gold, eng, locale=args.locale, apply_guard=not args.no_guard
        )
        tcia_scores, n_tcia = _score_gold_file(
            tcia_gold, eng, locale=args.locale, apply_guard=not args.no_guard
        )

        openi_neg = _load_negatives(openi_fp)
        tcia_neg = _load_negatives(tcia_fp)
        openi_fp_counts = radiology_fp_count(
            [
                (
                    t,
                    analyze_text(
                        t, engine=eng, locale=args.locale, apply_guard=not args.no_guard
                    ),
                )
                for t in openi_neg
            ]
        )
        tcia_fp_counts = radiology_fp_count(
            [
                (
                    t,
                    analyze_text(
                        t, engine=eng, locale=args.locale, apply_guard=not args.no_guard
                    ),
                )
                for t in tcia_neg
            ]
        )
        elapsed = time.perf_counter() - t0

        block = [
            format_report(
                f"{name} — Open-i seeded NAME/DATE/LOCATION (n={n_openi})",
                openi_scores,
                extra=(
                    f"engine={name} available={available} seconds={elapsed:.3f} "
                    f"openi_fp_on_raw_reports={openi_fp_counts}"
                ),
            ),
            "",
            format_report(
                f"{name} — TCIA SR DATE gold (n={n_tcia})",
                tcia_scores,
                extra=f"tcia_sr_fp_on_narratives={tcia_fp_counts}",
            ),
        ]
        text = "\n".join(block)
        reports.append(text)
        print(text)
        print()

    if args.write_report:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text("\n\n".join(reports) + "\n", encoding="utf-8")
        print(f"Wrote report → {args.write_report}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "analyze-text":
        return _cmd_analyze_text(args)
    if args.cmd == "analyze-file":
        return _cmd_analyze_file(args)
    if args.cmd == "eval":
        return _cmd_eval(args)
    if args.cmd == "prep-real-data":
        return _cmd_prep_real_data(args)
    if args.cmd == "prep-eval-corpus":
        return _cmd_prep_eval_corpus(args)
    if args.cmd == "prep-phi-dataset":
        return _cmd_prep_phi_dataset(args)
    if args.cmd == "eval-dataset":
        return _cmd_eval_dataset(args)
    if args.cmd == "eval-heldout":
        return _cmd_eval_heldout(args)
    if args.cmd == "scrub-file":
        return _cmd_scrub_file(args)
    if args.cmd == "eval-corpus":
        return _cmd_eval_corpus(args)
    if args.cmd == "eval-real":
        return _cmd_eval_real(args)
    if args.cmd == "pin-models":
        return _cmd_pin_models(args)
    if args.cmd == "list-engines":
        return _cmd_list_engines(args)
    if args.cmd == "list-locales":
        print("\n".join(list_locales()))
        return 0
    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
