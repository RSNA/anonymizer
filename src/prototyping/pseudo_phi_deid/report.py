"""Glossary-first SCORECARD and FINAL_REPORT."""

import json
from collections.abc import Sequence
from pathlib import Path

from prototyping.pseudo_phi_deid import ACCURACY_GATE
from prototyping.pseudo_phi_deid.paths import RESULTS_DIR
from prototyping.pseudo_phi_deid.score import ScoreMetrics

GLOSSARY = f"""
## How to read the numbers

We compare pipeline **candidates** (from Evaluation) to **DeIdentified gold**.

| Report label | Meaning |
|--------------|---------|
| **Cohort accuracy** | Share of comparable header + pixel + overlay checks that match gold (micro-average). **Pass if > {ACCURACY_GATE:.0%}.** |
| **Header accuracy** | Non-UID DICOM header fields matching gold (text normalized). |
| **Pixel accuracy** | Pixel-array agreement rule: if eval==gold pixels, candidate must not invent redaction; if they differ (burn-in), candidate must clean toward gold. |
| **Overlay accuracy** | Presence/absence of 60xx overlays matches gold (gold removes PT graphics overlays). |
| **Paired files scored** | Evaluation↔gold pairs included. |

**UIDs are excluded** from accuracy (Study/Series/SOP and VR UI). Anonymizer stamp tags are excluded.
""".strip()


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join(
        "| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in rows
    )
    return "\n".join([line, sep, body]) if rows else "\n".join([line, sep])


def write_scorecard(
    path: Path,
    *,
    title: str,
    goal: str,
    changed: str,
    config: dict,
    metrics: ScoreMetrics,
    next_step: str,
    max_fails: int = 25,
) -> None:
    rows = [
        ["Cohort accuracy (%)", f"{metrics.cohort_accuracy}", "PASS" if metrics.passed_gate else "FAIL"],
        ["Header accuracy (%)", f"{metrics.header_accuracy}", ""],
        ["Pixel accuracy (%)", f"{metrics.pixel_accuracy}", ""],
        ["Overlay accuracy (%)", f"{metrics.overlay_accuracy}", ""],
        ["Paired files scored", str(metrics.pairs), ""],
        [
            "Header matches / comparable",
            f"{metrics.header_matches} / {metrics.header_comparable}",
            "",
        ],
    ]
    mod_rows = [[m, f"{a}"] for m, a in sorted(metrics.modality_accuracy.items())]
    hist_rows = [[k, str(v)] for k, v in list(metrics.histogram.items())[:40]]
    fail_rows = [
        [
            f.kind,
            f.tag_path,
            _short(f.eval_value),
            _short(f.candidate_value),
            _short(f.gold_value),
            _short(f.note, 40),
        ]
        for f in metrics.failures[:max_fails]
    ]
    lines = [
        f"# {title}",
        "",
        f"**Goal:** {goal}",
        "",
        f"**What changed:** {changed}",
        "",
        GLOSSARY,
        "",
        "## Headline metrics",
        "",
        _md_table(["What it means", "Value", "Gate"], rows),
        "",
        "## Accuracy by modality",
        "",
        _md_table(["modality", "accuracy %"], mod_rows) if mod_rows else "_n/a_",
        "",
        "## Config",
        "",
        "```json",
        json.dumps(config, indent=2, default=str),
        "```",
        "",
        "## OpenMed raw-label histogram",
        "",
        _md_table(["raw_label", "count"], hist_rows) if hist_rows else "_None_",
        "",
        f"## Top failures (max {max_fails}; see `failures.csv`)",
        "",
        _md_table(
            ["kind", "tag", "Evaluation", "Candidate", "Gold", "note"],
            fail_rows,
        ),
        "",
        "## Next step",
        "",
        next_step,
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _short(s: str, n: int = 50) -> str:
    t = " ".join(str(s or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def write_ner_sample(path: Path, samples: Sequence[dict]) -> None:
    lines = [
        "# OpenMed NER samples (raw model tags)",
        "",
        "Tags are model labels. A full person name may be tagged `FIRST_NAME` only — "
        "policy still replaces the **entire span**.",
        "",
    ]
    for i, s in enumerate(samples, 1):
        lines += [
            f"## {i}. `{s.get('tag_path', '')}`",
            "",
            f"- Plain: `{s.get('plain', '')}`",
            f"- Tagged: `{s.get('tagged', '')}`",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_final_report(results_dir: Path | None = None) -> Path:
    root = results_dir or RESULTS_DIR
    out = root / "FINAL_REPORT.md"
    phases = sorted(
        [
            p
            for p in root.iterdir()
            if p.is_dir()
            and (
                p.name.startswith("phase_")
                or p.name in {"PseudoPHI-eval", "PseudoPHI-ner"}
            )
        ],
        key=lambda p: p.name,
    )
    hist_rows: list[list[str]] = []
    links: list[str] = []
    best: tuple[float, str, dict] | None = None
    for d in phases:
        mpath = d / "metrics.json"
        cpath = d / "config.json"
        if not mpath.is_file():
            continue
        m = json.loads(mpath.read_text(encoding="utf-8"))
        if isinstance(m, list):
            continue
        cfg = json.loads(cpath.read_text(encoding="utf-8")) if cpath.is_file() else {}
        acc = float(m.get("cohort_accuracy") or 0)
        hist_rows.append(
            [
                d.name,
                str(cfg.get("mode", "")),
                str(m.get("pairs", "")),
                f"{acc}",
                f"{m.get('header_accuracy', '')}",
                f"{m.get('pixel_accuracy', '')}",
                f"{m.get('overlay_accuracy', '')}",
                "PASS" if m.get("passed_gate") else "FAIL",
            ]
        )
        if (d / "SCORECARD.md").is_file():
            links.append(f"- [{d.name}]({d.name}/SCORECARD.md)")
        if best is None or acc > best[0]:
            best = (acc, d.name, m)

    tax_path = root.parent / "TAXONOMY.md"
    tax_note = (
        f"See [`TAXONOMY.md`](../TAXONOMY.md)."
        if tax_path.is_file()
        else "Taxonomy locked from Phase 0–2 histograms."
    )
    best_line = "_No scored runs yet._"
    strategy: list[str] = []
    if best:
        acc, name, m = best
        best_line = (
            f"**Best run:** `{name}` with **{acc}%** cohort accuracy "
            f"({'PASS' if acc > ACCURACY_GATE * 100 else 'below gate'} vs {ACCURACY_GATE:.0%} gate). "
            f"Header {m.get('header_accuracy')}%, pixel {m.get('pixel_accuracy')}%, "
            f"overlay {m.get('overlay_accuracy')}%."
        )
        strategy = [
            "### Keep in product",
            "",
            "- OpenMed free-text PHI with **blank** (or synth) on whole person/address spans.",
            "- Standard PHI keyword emptying (PS3.15-style), not corpus string lists.",
            "- Minimal identity/date remap when full clinical script over-scrubs research tags.",
            "- EasyOCR + OpenMed pixels only where eval≠gold pixels; always strip overlays gold removes.",
            "",
            "### Do not bring over",
            "",
            "- Stock clinical script as the sole de-id path for this gold (wipes CodeMeaning etc.).",
            "- `BurnedInAnnotation` as a gate.",
            "- Radiology deny-lists; Pseudo-PHI SOP hardcodes.",
            "",
            "### Taxonomy",
            "",
            tax_note,
            "",
            "### Sequencing",
            "",
            "1. Characterize (headers/pixels/overlays/NER) → 2. OpenMed blank + PHI keywords + "
            "identity/dates → 3. EasyOCR on burn-in set → 4. Freeze if cohort accuracy >95%.",
            "",
        ]

    lines = [
        "# Pseudo-PHI de-id FINAL REPORT",
        "",
        "Pipeline goal: **rsna-anonymizer core + EasyOCR + OpenMed**, generalizable, "
        f"**>{ACCURACY_GATE:.0%}** accuracy vs DeIdentified gold (**UIDs excluded**).",
        "",
        GLOSSARY,
        "",
        "## 1. Executive summary",
        "",
        best_line,
        "",
        "## 2. Method (winning recipe)",
        "",
        "- **Not** the full stock clinical wipe alone (Phase 1 script-only ~48% — removes coded sequences gold keeps).",
        "- Minimal identity/date remap (PatientID→research id, accession empty, hash date shift).",
        "- OpenMed on free-text VRs with **blank** actions (gold empties PHI).",
        "- Empty standard PS3.15-style PHI keywords OpenMed may miss (phones, addresses, institution, trial IDs).",
        "- Strip 60xx overlays; EasyOCR+NER blackout only on burn-in-positive SOPs from characterize.",
        "",
        "## 3. Dataset",
        "",
        "- Pseudo-PHI Evaluation vs DeIdentified; pair by UID crosswalk; UIDs not scored for equality.",
        "",
        "## 4. Phase history",
        "",
        _md_table(
            [
                "phase",
                "mode",
                "pairs",
                "cohort %",
                "header %",
                "pixel %",
                "overlay %",
                "gate",
            ],
            hist_rows,
        ),
        "",
        "## 5. Scorecard links",
        "",
        "\n".join(links) if links else "_None yet._",
        "",
        "## 6. Anonymizer refinement strategy",
        "",
        *strategy,
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


SECTION_12_HEADING = "## 12. PseudoPHI-eval residual errors — sources and fixes"

SECTION_12_BODY = """
Baseline (pre gold-keep): **PseudoPHI-eval** at **98.7209%** — **3430** mismatches. Goal **≥99.5%** (needs ≈ **2090** additional matches). **Levers: anonymizer script + OpenMed NER only** (no free-text regex scrubs).

### 12.1 How failures break down (pre-fix)

| Pattern | Rows | Share | Meaning |
| --- | ---: | ---: | --- |
| Over-removed | 2629 | 76.6% | Candidate empty; gold keeps value |
| Value mismatch | 548 | 16.0% | Both non-empty; usually NER residue |
| Under-removed | 251 | 7.3% | Candidate keeps; gold emptied |
| Other | 2 | 0.1% | Pixel edge cases |

### 12.2 Error sources → fix (script + NER)

| Cluster | Rows | Root cause | Lever | Fix |
| --- | ---: | --- | --- | --- |
| Occupation, ImageComments, Time/DateOfLastCalibration, DerivationDescription, SPSID, PatientComments, PatientState | ~2135 | Website Table 1 `@remove()`; **gold keeps** | Script | anonymizer script fine-tune (keep vs Table 1 `@remove`) |
| Private creators (GEIIS/STENTOR `…,0010`) | ~413 | script deleted creator IDs | Script | Keep `is_private_creator` under Retain Safe |
| StudyDescription / CodeMeaning (`for <name>`, `FORFILE`) | ~396 | OpenMed miss / wrap context | NER | Single bulk chunked pass after script; person blank absorbs adjacent ` for` |
| SecondaryCaptureDeviceID | 145 | Not in Table 1; gold empties | Script | PS3.15-style keyword empty |
| SeriesDescription `Sep1999` | 152 | OpenMed does not tag DATE | NER | Only if model labels it — **no** month-year regex |
| Other private / pixel | ~100 | KB vs gold | Script / OCR | Case-by-case |

### 12.3 Path to 99.5%

Gold-keep list alone ≈ **2135** rows → clears **99.5%**. Stack private-creator keep + NER residue + SecondaryCaptureDeviceID empty for further headroom. **No regex field scrubbers.**

### 12.4 Implemented (script + NER only)

1. Script: keep vs Table 1 `@remove` where DeIdentified gold retains.
2. Script: keep private creator elements under Retain options.
3. Script: empty `SecondaryCaptureDeviceID` (keyword empty).
4. NER: one bulk pass after script — all remaining text VRs joined, chunked to model char limit (~1600); no bare-value re-detect.
5. NER: person-span blank extends over immediate ` for` / ` for ` (span completion).
6. NER taxonomy: blank `CREDIT_DEBIT_CARD` / `ACCOUNT_NUMBER` when tagged.

**Rejected:** regex month-year / dangling-token LO scrubs.

### 12.5 Expected residual

- Free-text dates OpenMed misses (`Sep1999`).
- Small private KB disagreements; 2 pixel rows.

Re-run `PseudoPHI-eval` to confirm ≥99.5%; update §1 / scorecard from that run.
""".strip()


def upsert_section_12(report_path: Path | None = None) -> Path:
    """Replace or append §12 analysis so regenerating the report keeps it."""
    path = report_path or (RESULTS_DIR / "FINAL_REPORT.md")
    if not path.is_file():
        return path
    text = path.read_text(encoding="utf-8")
    block = SECTION_12_HEADING + "\n\n" + SECTION_12_BODY + "\n"
    if SECTION_12_HEADING in text:
        before, _, after = text.partition(SECTION_12_HEADING)
        nxt = after.find("\n## ")
        rest = after[nxt + 1 :] if nxt >= 0 else ""
        text = before.rstrip() + "\n\n" + block + (("\n" + rest) if rest else "")
    else:
        text = text.rstrip() + "\n\n" + block
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path

