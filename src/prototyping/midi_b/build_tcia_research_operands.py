"""Regenerate tcia_research_operands.json from the MIDI-B Validation answer key.

Usage:
  uv run --group midi-b python -m prototyping.midi_b.build_tcia_research_operands

Writes:
  src/anonymizer/controller/script/tcia_research_operands.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from anonymizer.controller.script.compile import (
    CLINICAL_TRIAL_SPONSOR_NAME_TAG,
    compile_script,
    normalize_script_operation,
)
from anonymizer.controller.script.operands import is_remove_operation
from anonymizer.controller.script.retain_option_tags import (
    patient_age_tag,
    product_device_identity_extra_tags,
)
from anonymizer.utils.dicom import DeidMethodCode
from prototyping.midi_b.paths import DEFAULT_ANSWER_KEY_VALIDATION

_TAG_RE = re.compile(r"\(([0-9a-fA-F]{4}),([0-9a-fA-F]{4})\)")
_ANONYMIZER_SRC = Path(__file__).resolve().parents[2] / "anonymizer"
_OPERANDS_PATH = (
    _ANONYMIZER_SRC / "controller" / "script" / "tcia_research_operands.json"
)
_DEFAULT_SCRIPT = _ANONYMIZER_SRC / "assets" / "scripts" / "default-anonymizer.script"

# Basic + retain-at-ingest options except TCIA Research, Device Identity, and
# Full Dates (mutually exclusive with Modified Dates). Device Identity stays
# out so MIDI-B / current TCIA stacks leave serial and station removed; product
# manufacturer / model / software extras are injected as @safe() below.
_BASELINE_OPTIONS: frozenset[DeidMethodCode] = frozenset(
    {
        DeidMethodCode.BASIC,
        DeidMethodCode.MODIFIED_DATES,
        DeidMethodCode.PATIENT_CHARACTERISTICS,
        DeidMethodCode.RETAIN_UIDS,
        DeidMethodCode.SAFE_PRIVATE,
        DeidMethodCode.INSTITUTION_IDENTITY,
    }
)

_TCIA_DEVICE_EXTRA_OPERAND = "@safe()"


def _is_remove_or_empty(operation: str | None) -> bool:
    """True when the script operation removes the attribute or empties its value."""
    op = normalize_script_operation(operation)
    return is_remove_operation(op) or op.startswith("@empty")


def build_operands(
    *,
    answer_key: Path,
    base_script: Path,
) -> dict:
    """
    Build the committed TCIA Research operand catalog payload.

    Public tags that appear in the answer key and remain @remove or @empty after
    compiling Basic plus retain-at-ingest options (except TCIA Research and
    Device Identity) become @keep candidates, except:

    - <text_removed> where value equals action_text (whole value must be
      blank/absent), and
    - any <date_shifted> check (source date/time must not remain; do not @keep).

    Product device-identity extras (Manufacturer, model, software versions, and
    secondary-capture equivalents) are always set to @safe() so they remain when
    Retain Device Identity is off.

    Args:
        answer_key: MIDI-B Validation answer key SQLite DB.
        base_script: Packaged default anonymizer script.

    Returns:
        JSON-serializable catalog with an operands map.
    """
    ak_tags: set[str] = set()
    # <text_removed> where value == action_text: whole source value is the
    # removal target (empty or absent). Partial-string removals differ and stay.
    whole_value_text_removed: set[str] = set()
    # <date_shifted>: original date/time string must not remain in the output.
    date_shifted_tags: set[str] = set()
    n_rows = 0
    con = sqlite3.connect(str(answer_key))
    try:
        for (blob,) in con.execute("SELECT AnswerData FROM answer_data"):
            n_rows += 1
            for entry in json.loads(blob).values():
                if not isinstance(entry, dict):
                    continue
                tag_ds = str(entry.get("tag_ds") or entry.get("tag") or "")
                public_elems = [
                    f"{group_hex.upper()}{elem_hex.upper()}"
                    for group_hex, elem_hex in _TAG_RE.findall(tag_ds)
                    if int(group_hex, 16) % 2 == 0
                ]
                if not public_elems:
                    continue
                for tag in public_elems:
                    ak_tags.add(tag)
                leaf = public_elems[-1]
                action = str(entry.get("action") or "")
                if (
                    action == "<text_removed>"
                    and entry.get("value") == entry.get("action_text")
                ):
                    whole_value_text_removed.add(leaf)
                if action == "<date_shifted>":
                    date_shifted_tags.add(leaf)
    finally:
        con.close()

    excluded = whole_value_text_removed | date_shifted_tags
    compiled = compile_script(_BASELINE_OPTIONS, base_script)
    ops = {
        rule.tag.upper(): normalize_script_operation(rule.operation)
        for rule in compiled.rules
    }
    operands: dict[str, str] = {
        tag: "@keep"
        for tag in sorted(ak_tags)
        if tag in ops
        and _is_remove_or_empty(ops[tag])
        and tag not in excluded
    }
    for tag in product_device_identity_extra_tags():
        if tag in ops:
            operands[tag] = _TCIA_DEVICE_EXTRA_OPERAND
    if CLINICAL_TRIAL_SPONSOR_NAME_TAG in ops:
        operands[CLINICAL_TRIAL_SPONSOR_NAME_TAG] = _TCIA_DEVICE_EXTRA_OPERAND
    age = patient_age_tag()
    if age in ops:
        operands[age] = "@keep"

    return {
        "source": "MIDI-B Synthetic Validation Answer Key",
        "answer_key_filename": answer_key.name,
        "baseline_options": sorted(code.name for code in _BASELINE_OPTIONS),
        "selection": (
            "Public tags that appear in the Validation answer key and remain "
            "@remove or @empty after Basic plus retain-at-ingest options "
            "(Modified Dates, Patient Characteristics, Retain UIDs, Safe Private, "
            "Institution Identity) — without Retain Device Identity — excluding "
            "tags with a <text_removed> check where value equals action_text "
            "(whole attribute is the removal target) or any <date_shifted> check "
            "(source date/time must not remain). Product manufacturer / model / "
            "software device tags and Clinical Trial Sponsor Name are always "
            "@safe() so they stay when Retain Device Identity is off / Clean "
            "Descriptors does not blank grant codes. Patient Age is always "
            "@keep (overrides Basic @round). Retain TCIA Research sets listed "
            "tags to their catalog operand when they are still @remove, @empty, "
            "or @round after other selected options."
        ),
        "n_answer_instances": n_rows,
        "n_whole_value_text_removed_excluded": len(whole_value_text_removed & ak_tags),
        "n_date_shifted_excluded": len(date_shifted_tags & ak_tags),
        "n_operands": len(operands),
        "operands": dict(sorted(operands.items())),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry: regenerate the committed operand JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--answer-key",
        type=Path,
        default=DEFAULT_ANSWER_KEY_VALIDATION,
        help="MIDI-B Validation answer key DB",
    )
    parser.add_argument(
        "--base-script",
        type=Path,
        default=_DEFAULT_SCRIPT,
        help="Packaged default anonymizer script",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_OPERANDS_PATH,
        help="Output JSON path",
    )
    args = parser.parse_args(argv)
    if not args.answer_key.is_file():
        raise SystemExit(f"answer key not found: {args.answer_key}")
    if not args.base_script.is_file():
        raise SystemExit(f"base script not found: {args.base_script}")
    payload = build_operands(
        answer_key=args.answer_key,
        base_script=args.base_script,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} n_operands={payload['n_operands']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
