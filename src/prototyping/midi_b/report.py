"""Failure / score reports from official MIDI validation_results.db."""

import sqlite3
from pathlib import Path


def _pct(num: int, den: int) -> str:
    if den <= 0:
        return "n/a"
    return f"{100.0 * num / den:.2f}%"


def write_score_report(
    run_dir: Path,
    *,
    title: str | None = None,
    out_name: str = "SCORECARD.md",
) -> Path:
    """Write a PseudoPHI-style scorecard from official scoring artifacts."""
    run_dir = Path(run_dir)
    db = run_dir / "official_score" / "midi_b" / "validation_results.db"
    if not db.is_file() or db.stat().st_size == 0:
        raise FileNotFoundError(f"missing/empty validation DB: {db}")

    con = sqlite3.connect(str(db))
    try:
        total = con.execute("SELECT COUNT(*) FROM validation_results").fetchone()[0]
        passed = con.execute(
            "SELECT COUNT(*) FROM validation_results WHERE check_passed = 1"
        ).fetchone()[0]
        failed = con.execute(
            "SELECT COUNT(*) FROM validation_results WHERE check_passed = 0"
        ).fetchone()[0]

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

        # Category columns may be missing on older DBs.
        cols = {r[1] for r in con.execute("PRAGMA table_info(validation_results)")}
        cat_blocks: list[str] = []
        for col, label in (
            ("tcia_ptkb", "TCIA private KB"),
            ("dicom_iod", "DICOM IOD"),
            ("tcia_rev", "TCIA review"),
            ("hipaa_z", "HIPAA"),
        ):
            if col not in cols:
                continue
            rows = con.execute(
                f"""
                SELECT COALESCE({col}, ''),
                       SUM(CASE WHEN check_passed = 0 THEN 1 ELSE 0 END) AS fail,
                       COUNT(*) AS tot
                FROM validation_results
                GROUP BY 1
                HAVING fail > 0
                ORDER BY fail DESC
                LIMIT 15
                """
            ).fetchall()
            if not rows:
                continue
            lines = [f"### {label}", "", "| Category | Fail | Total | Fail % |", "|---|---:|---:|---:|"]
            for cat, fail, tot in rows:
                lines.append(
                    f"| `{cat or '(empty)'}` | {fail} | {tot} | {_pct(fail, tot)} |"
                )
            cat_blocks.append("\n".join(lines))

        # Per-action top failing tags
        action_details: list[str] = []
        for action, _p, fail, tot in by_action:
            if not fail:
                continue
            top = con.execute(
                """
                SELECT tag_ds, tag_name,
                       SUM(CASE WHEN file_value IS NULL OR file_value = '' OR file_value = 'None'
                                THEN 1 ELSE 0 END) AS missing,
                       COUNT(*) AS n
                FROM validation_results
                WHERE action = ? AND check_passed = 0
                GROUP BY tag_ds, tag_name
                ORDER BY n DESC
                LIMIT 12
                """,
                (action,),
            ).fetchall()
            lines = [
                f"### `{action}` — {fail} fails / {tot} ({_pct(fail, tot)} fail rate)",
                "",
                "| Tag | Name | Fails | Of which missing/null |",
                "|---|---|---:|---:|",
            ]
            for tag_ds, tag_name, missing, n in top:
                lines.append(
                    f"| `{tag_ds}` | {tag_name or ''} | {n} | {missing} |"
                )
            # Sample mismatches (non-null file_value)
            samples = con.execute(
                """
                SELECT tag_ds, tag_name, action_text, file_value, patient
                FROM validation_results
                WHERE action = ? AND check_passed = 0
                  AND file_value IS NOT NULL AND file_value != '' AND file_value != 'None'
                LIMIT 8
                """,
                (action,),
            ).fetchall()
            if samples:
                lines += ["", "Sample value mismatches (expected token → got):", ""]
                for tag_ds, tag_name, exp, got, pat in samples:
                    lines.append(
                        f"- patient `{pat}` `{tag_ds}` {tag_name}: "
                        f"expect `{_short(exp)}` got `{_short(got)}`"
                    )
            action_details.append("\n".join(lines))

        # Missing-vs-mismatch for text_retained
        tr_miss = con.execute(
            """
            SELECT COUNT(*) FROM validation_results
            WHERE action = '<text_retained>' AND check_passed = 0
              AND (file_value IS NULL OR file_value = '' OR file_value = 'None')
            """
        ).fetchone()[0]
        tr_fail = next((f for a, _p, f, _t in by_action if a == "<text_retained>"), 0)

    finally:
        con.close()

    xlsx = run_dir / "scoring_report_instance.xlsx"
    if not xlsx.is_file():
        alt = run_dir / "official_score" / "midi_b" / "scoring_report_instance.xlsx"
        if alt.is_file():
            xlsx = alt

    title = title or f"SCORECARD — {run_dir.name}"
    parts = [
        f"# {title}",
        "",
        f"**Run:** `{run_dir}`",
        f"**Overall:** **{_pct(passed, total)}** pass "
        f"({passed:,} / {total:,}; fails {failed:,})",
        "",
        f"Official report: `{xlsx}`" if xlsx.is_file() else "",
        "",
        "## By action",
        "",
        "| Action | Pass | Fail | Total | Pass % |",
        "|---|---:|---:|---:|---:|",
    ]
    for action, p, f, t in by_action:
        parts.append(f"| `{action}` | {p:,} | {f:,} | {t:,} | {_pct(p, t)} |")

    if tr_fail:
        parts += [
            "",
            "## `text_retained` split",
            "",
            f"- Missing/null tag: **{tr_miss:,}** ({_pct(tr_miss, tr_fail)} of these fails)",
            f"- Present but token mismatch: **{tr_fail - tr_miss:,}**",
        ]

    if cat_blocks:
        parts += ["", "## Failures by answer category", ""] + [
            b + "\n" for b in cat_blocks
        ]

    parts += ["", "## Top failing tags by action", ""] + [
        d + "\n" for d in action_details
    ]

    out = run_dir / out_name
    out.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return out


def _short(v: object, n: int = 100) -> str:
    s = str(v or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"
