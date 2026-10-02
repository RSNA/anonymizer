"""CTP/TCIA properties lookup table — parse, preview, and commit."""

from __future__ import annotations

import logging
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from anonymizer.controller.project import ProjectController
from anonymizer.model.anonymizer import LookupPatient

if TYPE_CHECKING:
    from anonymizer.controller.anonymizer_script import ScriptDocument

logger = logging.getLogger(__name__)

_PROPERTIES_LINE = re.compile(r"^\s*([^#/][^/]*)/([^=]+)=(.*)$")
_DEFAULT_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "assets" / "scripts" / "default-anonymizer.script"
_PATIENT_TAGS = frozenset({"00100010", "00100020"})
_LOOKUP_PTID = "@lookup(this,ptid)"
_LOOKUP_DATEOFFSET = "@lookup(this,dateoffset)"


class LookupPropertiesError(ValueError):
    """Raised when a properties file cannot be parsed or fails validation."""


@dataclass(frozen=True)
class LookupPatientRow:
    patient_id: str
    anon_patient_id: str
    date_offset: int | None = None
    basedate: str | None = None


@dataclass(frozen=True)
class ScriptTagChange:
    tag: str
    name: str
    before: str
    after: str


@dataclass
class ScriptPatchResult:
    proposed_xml: str
    changes: list[ScriptTagChange]


@dataclass
class CtpLookupPreview:
    source_path: Path
    rows: list[LookupPatientRow]
    script_patch: ScriptPatchResult
    has_dateoffset: bool
    has_basedate: bool = False


@dataclass(frozen=True)
class LookupTableContext:
    """Whether a patient lookup table is available for @lookup operands."""

    present: bool
    has_dateoffset: bool
    has_basedate: bool = False
    path: Path | None = None


def private_lookup_properties_path(project_model) -> Path:
    return project_model.private_dir() / f"{project_model.site_id}-lookup.properties"


def private_anonymizer_script_path(project_model) -> Path:
    return project_model.private_dir() / f"{project_model.site_id}-anonymizer.script"


def lookup_table_context(project_model, pending: CtpLookupPreview | None = None) -> LookupTableContext:
    """Resolve lookup-table presence for script-editor operand filtering."""
    if pending is not None:
        return LookupTableContext(
            present=True,
            has_dateoffset=bool(pending.has_dateoffset),
            has_basedate=bool(pending.has_basedate),
            path=Path(pending.source_path),
        )
    path = private_lookup_properties_path(project_model)
    if not path.is_file():
        return LookupTableContext(present=False, has_dateoffset=False, has_basedate=False, path=None)
    try:
        rows = _parse_properties(path)
    except LookupPropertiesError:
        return LookupTableContext(present=True, has_dateoffset=False, has_basedate=False, path=path)
    return LookupTableContext(
        present=True,
        has_dateoffset=any(row.date_offset is not None for row in rows),
        has_basedate=any(row.basedate is not None for row in rows),
        path=path,
    )


def _lookup_after(tag: str, before: str, *, has_dateoffset: bool) -> str:
    """Single rewrite rule for lookup operands (shared by document + XML paths)."""
    text = str(before or "").strip()
    if "@remove" in text:
        return text
    tag_u = str(tag or "").upper()
    if tag_u in _PATIENT_TAGS and "@ptid" in text:
        return _LOOKUP_PTID
    if has_dateoffset and "@hashdate" in text:
        return _LOOKUP_DATEOFFSET
    return text


def apply_lookup_operands(document: ScriptDocument, *, has_dateoffset: bool) -> list[ScriptTagChange]:
    """Mutate document rules in place; return the list of tag changes applied."""
    changes: list[ScriptTagChange] = []
    for rule in document.rules:
        before = str(rule.operation or "").strip()
        after = _lookup_after(rule.tag, before, has_dateoffset=has_dateoffset)
        if after == before:
            continue
        changes.append(
            ScriptTagChange(tag=rule.tag.upper(), name=rule.name or rule.tag, before=before, after=after)
        )
        rule.operation = after
    return changes


def preview_lookup_operand_changes(document: ScriptDocument, *, has_dateoffset: bool) -> list[ScriptTagChange]:
    """Non-mutating preview of lookup rewrites against a ScriptDocument."""
    changes: list[ScriptTagChange] = []
    for rule in document.rules:
        before = str(rule.operation or "").strip()
        after = _lookup_after(rule.tag, before, has_dateoffset=has_dateoffset)
        if after == before:
            continue
        changes.append(
            ScriptTagChange(tag=rule.tag.upper(), name=rule.name or rule.tag, before=before, after=after)
        )
    return changes


def preview_ctp_lookup(
    properties_path: Path,
    document: ScriptDocument | None = None,
) -> CtpLookupPreview:
    """Parse properties and build script-change preview (document if given, else default asset)."""
    rows = _parse_properties(properties_path)
    has_dateoffset = any(row.date_offset is not None for row in rows)
    has_basedate = any(row.basedate is not None for row in rows)
    if document is not None:
        changes = preview_lookup_operand_changes(document, has_dateoffset=has_dateoffset)
        script_patch = ScriptPatchResult(proposed_xml="", changes=changes)
    else:
        script_patch = _build_script_patch_from_path(_DEFAULT_SCRIPT_PATH, has_dateoffset)
    return CtpLookupPreview(
        source_path=properties_path,
        rows=rows,
        script_patch=script_patch,
        has_dateoffset=has_dateoffset,
        has_basedate=has_basedate,
    )


def commit_ctp_lookup(
    project_controller: ProjectController,
    preview: CtpLookupPreview,
    document: ScriptDocument | None = None,
) -> Path:
    """
    Commit CTP lookup: copy properties, patch active script, load SQL, update script path.

    When ``document`` is provided, lookup operands are applied to that in-memory document
    and written. Otherwise the project's current ``anonymizer_script_path`` is patched if
    present; otherwise the packaged default is used.
    """
    from anonymizer.controller.anonymizer_script import load_script_rules, write_script_rules

    project_model = project_controller.model
    anonymizer_model = project_controller.anonymizer.model

    private_dir = project_model.private_dir()
    private_dir.mkdir(parents=True, exist_ok=True)

    properties_dest = private_lookup_properties_path(project_model)
    script_dest = private_anonymizer_script_path(project_model)

    shutil.copy2(preview.source_path, properties_dest)

    if document is not None:
        apply_lookup_operands(document, has_dateoffset=preview.has_dateoffset)
        write_script_rules(script_dest, document)
        document.source_path = script_dest
    else:
        source = Path(project_model.anonymizer_script_path)
        if source.is_file() and source.resolve() != _DEFAULT_SCRIPT_PATH.resolve():
            doc = load_script_rules(source)
            apply_lookup_operands(doc, has_dateoffset=preview.has_dateoffset)
            write_script_rules(script_dest, doc)
        elif source.is_file():
            # Packaged default (or identical path): patch via XML builder for stable output.
            write_patched_script(script_dest, preview.has_dateoffset)
        else:
            write_patched_script(script_dest, preview.has_dateoffset)

    orm_rows = [
        LookupPatient(
            patient_id=row.patient_id,
            anon_patient_id=row.anon_patient_id,
            date_offset=row.date_offset,
            basedate=row.basedate,
        )
        for row in preview.rows
    ]
    anonymizer_model.replace_lookup_patients(orm_rows)

    project_model.anonymizer_script_path = script_dest
    project_controller.anonymizer.project_model.anonymizer_script_path = script_dest
    anonymizer_model.reload_script(script_dest)

    logger.info(
        "CTP lookup committed: %d patients, properties=%s, script=%s",
        len(orm_rows),
        properties_dest,
        script_dest,
    )
    return script_dest


def write_patched_script(dest: Path, has_dateoffset: bool) -> None:
    """Write patched anonymizer script to dest from the packaged default template."""
    patch = _build_script_patch_from_path(_DEFAULT_SCRIPT_PATH, has_dateoffset)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(patch.proposed_xml, encoding="utf-8")


def _parse_properties(path: Path) -> list[LookupPatientRow]:
    if not path.is_file():
        raise LookupPropertiesError(f"Properties file not found: {path}")

    ptid: dict[str, str] = {}
    dateoffset: dict[str, int] = {}
    basedate: dict[str, str] = {}
    errors: list[str] = []

    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        match = _PROPERTIES_LINE.match(line)
        if not match:
            errors.append(f"Line {line_no}: invalid format")
            continue
        keytype, patient_id, replacement = match.group(1).strip(), match.group(2).strip(), match.group(3).strip()
        if keytype == "ptid":
            if not patient_id or not replacement:
                errors.append(f"Line {line_no}: empty ptid key or value")
            else:
                ptid[patient_id] = replacement
        elif keytype == "dateoffset":
            if not patient_id:
                errors.append(f"Line {line_no}: empty dateoffset patient id")
                continue
            try:
                dateoffset[patient_id] = int(replacement)
            except ValueError:
                errors.append(f"Line {line_no}: dateoffset must be an integer, got {replacement!r}")
        elif keytype == "basedate":
            if not patient_id:
                errors.append(f"Line {line_no}: empty basedate patient id")
                continue
            if len(replacement) != 8 or not replacement.isdigit():
                errors.append(
                    f"Line {line_no}: basedate must be YYYYMMDD, got {replacement!r}"
                )
                continue
            try:
                datetime.strptime(replacement, "%Y%m%d")
            except ValueError:
                errors.append(f"Line {line_no}: basedate is not a valid date: {replacement!r}")
                continue
            basedate[patient_id] = replacement
        else:
            errors.append(f"Line {line_no}: unsupported key type {keytype!r}")

    if errors:
        raise LookupPropertiesError("\n".join(errors))

    if not ptid:
        raise LookupPropertiesError("No ptid/ entries found in properties file")

    if dateoffset:
        missing = sorted(set(ptid) - set(dateoffset))
        if missing:
            raise LookupPropertiesError(
                "Every ptid patient must have a dateoffset entry. Missing: " + ", ".join(missing)
            )
        extra = sorted(set(dateoffset) - set(ptid))
        if extra:
            raise LookupPropertiesError(
                "dateoffset entries without matching ptid: " + ", ".join(extra)
            )

    if basedate:
        missing = sorted(set(ptid) - set(basedate))
        if missing:
            raise LookupPropertiesError(
                "Every ptid patient must have a basedate entry. Missing: " + ", ".join(missing)
            )
        extra = sorted(set(basedate) - set(ptid))
        if extra:
            raise LookupPropertiesError(
                "basedate entries without matching ptid: " + ", ".join(extra)
            )

    rows: list[LookupPatientRow] = []
    for patient_id, anon_patient_id in sorted(ptid.items()):
        offset = dateoffset.get(patient_id)
        rows.append(
            LookupPatientRow(
                patient_id=patient_id,
                anon_patient_id=anon_patient_id,
                date_offset=offset,
                basedate=basedate.get(patient_id),
            )
        )
    return rows


def _build_script_patch_from_path(script_path: Path, has_dateoffset: bool) -> ScriptPatchResult:
    if not script_path.is_file():
        raise LookupPropertiesError(f"Anonymizer script not found: {script_path}")

    tree = ET.parse(script_path)
    root = tree.getroot()
    changes: list[ScriptTagChange] = []

    for element in root.findall("e"):
        tag = str(element.attrib.get("t", "")).upper()
        name = str(element.attrib.get("n", tag))
        before = (element.text or "").strip()
        after = _lookup_after(tag, before, has_dateoffset=has_dateoffset)
        if after != before:
            changes.append(ScriptTagChange(tag=tag, name=name, before=before, after=after))
            element.text = after

    xml_body = ET.tostring(root, encoding="unicode")
    proposed_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body
    if not proposed_xml.endswith("\n"):
        proposed_xml += "\n"
    return ScriptPatchResult(proposed_xml=proposed_xml, changes=changes)
