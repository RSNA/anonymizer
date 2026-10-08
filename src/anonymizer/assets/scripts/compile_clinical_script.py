#!/usr/bin/env python3
"""Compile clinical-anonymizer.script from default + keep-tags + TCIA private CSV."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_POLICY = _SCRIPTS.parent / "anonymization_policy"
_DEFAULT = _SCRIPTS / "default-anonymizer.script"
_OUT = _SCRIPTS / "clinical-anonymizer.script"
_KEEP = _POLICY / "clinical_text_keep_tags.txt"
_CSV = _POLICY / "tcia_private_tag_kb.csv"

_TAG_HEX = re.compile(r"^[0-9A-Fa-f]{8}$")
_XX_TAG = re.compile(r"^([0-9A-Fa-f]{4})XX([0-9A-Fa-f]{2})$", re.IGNORECASE)


def _load_keep_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        keys.add(text)
        keys.add(text.casefold())
        if _TAG_HEX.match(text):
            keys.add(text.upper())
    return keys


def _flip_keep(root: ET.Element, keep_keys: set[str]) -> int:
    flipped = 0
    for e in root.findall("e"):
        tag = str(e.attrib.get("t", ""))
        name = str(e.attrib.get("n", ""))
        if tag.upper() in keep_keys or name in keep_keys or name.casefold() in keep_keys:
            op = (e.text or "").strip()
            if "@remove" in op or op.startswith("@empty"):
                e.text = ""  # keep
                flipped += 1
    return flipped


def _tcia_operation(action: str) -> str | None:
    a = action.strip().lower()
    if a == "k":
        return ""
    if a == "d":
        return "@remove()"
    if a == "h":
        return "@uid"
    if a == "o":
        return "@hashdate(this,StudyDate)"
    if a == "oi":
        return "@incrementdate(this,0)"
    return None


def _merge_tcia(root: ET.Element, csv_path: Path) -> int:
    added = 0
    if not csv_path.is_file():
        return 0
    existing = {str(e.attrib.get("t", "")).upper() for e in root.findall("e")}
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ge = (row.get("group_element") or "").strip()
            creator = (row.get("creator") or "").strip()
            action = (row.get("action") or "").strip()
            note = (row.get("note") or "").strip()
            if not ge:
                continue
            op = _tcia_operation(action)
            if op is None:
                continue
            tag = ge.upper().replace(",", "")
            if tag in existing:
                continue
            attrib = {"en": "T", "t": tag, "n": note or creator or "Private"}
            if creator:
                attrib["n"] = f"{creator}: {note}" if note else creator
            elem = ET.SubElement(root, "e", attrib)
            elem.text = op
            existing.add(tag)
            added += 1
            # Keep private creator block when XX pattern present.
            m = _XX_TAG.match(tag)
            if m and creator:
                creator_tag = f"{m.group(1)}00XX".upper()
                if creator_tag not in existing:
                    ce = ET.SubElement(
                        root,
                        "e",
                        {"en": "T", "t": creator_tag, "n": f"{creator} (creator)"},
                    )
                    ce.text = ""
                    existing.add(creator_tag)
                    added += 1
    return added


def compile_clinical(*, check: bool = False) -> int:
    if not _DEFAULT.is_file():
        print(f"missing default script: {_DEFAULT}", file=sys.stderr)
        return 2
    keep_keys = _load_keep_keys(_KEEP) if _KEEP.is_file() else set()
    tree = ET.parse(_DEFAULT)
    root = tree.getroot()
    flipped = _flip_keep(root, keep_keys)
    added = _merge_tcia(root, _CSV)
    # Preserve XML declaration style of CTP scripts.
    payload = ET.tostring(root, encoding="unicode")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n' + payload + "\n"
    if check:
        if not _OUT.is_file():
            print(f"missing clinical script: {_OUT}", file=sys.stderr)
            return 1
        current = _OUT.read_text(encoding="utf-8")
        if current != text:
            print("clinical-anonymizer.script is out of date; re-run compiler", file=sys.stderr)
            return 1
        print(f"OK clinical script up to date (flipped={flipped} private_rows={added})")
        return 0
    _OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {_OUT} (flipped_keep={flipped}, private_added={added})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true", help="Diff against committed clinical script")
    args = p.parse_args(argv)
    return compile_clinical(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
