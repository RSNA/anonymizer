"""Convert official TCIAPrivateTagKB-*-formatted.csv → tcia_kb_data.py.

Public API
----------
flatten_official_kb(src: Path) -> list[dict[str, str]]
    Collapse the official formatted KB CSV to in-memory rows.

write_generated_module(rows: list[dict[str, str]], src_name: str, out_module: Path) -> int
    Emit the runtime lookup-dict module for flattened KB rows.

main() -> None
    Run official CSV → generated module from CLI arguments.
"""
import argparse
import csv
import re
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_DEFAULT_SRC = (
    _PKG.parents[1]
    / "assets"
    / "tcia_kb"
    / "TCIAPrivateTagKB-02-01-2024-formatted.csv"
)
_DEFAULT_MODULE_OUT = _PKG / "tcia_kb_data.py"

# Terminal private element: (gggg,"creator",ee) or (gggg,,ee); ee = 2 hex digits.
_TERM = re.compile(
    r"\((?P<g>[0-9a-fA-F]{4}),(?P<creator>(?:\"(?:[^\"]|\"\")*\"|[^,]*)),(?P<e>[0-9a-fA-F]{2})\)$"
)

# MIDI-B / curated answer-key fine-tunes: official CSV has only d but the
# challenge labels the tag TCIA-PTKB-K (keep). Key = (group_element, creator).
_MIDI_KEEP_OVERRIDES: dict[tuple[str, str], str] = {
    ("0009XX0F", "gems_petd_01"): "k",  # Scan Description
}

# Letter → enum member name written into the generated module. o and oi
# both become DATE_DELTA.
_ACTION_TO_NAME: dict[str, str] = {
    "k": "KEEP",
    "d": "REMOVE",
    "h": "UID",
    "o": "DATE_DELTA",
    "oi": "DATE_DELTA",
}
# Build-time priority: transform before keep before remove (same order as
# collapse_retain_safe_action).
_ACTION_PRIORITY: tuple[str, ...] = ("o", "h", "k", "d")


def _parse_creator(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text.replace('""', '"').strip().strip('"')


def _normalize_action_letter(raw: str) -> str | None:
    """
    Normalize a TCIA private_disposition letter to k/d/h/o.

    Args:
        raw: TCIA action letter from the source CSV.

    Returns:
        Normalized letter, or None for blank / na / unknown letters.
    """
    letter = (raw or "").strip().lower()
    if letter not in _ACTION_TO_NAME:
        return None
    if letter == "oi":
        return "o"
    return letter


def _action_beats(candidate: str, incumbent: str) -> bool:
    """
    True when candidate should replace incumbent under Retain Safe.

    Args:
        candidate: Normalized action letter.
        incumbent: Normalized action letter already stored.

    Returns:
        True when candidate has higher priority (earlier in _ACTION_PRIORITY).
    """
    try:
        return _ACTION_PRIORITY.index(candidate) < _ACTION_PRIORITY.index(incumbent)
    except ValueError:
        return False


def flatten_official_kb(src: Path) -> list[dict[str, str]]:
    """
    Collapse the official formatted KB CSV to in-memory rows.

    Args:
        src: Official formatted CSV path.

    Returns:
        Flattened rows with group_element, creator, action, vr, note.
    """
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
            action = _normalize_action_letter(disp)
            if action is None:
                continue
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
            if prev is None or _action_beats(action, prev["action"]):
                best[key] = row

    for (ge, creator_cf), action_letter in _MIDI_KEEP_OVERRIDES.items():
        key = (ge, creator_cf)
        if key in best:
            best[key] = {**best[key], "action": action_letter}
        else:
            best[key] = {
                "group_element": ge,
                "creator": "GEMS_PETD_01",
                "action": action_letter,
                "vr": "",
                "note": "MIDI-B keep override",
            }

    rows = sorted(best.values(), key=lambda r: (r["group_element"], r["creator"].casefold()))
    print(f"Flattened {len(rows)} rows from {src.name} (skipped {skipped} nested/non-private sigs)")
    return rows


def write_generated_module(rows: list[dict[str, str]], src_name: str, out_module: Path) -> int:
    """
    Emit the runtime lookup-dict module for flattened KB rows.

    Args:
        rows: Flattened KB rows (group_element is GGGGXXEE).
        src_name: Official KB filename recorded as provenance.
        out_module: Generated Python module path.

    Returns:
        Number of creator-exact entries written.
    """
    entries: dict[tuple[str, int, int], tuple[str, str, str, str]] = {}
    fallback: dict[tuple[int, int], tuple[str, str, str, str]] = {}
    for row in rows:
        ge = row["group_element"].upper()
        group = int(ge[:4], 16)
        suffix = int(ge[6:], 16)
        letter = _normalize_action_letter(row["action"])
        if letter is None:
            continue
        action_name = _ACTION_TO_NAME[letter]
        value = (row["creator"], action_name, row["vr"], row["note"])
        entries[(row["creator"].casefold(), group, suffix)] = value
        slot = (group, suffix)
        incumbent = fallback.get(slot)
        if incumbent is None or (not value[0] and incumbent[0]):
            fallback[slot] = value

    lines = [
        f'"""GENERATED by convert_tcia_private_kb.py from {src_name}. Do not edit.\n'
        "\n"
        "Public API\n"
        "----------\n"
        "KB_SOURCE — source CSV basename used to build this module\n"
        "PrivateTagAction — knowledge-base action StrEnum (k / d / h / o)\n"
        "PrivateTagEntry — one knowledge-base row (creator, action, vr, note)\n"
        "PRIVATE_KB — (creator_casefold, group, element_suffix) → PrivateTagEntry\n"
        "PRIVATE_KB_FALLBACK — (group, element_suffix) → PrivateTagEntry\n"
        "\n"
        "Consumers look up via private_tags.lookup_private_tag; do not edit by hand.\n"
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from enum import StrEnum",
        "from typing import NamedTuple",
        "",
        f"KB_SOURCE = {src_name!r}",
        "",
        "",
        "class PrivateTagAction(StrEnum):",
        '    """TCIA private-tag knowledge-base action letter."""',
        "",
        '    KEEP = "k"',
        '    REMOVE = "d"',
        '    UID = "h"',
        '    DATE_DELTA = "o"',
        "",
        "",
        "class PrivateTagEntry(NamedTuple):",
        '    """One knowledge-base row stored in PRIVATE_KB."""',
        "",
        "    creator: str",
        "    action: PrivateTagAction",
        "    vr: str",
        "    note: str",
        "",
        "    @property",
        "    def display_name(self) -> str:",
        '        """Label creator: note, or whichever part is non-empty."""',
        "        if self.creator and self.note:",
        '            return f"{self.creator}: {self.note}"',
        "        if self.creator:",
        "            return self.creator",
        "        if self.note:",
        "            return self.note",
        '        return ""',
        "",
        "",
        "# (creator casefold, group, element suffix) -> PrivateTagEntry",
        "PRIVATE_KB: dict[tuple[str, int, int], PrivateTagEntry] = {",
    ]
    for key in sorted(entries):
        creator, action_name, vr, note = entries[key]
        lines.append(
            f"    {key!r}: PrivateTagEntry({creator!r}, PrivateTagAction.{action_name}, {vr!r}, {note!r}),"
        )
    lines.append("}")
    lines.append("")
    lines.append(
        "# (group, element suffix) -> PrivateTagEntry; creator-less row, else first creator"
    )
    lines.append("PRIVATE_KB_FALLBACK: dict[tuple[int, int], PrivateTagEntry] = {")
    for key in sorted(fallback):
        creator, action_name, vr, note = fallback[key]
        lines.append(
            f"    {key!r}: PrivateTagEntry({creator!r}, PrivateTagAction.{action_name}, {vr!r}, {note!r}),"
        )
    lines.append("}")
    out_module.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(entries)} entries → {out_module}")
    return len(entries)


def main() -> None:
    """Run official CSV → generated module from CLI arguments."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=_DEFAULT_SRC)
    p.add_argument("--out-module", type=Path, default=_DEFAULT_MODULE_OUT)
    args = p.parse_args()
    if not args.src.is_file():
        raise SystemExit(f"Missing official KB: {args.src}")
    rows = flatten_official_kb(args.src)
    write_generated_module(rows, args.src.name, args.out_module)


if __name__ == "__main__":
    main()
