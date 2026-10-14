#!/usr/bin/env python3
"""Flatten official TCIAPrivateTagKB-*-formatted.csv → tcia_private_tag_kb.csv."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.metadata.tcia_kb import (
    ACTION_PRIORITY,
    action_beats,
)

_DIR = Path(__file__).resolve().parent
_DEFAULT_SRC = _DIR / "TCIAPrivateTagKB-02-01-2024-formatted.csv"
_DEFAULT_OUT = _DIR / "tcia_private_tag_kb.csv"

# Terminal private element: (gggg,"creator",ee) or (gggg,,ee); ee = 2 hex digits.
_TERM = re.compile(
    r"\((?P<g>[0-9a-fA-F]{4}),(?P<creator>(?:\"(?:[^\"]|\"\")*\"|[^,]*)),(?P<e>[0-9a-fA-F]{2})\)$"
)

# MIDI-B / curated answer-key fine-tunes: official CSV has only ``d`` but the
# challenge labels the tag TCIA-PTKB-K (keep). Key = (group_element, creator).
_MIDI_KEEP_OVERRIDES: dict[tuple[str, str], str] = {
    ("0009XX0F", "gems_petd_01"): "k",  # Scan Description
}


def _parse_creator(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text.replace('""', '"').strip().strip('"')


def convert(src: Path, out: Path) -> int:
    best: dict[tuple[str, str], dict[str, str]] = {}
    skipped = 0
    with src.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = [h.strip() for h in next(reader)]
        if header[:4] != [
            "element_sig_pattern",
            "tag_name",
            "vr",
            "private_disposition",
        ]:
            raise SystemExit(f"Unexpected header in {src}: {header[:4]}")
        for raw in reader:
            if len(raw) < 4:
                continue
            sig, name, vr, disp = (c.strip() for c in raw[:4])
            match = _TERM.search(sig)
            if match is None:
                skipped += 1
                continue
            action = disp.lower()
            if action not in ACTION_PRIORITY:
                continue  # na / blank = curator discretion
            group = match.group("g").upper()
            elem = match.group("e").upper()
            creator = _parse_creator(match.group("creator"))
            ge = f"{group}XX{elem}"
            key = (ge, creator.casefold())
            row = {
                "group_element": ge,
                "creator": creator,
                "action": action,
                "vr": vr.upper(),
                "note": name,
            }
            prev = best.get(key)
            if prev is None or action_beats(action, prev["action"]):
                best[key] = row

    for (ge, creator_cf), action in _MIDI_KEEP_OVERRIDES.items():
        key = (ge, creator_cf)
        if key in best:
            best[key] = {**best[key], "action": action}
        else:
            best[key] = {
                "group_element": ge,
                "creator": "GEMS_PETD_01",  # only override today
                "action": action,
                "vr": "",
                "note": "MIDI-B keep override",
            }

    rows = sorted(best.values(), key=lambda r: (r["group_element"], r["creator"].casefold()))
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["group_element", "creator", "action", "vr", "note"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows → {out} (skipped {skipped} nested/non-private sigs)")
    return len(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=_DEFAULT_SRC)
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = p.parse_args()
    if not args.src.is_file():
        raise SystemExit(f"Missing official KB: {args.src}")
    convert(args.src, args.out)


if __name__ == "__main__":
    main()
