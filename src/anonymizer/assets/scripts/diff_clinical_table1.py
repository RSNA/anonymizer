#!/usr/bin/env python3
"""Reference diff: clinical-anonymizer.script vs TCIA Overview Table 1 CSV.

Clinical policy is the script. This tool only lists where the script diverges
from the website Table 1 seed — it does not validate or regenerate the script.
"""

from __future__ import annotations

import argparse
import csv
import xml.etree.ElementTree as ET
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.metadata.process_private_tags_tcia import (
    clinical_dateinc_days,
    incrementdate_operand,
)

_SCRIPTS = Path(__file__).resolve().parent
_POLICY = _SCRIPTS.parent / "anonymization_policy"
_CLINICAL = _SCRIPTS / "clinical-anonymizer.script"
_TABLE1 = _POLICY / "tcia_table1_ctp_ops.csv"
_DATEINC_FILE = _POLICY / "clinical_dateinc.txt"


def map_tcia_table1_ctp(ctp_script: str, *, dateinc: int | None = None) -> str | None:
    """Map a TCIA Overview Table 1 CTP cell → product operand (or None to skip)."""
    raw = (ctp_script or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low in {"@remove()", "removed"} or low.startswith("remove "):
        return "@remove()"
    if low in {"@keep()", "@keep"}:
        return ""
    if low == "@empty()":
        return "@empty()"
    if low == "@process()":
        return "@process()"
    if low.startswith("@incrementdate"):
        return incrementdate_operand(dateinc)
    if low.startswith("@hashuid"):
        return "@uid"
    if low.startswith("lookup"):
        return "@ptid"
    if "hashname" in low:
        return "@empty()"
    if "private attributes" in low or "posda" in low:
        return None
    return None


def diff_vs_table1(
    script_path: Path = _CLINICAL,
    table_path: Path = _TABLE1,
    *,
    dateinc: int | None = None,
) -> list[str]:
    """List script ops that differ from the Table 1 CSV (reference only)."""
    if not script_path.is_file() or not table_path.is_file():
        return ["missing script or table1 csv"]
    days = clinical_dateinc_days(str(_DATEINC_FILE)) if dateinc is None else dateinc
    root = ET.parse(script_path).getroot()
    by_tag = {
        str(e.attrib.get("t", "")).upper(): (e.text or "").strip()
        for e in root.findall("e")
        if e.attrib.get("t")
    }
    keep_like = ("", "@keep", "@keep()", "@safe", "@safe()")
    msgs: list[str] = []
    with table_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            ge = (row.get("group_element") or "").strip().upper()
            name = (row.get("attribute_name") or "").strip()
            seeded = map_tcia_table1_ctp(row.get("ctp_script") or "", dateinc=days)
            if seeded is None or not ge:
                continue
            actual = by_tag.get(ge)
            if actual is None:
                msgs.append(f"{ge} {name}: missing (Table 1 seed {seeded!r})")
                continue
            if actual in ("@safe()", "@safe") and seeded in ("", "@keep", "@keep()"):
                msgs.append(f"{ge} {name}: @safe() (Table 1 keep)")
                continue
            if actual in keep_like and seeded in ("", "@keep", "@keep()"):
                continue
            if actual == seeded:
                continue
            if seeded.startswith("@incrementdate") and actual.startswith("@incrementdate"):
                continue
            if seeded == "@hashdate" and actual.startswith("@hashdate"):
                continue
            msgs.append(f"{ge} {name}: script {actual!r} vs Table 1 seed {seeded!r}")
    return msgs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--script",
        type=Path,
        default=_CLINICAL,
        help="Clinical script path (default: packaged clinical-anonymizer.script)",
    )
    p.add_argument(
        "--table1",
        type=Path,
        default=_TABLE1,
        help="Table 1 CSV path",
    )
    args = p.parse_args(argv)
    msgs = diff_vs_table1(args.script, args.table1)
    print(f"Table 1 reference diffs: {len(msgs)}")
    for m in msgs:
        print(f"  {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
