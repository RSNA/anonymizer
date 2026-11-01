"""SCORECARD.md from official MIDI validation scoring artifacts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def _pct(num: float | int, den: float | int) -> str:
    if den <= 0:
        return "n/a"
    return f"{100.0 * float(num) / float(den):.2f}%"


def resolve_validation_results_db(run_dir: Path) -> Path:
    """
    Locate validation_results.db under official_score/.

    Prefers the legacy ``midi_b`` folder (prototyping harness), then a folder
    named like the run directory (eval harness), then any non-empty DB under
    official_score/.

    Args:
        run_dir: Harness run directory.

    Returns:
        Path to validation_results.db.

    Raises:
        FileNotFoundError: When no non-empty DB is found.
    """
    run_dir = Path(run_dir)
    official = run_dir / "official_score"
    candidates = [
        official / "midi_b" / "validation_results.db",
        official / run_dir.name / "validation_results.db",
    ]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    if official.is_dir():
        found = sorted(
            p
            for p in official.rglob("validation_results.db")
            if p.is_file() and p.stat().st_size > 0
        )
        if found:
            return found[0]
    raise FileNotFoundError(
        f"missing/empty validation_results.db under {official}"
    )


def resolve_scoring_report_xlsx(run_dir: Path) -> Path | None:
    """
    Locate scoring_report_instance.xlsx written by the MIDI validation reports.

    Args:
        run_dir: Harness run directory.

    Returns:
        Path to the workbook, or None when missing.
    """
    run_dir = Path(run_dir)
    official = run_dir / "official_score"
    candidates = [
        official / "midi_b" / "scoring_report_instance.xlsx",
        official / run_dir.name / "scoring_report_instance.xlsx",
    ]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    if official.is_dir():
        found = sorted(
            p
            for p in official.rglob("scoring_report_instance.xlsx")
            if p.is_file() and p.stat().st_size > 0
        )
        if found:
            return found[0]
    return None


def read_official_score(scoring_xlsx: Path) -> str:
    """
    Read the official MIDI validation Score from the Scoring sheet.

    This is Pass / Total as written by MIDI_validation_script reports_helper
    scoring_report() (formatted like ``98.54%``).

    Args:
        scoring_xlsx: Path to scoring_report_instance.xlsx.

    Returns:
        Score string from the All / Total row (e.g. ``98.54%``).

    Raises:
        ValueError: When the Scoring sheet has no Score column or no rows.
    """
    df = pd.read_excel(scoring_xlsx, sheet_name="Scoring")
    if "Score" not in df.columns or df.empty:
        raise ValueError(f"no Score column in Scoring sheet: {scoring_xlsx}")
    # Prefer the All category row; else the first row (instance-based report).
    if "Category" in df.columns:
        all_rows = df[df["Category"].astype(str).str.strip().str.lower() == "all"]
        if not all_rows.empty:
            return str(all_rows.iloc[0]["Score"]).strip()
    return str(df.iloc[0]["Score"]).strip()


def write_score_report(
    run_dir: Path,
    *,
    title: str | None = None,
    out_name: str = "SCORECARD.md",
) -> Path:
    """
    Write a scorecard markdown file from official scoring artifacts.

    The Final score line is the MIDI validation Scoring-report ``Score`` only
    (Pass / Total). Breakdown tables still come from validation_results.db for
    triage; they are not alternate overall metrics.

    Args:
        run_dir: Harness run directory containing official_score/.
        title: Optional document title.
        out_name: Output filename under run_dir.

    Returns:
        Path to the written SCORECARD.

    Raises:
        FileNotFoundError: When validation_results.db is missing or empty, or
            when scoring_report_instance.xlsx (required for Final score) is
            missing.
        ValueError: When the Scoring sheet has no Score value.
    """
    run_dir = Path(run_dir)
    db = resolve_validation_results_db(run_dir)
    scoring_xlsx = resolve_scoring_report_xlsx(run_dir)
    if scoring_xlsx is None:
        raise FileNotFoundError(
            f"missing scoring_report_instance.xlsx under {run_dir / 'official_score'}"
        )
    official_score = read_official_score(scoring_xlsx)

    con = sqlite3.connect(str(db))
    try:
        by_action = con.execute(
            """
            SELECT action,
                   SUM(CASE WHEN check_passed = 1 THEN 1 ELSE 0 END) AS pass,
                   SUM(CASE WHEN check_passed = 0 THEN 1 ELSE 0 END) AS fail,
                   COUNT(*) AS tot
            FROM validation_results
            GROUP BY action
            ORDER BY fail DESC
            """
        ).fetchall()

        action_details: list[str] = []
        for action, _p, fail, tot in by_action:
            if fail <= 0:
                continue
            rows = con.execute(
                """
                SELECT tag_ds, tag_name, COUNT(*) AS fails
                FROM validation_results
                WHERE action = ? AND check_passed = 0
                GROUP BY tag_ds, tag_name
                ORDER BY fails DESC
                LIMIT 12
                """,
                (action,),
            ).fetchall()
            lines = [
                f"### `{action}` — {fail} fails / {tot} ({_pct(fail, tot)} fail rate)",
                "",
                "| Tag | Name | Fails |",
                "|---|---|---:|",
            ]
            for tag_ds, tag_name, fails in rows:
                lines.append(f"| `{tag_ds}` | {tag_name} | {fails} |")
            action_details.append("\n".join(lines))
    finally:
        con.close()

    heading = title or f"MIDI-B scorecard — `{run_dir.name}`"
    parts = [
        f"# {heading}",
        "",
        f"**Final score: {official_score}**",
        "",
        "Official MIDI validation `Score` (Pass / Total) from "
        f"`{scoring_xlsx.name}` Scoring sheet.",
        "",
        "## By action",
        "",
        "| Action | Pass | Fail | Total | Fail % |",
        "|---|---:|---:|---:|---:|",
    ]
    sum_pass = 0
    sum_fail = 0
    sum_tot = 0
    for _action, p, f, tot in by_action:
        sum_pass += int(p or 0)
        sum_fail += int(f or 0)
        sum_tot += int(tot or 0)
    # Fail % = fails in this action / all checks (a fail anywhere is a fail).
    for action, p, f, tot in by_action:
        parts.append(
            f"| `{action}` | {p} | {f} | {tot} | {_pct(f, sum_tot)} |"
        )
    parts.append(
        f"| **Total** | **{sum_pass}** | **{sum_fail}** | **{sum_tot}** | "
        f"**{_pct(sum_fail, sum_tot)}** |"
    )
    if action_details:
        parts.extend(["", "## Top failing tags by action", ""])
        parts.append("\n\n".join(action_details))
    out = run_dir / out_name
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out
