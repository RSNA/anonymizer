"""Build the definitive length-stratified PHI text eval dataset.

All rows share the same schema; only text length (and thus context) differs.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from prototyping.metadata_phi.dataset_schema import (
    PhiTextExample,
    build_manifest,
    length_class_for,
    write_dataset,
)
from prototyping.metadata_phi.datasets import (
    DEFAULT_OPENI_DIR,
    DEFAULT_REXERR_DIR,
)
from prototyping.metadata_phi.datasets.openi import iter_reports
from prototyping.metadata_phi.types import Span

_OUT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "en_US"
    / "dataset"
    / "phi_text_eval.jsonl"
)

_IDENTITIES: list[dict[str, str]] = [
    {
        "name": "Helen Park",
        "dob_slash": "03/14/1962",
        "dob_iso": "1962-03-14",
        "addr": "12 Oak Street, Boston, MA 02108",
        "phone": "(555) 123-4567",
        "email": "helen.park@example.org",
        "mrn": "4455667",
        "ssn": "123-45-6789",
    },
    {
        "name": "Robert Chen",
        "dob_slash": "11/03/1958",
        "dob_iso": "1958-11-03",
        "addr": "2200 Market Street, Philadelphia, PA 19103",
        "phone": "(215) 555-0198",
        "email": "r.chen@example.com",
        "mrn": "9988776",
        "ssn": "987-65-4321",
    },
    {
        "name": "Maria Santos",
        "dob_slash": "07/22/1975",
        "dob_iso": "1975-07-22",
        "addr": "4821 Willow Creek Drive, Austin, TX 78745",
        "phone": "512-555-0144",
        "email": "maria.santos@example.net",
        "mrn": "3322110",
        "ssn": "321-54-9876",
    },
    {
        "name": "James O'Neill",
        "dob_slash": "01/09/1949",
        "dob_iso": "1949-01-09",
        "addr": "88 Harbor View Road, Seattle, WA 98109",
        "phone": "+1-206-555-0177",
        "email": "j.oneill@example.edu",
        "mrn": "A774419",
        "ssn": "111-22-3333",
    },
    {
        "name": "Priya Nair",
        "dob_slash": "09/30/1988",
        "dob_iso": "1988-09-30",
        "addr": "1500 Peachtree Street, Atlanta, GA 30309",
        "phone": "(404) 555-0162",
        "email": "priya.nair@example.org",
        "mrn": "MRN-550012",
        "ssn": "456-78-9012",
    },
]

_SHORT_NEGATIVES = [
    "MR BREAST BILATERAL",
    "CT CHEST WITH CONTRAST",
    "PORTABLE AP CHEST",
    "Protocol 12 Series 3",
    "kVp 120 mAs 200",
    "UID 1.2.840.113619.2.55.3.2831166119.567",
    "Axial T1 T2 DWI",
    "BI-RADS 2",
    "No acute finding",
    "Left breast",
    "Series 7 reformats",
    "Ortho Standard",
    "Fluoro Loop",
    "RADIATION DOSE INFORMATION",
    "ANGIO",
]


def _span(text: str, fragment: str, label: str) -> Span:
    start = text.index(fragment)
    return Span(label=label, start=start, end=start + len(fragment))


def _spans(text: str, pairs: list[tuple[str, str]]) -> list[Span]:
    return [_span(text, frag, lab) for frag, lab in pairs]


def _ex(eid: str, text: str, spans: list[Span]) -> PhiTextExample:
    return PhiTextExample(id=eid, text=text, spans=spans, length_class=length_class_for(text))


def _insert_mid(text: str, sentence: str) -> str:
    cut = max(40, len(text) // 2)
    dot = text.find(". ", cut)
    if 0 <= dot < len(text) - 2:
        cut = dot + 2
    return text[:cut] + sentence + " " + text[cut:]


def _pad_to_long(body: str) -> str:
    """Ensure report-like text exceeds medium length threshold."""
    filler = (
        "\n\nFINDINGS\n"
        "The lungs are clear without focal consolidation. No pleural effusion. "
        "The cardiomediastinal silhouette is within normal limits. Soft tissues "
        "and osseous structures are unremarkable on this examination. "
        "Visualized upper abdomen is unremarkable.\n\n"
        "IMPRESSION\n"
        "No acute cardiopulmonary process. Clinical correlation is recommended "
        "if symptoms persist. Images were reviewed again; impression unchanged.\n"
    )
    text = body
    while len(text) <= 400:
        text = text.rstrip() + filler
    return text


def build_short_examples(rng: random.Random) -> list[PhiTextExample]:
    rows: list[PhiTextExample] = []
    n = 0
    for ident in _IDENTITIES:
        for text, pairs in [
            (ident["name"], [(ident["name"], "NAME")]),
            (f"MRN: {ident['mrn']}", [(ident["mrn"], "ID")]),
            (ident["phone"], [(ident["phone"], "PHONE")]),
            (ident["email"], [(ident["email"], "EMAIL")]),
            (ident["dob_slash"], [(ident["dob_slash"], "DATE")]),
            (ident["dob_iso"], [(ident["dob_iso"], "DATE")]),
            (ident["ssn"], [(ident["ssn"], "ID")]),
            (f"Patient ID {ident['mrn']}", [(ident["mrn"], "ID")]),
        ]:
            n += 1
            rows.append(_ex(f"s{n:04d}", text, _spans(text, pairs)))
        # Truncate address to stay short when needed
        addr = ident["addr"]
        if len(addr) <= 64:
            n += 1
            rows.append(_ex(f"s{n:04d}", addr, _spans(addr, [(addr, "LOCATION")])))

    for neg in _SHORT_NEGATIVES:
        n += 1
        rows.append(_ex(f"s{n:04d}", neg, []))

    # Extra short synthetics to reach ~300 with ~50% PHI
    while len([r for r in rows if r.length_class == "short" and r.spans]) < 150:
        ident = rng.choice(_IDENTITIES)
        choice = rng.choice(["name", "mrn", "phone", "email", "date", "ssn"])
        n += 1
        if choice == "name":
            text = ident["name"]
            spans = _spans(text, [(ident["name"], "NAME")])
        elif choice == "mrn":
            text = f"ID {ident['mrn']}"
            spans = _spans(text, [(ident["mrn"], "ID")])
        elif choice == "phone":
            text = ident["phone"]
            spans = _spans(text, [(ident["phone"], "PHONE")])
        elif choice == "email":
            text = ident["email"]
            spans = _spans(text, [(ident["email"], "EMAIL")])
        elif choice == "date":
            text = ident["dob_slash"]
            spans = _spans(text, [(ident["dob_slash"], "DATE")])
        else:
            text = f"SSN {ident['ssn']}"
            spans = _spans(text, [(ident["ssn"], "ID")])
        if length_class_for(text) != "short":
            continue
        rows.append(_ex(f"s{n:04d}", text, spans))

    while len([r for r in rows if r.length_class == "short" and not r.spans]) < 150:
        neg = rng.choice(_SHORT_NEGATIVES)
        n += 1
        rows.append(_ex(f"s{n:04d}", f"{neg} #{n}", []))

    short = [r for r in rows if r.length_class == "short"]
    rng.shuffle(short)
    return short[:300]


def build_medium_examples(
    rng: random.Random,
    *,
    openi_dir: Path,
    rexerr_dir: Path,
) -> list[PhiTextExample]:
    rows: list[PhiTextExample] = []
    n = 0

    # Labeled header style
    for ident in _IDENTITIES * 8:
        text = (
            f"Patient {ident['name']} DOB {ident['dob_slash']} lives at {ident['addr']}. "
            f"Phone {ident['phone']}. Email {ident['email']}. MRN {ident['mrn']}."
        )
        if length_class_for(text) != "medium":
            continue
        pairs = [
            (ident["name"], "NAME"),
            (ident["dob_slash"], "DATE"),
            (ident["addr"], "LOCATION"),
            (ident["phone"], "PHONE"),
            (ident["email"], "EMAIL"),
            (ident["mrn"], "ID"),
        ]
        n += 1
        rows.append(_ex(f"m{n:04d}", text, _spans(text, pairs)))

    # In-paragraph insertion into Open-i
    reports = [r for r in iter_reports(openi_dir) if 80 <= len(r.findings) <= 320]
    rng.shuffle(reports)
    for r in reports[:120]:
        ident = rng.choice(_IDENTITIES)
        sent = (
            f"Compared with imaging from {ident['dob_slash']} interpreted for "
            f"{ident['name']}, findings are unchanged."
        )
        body = _insert_mid(r.findings, sent)
        text = f"FINDINGS: {body}"
        if r.impression:
            text += f"\nIMPRESSION: {r.impression}"
        if length_class_for(text) != "medium":
            # trim impression if too long
            text = f"FINDINGS: {body}"
            if length_class_for(text) != "medium":
                continue
        n += 1
        rows.append(
            _ex(
                f"m{n:04d}",
                text,
                _spans(text, [(ident["dob_slash"], "DATE"), (ident["name"], "NAME")]),
            )
        )

    # Negatives from Open-i / ReXErr (no inserted PHI)
    for r in reports[120:120 + 150]:
        text = r.body
        if length_class_for(text) != "medium":
            text = f"FINDINGS: {r.findings}"
            if length_class_for(text) != "medium":
                continue
        n += 1
        rows.append(_ex(f"m{n:04d}", text, []))

    # ReXErr originals as negatives / bases
    csv_paths = sorted(Path(rexerr_dir).rglob("ReXErr-report-level_*.csv")) if rexerr_dir.is_dir() else []
    if csv_paths:
        import csv

        taken = 0
        with csv_paths[0].open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                text = (row.get("original_report") or "").strip()
                if length_class_for(text) != "medium":
                    continue
                n += 1
                if taken % 2 == 0:
                    rows.append(_ex(f"m{n:04d}", text, []))
                else:
                    ident = _IDENTITIES[taken % len(_IDENTITIES)]
                    sent = f"{ident['name']} underwent the examination; no consolidation."
                    text2 = _insert_mid(text, sent)
                    if length_class_for(text2) != "medium":
                        continue
                    rows.append(
                        _ex(f"m{n:04d}", text2, _spans(text2, [(ident["name"], "NAME")]))
                    )
                taken += 1
                if taken >= 200:
                    break

    # Top up with synthetic medium
    while len([r for r in rows if r.spans]) < 225:
        ident = rng.choice(_IDENTITIES)
        text = (
            f"Outside films from {ident['addr']} dated {ident['dob_iso']} "
            f"were reviewed for {ident['name']}."
        )
        if length_class_for(text) != "medium":
            text += " No acute osseous abnormality. Soft tissues unremarkable."
        if length_class_for(text) != "medium":
            continue
        n += 1
        rows.append(
            _ex(
                f"m{n:04d}",
                text,
                _spans(
                    text,
                    [
                        (ident["addr"], "LOCATION"),
                        (ident["dob_iso"], "DATE"),
                        (ident["name"], "NAME"),
                    ],
                ),
            )
        )

    while len([r for r in rows if not r.spans]) < 225:
        text = (
            "No focal consolidation. Heart size normal. No pleural effusion. "
            f"Protocol note {n}."
        )
        n += 1
        if length_class_for(text) != "medium":
            continue
        rows.append(_ex(f"m{n:04d}", text, []))

    medium = [r for r in rows if r.length_class == "medium"]
    rng.shuffle(medium)
    # Balance ~half/half within 450
    pos = [r for r in medium if r.spans][:225]
    neg = [r for r in medium if not r.spans][:225]
    out = pos + neg
    rng.shuffle(out)
    return out[:450]


def build_long_examples(
    rng: random.Random,
    *,
    openi_dir: Path,
    rexerr_dir: Path,
) -> list[PhiTextExample]:
    rows: list[PhiTextExample] = []
    n = 0

    for i, ident in enumerate(_IDENTITIES * 20):
        body = (
            "CLINICAL HISTORY\n"
            f"Adult patient referred for imaging. Coordination of care with {ident['name']} "
            f"after evaluation at {ident['addr']}. Callback {ident['phone']}. "
            f"Email {ident['email']}. MRN {ident['mrn']}.\n\n"
            "TECHNIQUE\n"
            "Multiplanar reconstructions were reviewed.\n\n"
        )
        text = _pad_to_long(
            body
            + "FINDINGS\nThe lungs are clear.\n\nIMPRESSION\n"
            + f"No acute process. Prior note from {ident['dob_iso']} is similar."
        )
        n += 1
        rows.append(
            _ex(
                f"l{n:04d}",
                text,
                _spans(
                    text,
                    [
                        (ident["name"], "NAME"),
                        (ident["addr"], "LOCATION"),
                        (ident["phone"], "PHONE"),
                        (ident["email"], "EMAIL"),
                        (ident["mrn"], "ID"),
                        (ident["dob_iso"], "DATE"),
                    ],
                ),
            )
        )

    # Long negatives / insertions from ReXErr
    csv_paths = sorted(Path(rexerr_dir).rglob("ReXErr-report-level_*.csv")) if rexerr_dir.is_dir() else []
    if csv_paths:
        import csv

        # Prefer train for volume
        path = next((p for p in csv_paths if "train" in p.name), csv_paths[0])
        taken = 0
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                text = (row.get("original_report") or "").strip()
                if len(text) <= 400:
                    text = _pad_to_long("FINDINGS\n" + text)
                if length_class_for(text) != "long":
                    continue
                n += 1
                if taken % 2 == 0:
                    rows.append(_ex(f"l{n:04d}", text, []))
                else:
                    ident = _IDENTITIES[taken % len(_IDENTITIES)]
                    sent = (
                        f"Discussion with {ident['name']} confirmed symptoms; "
                        f"home {ident['addr']}."
                    )
                    text2 = _insert_mid(text, sent)
                    if length_class_for(text2) != "long":
                        text2 = _pad_to_long(text2)
                    rows.append(
                        _ex(
                            f"l{n:04d}",
                            text2,
                            _spans(
                                text2,
                                [(ident["name"], "NAME"), (ident["addr"], "LOCATION")],
                            ),
                        )
                    )
                taken += 1
                if taken >= 350:
                    break

    # Open-i padded long
    reports = [r for r in iter_reports(openi_dir) if r.findings]
    rng.shuffle(reports)
    for r in reports[:80]:
        text = _pad_to_long(r.body)
        n += 1
        rows.append(_ex(f"l{n:04d}", text, []))

    long_rows = [r for r in rows if r.length_class == "long"]
    rng.shuffle(long_rows)
    pos = [r for r in long_rows if r.spans][:225]
    neg = [r for r in long_rows if not r.spans][:225]
    # Top up if short
    while len(pos) < 225:
        ident = rng.choice(_IDENTITIES)
        text = _pad_to_long(
            f"History for {ident['name']} ({ident['dob_slash']}). Address {ident['addr']}."
        )
        n += 1
        pos.append(
            _ex(
                f"l{n:04d}",
                text,
                _spans(
                    text,
                    [
                        (ident["name"], "NAME"),
                        (ident["dob_slash"], "DATE"),
                        (ident["addr"], "LOCATION"),
                    ],
                ),
            )
        )
    while len(neg) < 225:
        n += 1
        neg.append(_ex(f"l{n:04d}", _pad_to_long(f"Negative case {n}. Lungs clear."), []))

    out = pos[:225] + neg[:225]
    rng.shuffle(out)
    return out[:450]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=_OUT)
    p.add_argument("--openi-dir", type=Path, default=Path(DEFAULT_OPENI_DIR))
    p.add_argument("--rexerr-dir", type=Path, default=Path(DEFAULT_REXERR_DIR))
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    rng = random.Random(args.seed)
    examples: list[PhiTextExample] = []
    examples.extend(build_short_examples(rng))
    examples.extend(
        build_medium_examples(rng, openi_dir=args.openi_dir, rexerr_dir=args.rexerr_dir)
    )
    examples.extend(
        build_long_examples(rng, openi_dir=args.openi_dir, rexerr_dir=args.rexerr_dir)
    )

    # Stable ids
    for i, ex in enumerate(examples, start=1):
        ex.id = f"t{i:06d}"

    write_dataset(args.out, examples)
    manifest = build_manifest(examples)
    man_path = args.out.with_suffix(".manifest.json")
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(examples)} examples → {args.out}")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
