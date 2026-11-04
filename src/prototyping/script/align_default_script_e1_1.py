"""Align packaged default-anonymizer.script to DICOM PS3.15 Table E.1-1 Basic.

Usage:
  uv run python -m prototyping.script.align_default_script_e1_1

Reads:
  src/anonymizer/controller/script/e1_1_basic_profile.json
  src/anonymizer/assets/scripts/default-anonymizer.script

Writes:
  src/anonymizer/assets/scripts/default-anonymizer.script
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from anonymizer.controller.script.compile import (
    DESCRIPTOR_KEEP_TAGS,
    normalize_script_operation,
)
from anonymizer.controller.script.document import (
    ScriptDocument,
    ScriptRule,
    load_script_rules,
    write_script_rules,
)

_ANONYMIZER_SRC = Path(__file__).resolve().parents[2] / "anonymizer"
_BASIC_PROFILE_PATH = (
    _ANONYMIZER_SRC / "controller" / "script" / "e1_1_basic_profile.json"
)
_DEFAULT_SCRIPT = _ANONYMIZER_SRC / "assets" / "scripts" / "default-anonymizer.script"

# Product Patient Age band even when Basic Profile lists X.
_AGE_ROUND_TAG = "00101010"


def is_packaged_script_e1_1_tag(tag: str) -> bool:
    """
    True when an E.1-1 tag belongs in the packaged default script.

    Skips CTP-style XX / GGGGEEEE wildcards and odd (private) groups — those
    are not matched by this product; private tags use the TCIA KB at import.

    Args:
        tag: E.1-1 attribute id (eight hex or a wildcard placeholder).

    Returns:
        True for real eight-hex even-group public tags.
    """
    key = str(tag or "").strip().upper()
    if len(key) != 8 or any(c not in "0123456789ABCDEF" for c in key):
        return False
    return int(key[:4], 16) % 2 == 0


def _basic_letters(basic: str) -> list[str]:
    """
    Split a Basic Profile action code into ordered letters.

    Args:
        basic: E.1-1 Basic column (e.g. X/Z/D, U*).

    Returns:
        Letters without trailing markers (U* -> U).
    """
    parts: list[str] = []
    for raw in str(basic or "").replace(" ", "").split("/"):
        if not raw:
            continue
        letter = raw.rstrip("*")
        if letter and letter not in parts:
            parts.append(letter)
    return parts


def mapped_operand(basic: str) -> str:
    """
    Map E.1-1 Basic action to a script operand (mapping A).

    Preference for mixtures: X then Z then D then U.

    Args:
        basic: E.1-1 Basic Profile action code.

    Returns:
        Script operation text.

    Raises:
        ValueError: When basic has no supported letter.
    """
    letters = _basic_letters(basic)
    if "X" in letters:
        return "@remove()"
    if "Z" in letters:
        return "@empty()"
    if "D" in letters:
        return "@empty()"
    if "U" in letters:
        return "@uid"
    if "C" in letters or "K" in letters:
        return "@keep"
    raise ValueError(f"unsupported Basic action: {basic!r}")


def _remap_compatible(operation: str, basic: str) -> bool:
    """
    True when a product remap may stay for this Basic action.

    Args:
        operation: Current script operation.
        basic: E.1-1 Basic Profile action code.

    Returns:
        True when the remap is allowed under Z/D/U for this tag.
    """
    op = normalize_script_operation(operation)
    letters = set(_basic_letters(basic))
    if "@ptid" in op or "@acc" in op or "hashdate" in op:
        return bool(letters & {"Z", "D"})
    if "@uid" in op:
        return "U" in letters
    return False


def target_operand(
    *,
    tag: str,
    basic: str,
    current: str | None,
) -> str:
    """
    Choose the aligned operand for one E.1-1 tag.

    Args:
        tag: Eight-hex-digit tag.
        basic: E.1-1 Basic Profile action.
        current: Existing script operation, or None when missing.

    Returns:
        Operation to store.
    """
    tag = tag.upper()
    if tag in DESCRIPTOR_KEEP_TAGS:
        return "@keep"
    if current is not None:
        op = normalize_script_operation(current)
        if tag == _AGE_ROUND_TAG and "@round" in op:
            return op
        if _remap_compatible(op, basic):
            return op
    return mapped_operand(basic)


def load_basic_profile(path: Path = _BASIC_PROFILE_PATH) -> dict[str, dict[str, str]]:
    """
    Load the committed E.1-1 Basic Profile extract.

    Args:
        path: JSON path.

    Returns:
        Tag → {name, basic}.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    attributes = raw.get("attributes") or {}
    return {
        str(tag).upper(): {
            "name": str(info.get("name") or tag),
            "basic": str(info.get("basic") or "").strip(),
        }
        for tag, info in attributes.items()
        if str(info.get("basic") or "").strip()
    }


def align_document(
    document: ScriptDocument,
    profile: dict[str, dict[str, str]],
) -> tuple[ScriptDocument, dict[str, int]]:
    """
    Apply E.1-1 Basic alignment to a script document in place.

    Args:
        document: Loaded default script.
        profile: Tag → {name, basic} from e1_1_basic_profile.json.

    Returns:
        (document, counts) where counts has keys changed, added, deferred, remapped.
    """
    by_tag = {rule.tag.upper(): rule for rule in document.rules}
    counts = {"changed": 0, "added": 0, "deferred": 0, "remapped": 0, "unchanged": 0}

    for tag, info in sorted(profile.items()):
        if not is_packaged_script_e1_1_tag(tag):
            continue
        basic = info["basic"]
        name = info["name"]
        current_rule = by_tag.get(tag)
        current_op = current_rule.operation if current_rule is not None else None
        new_op = target_operand(tag=tag, basic=basic, current=current_op)

        if tag in DESCRIPTOR_KEEP_TAGS:
            counts["deferred"] += 1
        elif current_op is not None and normalize_script_operation(
            current_op
        ) == normalize_script_operation(new_op) and _remap_compatible(
            current_op, basic
        ) and normalize_script_operation(new_op) != mapped_operand(basic):
            counts["remapped"] += 1

        if current_rule is None:
            rule = ScriptRule(tag=tag, name=name, en="T", operation=new_op)
            document.rules.append(rule)
            by_tag[tag] = rule
            counts["added"] += 1
            continue

        if current_rule.name in ("", current_rule.tag) and name:
            current_rule.name = name
        old = normalize_script_operation(current_rule.operation)
        new = normalize_script_operation(new_op)
        if old == new:
            counts["unchanged"] += 1
        else:
            current_rule.operation = new_op
            counts["changed"] += 1

    def _is_product_script_tag(tag: str) -> bool:
        t = tag.upper()
        return len(t) == 8 and all(c in "0123456789ABCDEF" for c in t) and int(t[:4], 16) % 2 == 0

    document.rules = [rule for rule in document.rules if _is_product_script_tag(rule.tag)]

    # Keep stable tag order for readable diffs.
    document.rules.sort(key=lambda rule: rule.tag.upper())
    return document, counts


def align_default_script(
    *,
    script_path: Path = _DEFAULT_SCRIPT,
    profile_path: Path = _BASIC_PROFILE_PATH,
) -> dict[str, int]:
    """
    Align the packaged default script to the committed E.1-1 Basic extract.

    Args:
        script_path: default-anonymizer.script path.
        profile_path: e1_1_basic_profile.json path.

    Returns:
        Alignment counts.
    """
    profile = load_basic_profile(profile_path)
    document = load_script_rules(script_path)
    document, counts = align_document(document, profile)
    write_script_rules(script_path, document)
    return counts


def main(argv: list[str] | None = None) -> int:
    """CLI entry: rewrite the packaged default script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--script",
        type=Path,
        default=_DEFAULT_SCRIPT,
        help="Packaged default anonymizer script",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=_BASIC_PROFILE_PATH,
        help="Committed E.1-1 Basic Profile JSON",
    )
    args = parser.parse_args(argv)
    if not args.script.is_file():
        raise SystemExit(f"script not found: {args.script}")
    if not args.profile.is_file():
        raise SystemExit(f"profile not found: {args.profile}")
    counts = align_default_script(script_path=args.script, profile_path=args.profile)
    print(
        f"wrote {args.script} "
        f"changed={counts['changed']} added={counts['added']} "
        f"deferred={counts['deferred']} remapped_preserved={counts['remapped']} "
        f"unchanged={counts['unchanged']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
