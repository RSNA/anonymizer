"""Anonymizer script document types and XML load/write.

Public API
----------
ScriptRule
    One enabled <e> rule (tag, name, operation).

ScriptRRule
    Preserved <r> element (not edited by the UI).

ScriptDocument
    Rules list plus optional source path.

load_script_rules(path) -> ScriptDocument
    Load a .script file; blank operation text becomes @keep.

write_script_rules(path, document) -> None
    Write CTP-compatible script XML.

tag_keep_from_document(document) -> dict[str, str]
    Tag → operation for the runtime keep table (@remove omitted).

validate_document(document) -> list[str]
    All validation errors (empty if OK).
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from anonymizer.controller.script.operands import (
    is_remove_operation,
    validate_operation,
)


@dataclass
class ScriptRule:
    """One enabled <e> rule (tag, name, operation)."""

    tag: str
    name: str
    en: str
    operation: str


@dataclass
class ScriptRRule:
    """Preserved <r> elements (not edited by the UI)."""

    tag: str
    en: str
    text: str


@dataclass
class ScriptDocument:
    """In-memory anonymizer script."""

    rules: list[ScriptRule] = field(default_factory=list)
    r_rules: list[ScriptRRule] = field(default_factory=list)
    source_path: Path | None = None

    def rule_index(self, tag: str) -> int | None:
        """
        Index of the rule for tag, or None.

        Args:
            tag: Eight-hex-digit DICOM tag.

        Returns:
            Index into rules, or None.
        """
        key = tag.upper()
        for index, rule in enumerate(self.rules):
            if rule.tag.upper() == key:
                return index
        return None

    def get_rule(self, tag: str) -> ScriptRule | None:
        """
        Rule for tag, or None.

        Args:
            tag: Eight-hex-digit DICOM tag.

        Returns:
            Matching rule, or None.
        """
        index = self.rule_index(tag)
        return None if index is None else self.rules[index]


def _operation_from_element_text(text: str | None) -> str:
    """Blank or whitespace-only element text becomes @keep."""
    op = str(text or "").strip()
    return op if op else "@keep"


def load_script_rules(path: Path) -> ScriptDocument:
    """
    Load a .script file into a document.

    Blank operation text is stored as @keep.

    Args:
        path: Path to the script file.

    Returns:
        Loaded document.

    Raises:
        FileNotFoundError: When path is missing.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Script file not found: {path}")
    root = ET.parse(path).getroot()
    rules: list[ScriptRule] = []
    for element in root.findall("e"):
        tag = str(element.attrib.get("t", "") or "").upper()
        if not tag:
            continue
        rules.append(
            ScriptRule(
                tag=tag,
                name=str(element.attrib.get("n", "") or tag),
                en=str(element.attrib.get("en", "T") or "T"),
                operation=_operation_from_element_text(element.text),
            )
        )
    r_rules: list[ScriptRRule] = []
    for element in root.findall("r"):
        r_rules.append(
            ScriptRRule(
                tag=str(element.attrib.get("t", "") or ""),
                en=str(element.attrib.get("en", "T") or "T"),
                text=str(element.text or ""),
            )
        )
    return ScriptDocument(rules=rules, r_rules=r_rules, source_path=path)


def write_script_rules(path: Path, document: ScriptDocument) -> None:
    """
    Write CTP-compatible script XML (full e list including @remove()).

    Args:
        path: Destination path.
        document: Document to write.

    Returns:
        None.

    Raises:
        ValueError: When a rule operation fails validation.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<script>"]
    for rule in document.rules:
        op = str(rule.operation or "").strip() or "@keep"
        err = validate_operation(op)
        if err is not None:
            raise ValueError(f"{rule.tag}: {err}")
        name = rule.name or rule.tag
        en = rule.en or "T"
        lines.append(
            f' <e en="{_xml_attr(en)}" t="{_xml_attr(rule.tag.upper())}" n="{_xml_attr(name)}">{op}</e>'
        )
    for r_rule in document.r_rules:
        lines.append(
            f' <r en="{_xml_attr(r_rule.en or "T")}" t="{_xml_attr(r_rule.tag)}">{r_rule.text or ""}</r>'
        )
    lines.append("</script>")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def tag_keep_from_document(document: ScriptDocument) -> dict[str, str]:
    """
    Build the runtime keep table from a script document.

    Args:
        document: Loaded or compiled script.

    Returns:
        Uppercase tag → operation; @remove rules omitted.
    """
    out: dict[str, str] = {}
    for rule in document.rules:
        if is_remove_operation(rule.operation):
            continue
        op = str(rule.operation or "").strip() or "@keep"
        out[rule.tag.upper()] = op
    return out


def validate_document(document: ScriptDocument) -> list[str]:
    """
    Return all validation errors (empty if OK).

    Args:
        document: Document to validate.

    Returns:
        Error messages.
    """
    errors: list[str] = []
    seen: set[str] = set()
    for rule in document.rules:
        tag = rule.tag.upper()
        if tag in seen:
            errors.append(f"Duplicate tag: {tag}")
        seen.add(tag)
        err = validate_operation(rule.operation)
        if err is not None:
            errors.append(f"{tag}: {err}")
    return errors


def _xml_attr(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
