"""CTP/TCIA patient lookup table for project settings and script operands.

Parse a .properties file, preview script operand rewrites, and commit the table
into the project (private copy, patched script, PHI SQL). Used from Settings /
script editor.

Public API
----------
LookupPropertiesError
    Raised when a properties file cannot be parsed or fails validation.

LookupPatientRow
    One patient mapping from the properties file.

ScriptTagChange
    One anonymizer-script tag rewrite shown in the preview.

ScriptPatchResult
    Proposed script XML (when built from file) plus the list of tag changes.

CtpLookupPreview
    Parsed rows plus script-change preview for Accept / staging.

LookupTableContext
    Whether a lookup table is present (for script-editor operand filtering).

lookup_table_context(project_model, pending=None) -> LookupTableContext
    Resolve lookup-table presence from pending preview or private properties.

preview_ctp_lookup(properties_path, document=None) -> CtpLookupPreview
    Parse properties and build the script-change preview.

apply_ctp_lookup_preview(document, preview) -> list[ScriptTagChange]
    Apply preview rewrites to an in-memory script (create-project staging).

commit_ctp_lookup(project_controller, preview, document=None) -> Path
    Copy properties, patch/write project script, load PHI SQL, reload script.
"""

import logging
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from anonymizer.controller.project import ProjectController
from anonymizer.controller.script.document import (
    ScriptDocument,
    load_script_rules,
    write_script_rules,
)
from anonymizer.model.anonymizer import CtpLookupPhiRow
from anonymizer.model.project import ProjectModel

logger = logging.getLogger(__name__)

_PROPERTIES_LINE = re.compile(r"^\s*([^#/][^/]*)/([^=]+)=(.*)$")
_DEFAULT_SCRIPT_PATH = ProjectModel.default_anonymizer_script_path()
_PATIENT_TAGS = frozenset({"00100010", "00100020"})
_LOOKUP_PTID = "@lookup(this,ptid)"
_LOOKUP_DATEOFFSET = "@lookup(this,dateoffset)"


class LookupPropertiesError(ValueError):
    """Raised when a properties file cannot be parsed or fails validation."""


@dataclass(frozen=True)
class LookupPatientRow:
    """One patient mapping from the properties file."""

    patient_id: str
    anon_patient_id: str
    date_offset: int | None = None
    base_date: str | None = None
    collection_name: str | None = None
    site_name: str | None = None
    lookup_site_id: str | None = None


@dataclass(frozen=True)
class ScriptTagChange:
    """One anonymizer-script tag rewrite shown in the preview."""

    tag: str
    name: str
    before: str
    after: str


@dataclass
class ScriptPatchResult:
    """Proposed script XML (when built from file) plus the list of tag changes."""

    proposed_xml: str
    changes: list[ScriptTagChange]


@dataclass
class CtpLookupPreview:
    """Parsed rows plus script-change preview for Accept / staging."""

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


def lookup_table_context(
    project_model: ProjectModel,
    pending: CtpLookupPreview | None = None) -> LookupTableContext:
    """
    Resolve lookup-table presence for script-editor operand filtering.

    Args:
        project_model: Active project model.
        pending: Create-project staged preview, if any.

    Returns:
        Presence and dateoffset/basedate flags for the table in force.
    """
    if pending is not None:
        return LookupTableContext(
            present=True,
            has_dateoffset=bool(pending.has_dateoffset),
            has_basedate=bool(pending.has_basedate),
            path=Path(pending.source_path))
    path = _properties_path(project_model)
    if not path.is_file():
        return LookupTableContext(present=False, has_dateoffset=False, has_basedate=False, path=None)
    try:
        rows = _parse_properties(path)
    except LookupPropertiesError:
        return LookupTableContext(present=True, has_dateoffset=False, has_basedate=False, path=path)
    return LookupTableContext(
        present=True,
        has_dateoffset=any(row.date_offset is not None for row in rows),
        has_basedate=any(row.base_date is not None for row in rows),
        path=path)


def preview_ctp_lookup(
    properties_path: Path,
    document: ScriptDocument | None = None) -> CtpLookupPreview:
    """
    Parse properties and build the script-change preview.

    Args:
        properties_path: Path to the CTP/TCIA .properties file.
        document: In-memory script to preview against; when None, uses the packaged default.

    Returns:
        Preview with rows and script tag changes.

    Raises:
        LookupPropertiesError: Invalid or missing properties file.
    """
    rows = _parse_properties(properties_path)
    has_dateoffset = any(row.date_offset is not None for row in rows)
    has_basedate = any(row.base_date is not None for row in rows)
    if document is not None:
        changes = _preview_lookup_operand_changes(document, has_dateoffset=has_dateoffset)
        script_patch = ScriptPatchResult(proposed_xml="", changes=changes)
    else:
        script_patch = _build_script_patch_from_path(_DEFAULT_SCRIPT_PATH, has_dateoffset)
    return CtpLookupPreview(
        source_path=properties_path,
        rows=rows,
        script_patch=script_patch,
        has_dateoffset=has_dateoffset,
        has_basedate=has_basedate)


def apply_ctp_lookup_preview(
    document: ScriptDocument,
    preview: CtpLookupPreview) -> list[ScriptTagChange]:
    """
    Apply preview rewrites to an in-memory script (create-project staging).

    Args:
        document: Script document to mutate.
        preview: Preview from preview_ctp_lookup.

    Returns:
        Tag changes that were applied.
    """
    return _apply_lookup_operands(document, has_dateoffset=preview.has_dateoffset)


def commit_ctp_lookup(
    project_controller: ProjectController,
    preview: CtpLookupPreview,
    document: ScriptDocument | None = None) -> Path:
    """
    Commit CTP lookup: copy properties, patch active script, load SQL, update script path.

    When document is provided, lookup operands are applied to that in-memory document
    and written. Otherwise the project's current anonymizer_script_path is patched if
    present; otherwise the packaged default is used.

    Args:
        project_controller: Live project controller.
        preview: Preview from preview_ctp_lookup.
        document: Optional in-memory script to patch and write.

    Returns:
        Path of the written project anonymizer script.
    """
    project_model = project_controller.model
    anonymizer_model = project_controller.anonymizer.model

    private_dir = project_model.private_dir()
    private_dir.mkdir(parents=True, exist_ok=True)

    properties_dest = _properties_path(project_model)
    source = Path(project_model.anonymizer_script_path)
    project_model.anonymizer_script_path = (
        Path(project_model.storage_dir) / f"{project_model.site_id}-anonymizer.script"
    )
    script_dest = project_model.anonymizer_script_path
    script_dest.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(preview.source_path, properties_dest)

    if document is not None:
        _apply_lookup_operands(document, has_dateoffset=preview.has_dateoffset)
        write_script_rules(script_dest, document)
        document.source_path = script_dest
    else:
        if source.is_file() and source.resolve() != _DEFAULT_SCRIPT_PATH.resolve():
            doc = load_script_rules(source)
            _apply_lookup_operands(doc, has_dateoffset=preview.has_dateoffset)
            write_script_rules(script_dest, doc)
        else:
            _write_patched_script(script_dest, preview.has_dateoffset)

    phi_rows = [
        CtpLookupPhiRow(
            patient_id=row.patient_id,
            anon_patient_id=row.anon_patient_id,
            date_offset=row.date_offset,
            base_date=row.base_date,
            collection_name=row.collection_name,
            site_name=row.site_name,
            lookup_site_id=row.lookup_site_id,
        )
        for row in preview.rows
    ]
    anonymizer_model.upsert_ctp_lookup_phi(phi_rows)

    project_controller.anonymizer.reload_script(script_dest)

    logger.info(
        "CTP lookup committed: %d patients, properties=%s, script=%s",
        len(phi_rows),
        properties_dest,
        script_dest)
    return script_dest


def _properties_path(project_model: ProjectModel) -> Path:
    return project_model.private_dir() / f"{project_model.site_id}-lookup.properties"


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


def _apply_lookup_operands(document: ScriptDocument, *, has_dateoffset: bool) -> list[ScriptTagChange]:
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


def _preview_lookup_operand_changes(document: ScriptDocument, *, has_dateoffset: bool) -> list[ScriptTagChange]:
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


def _write_patched_script(dest: Path, has_dateoffset: bool) -> None:
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
    ddate: dict[str, str] = {}
    cname: dict[str, str] = {}
    sname: dict[str, str] = {}
    siteid: dict[str, str] = {}
    errors: list[str] = []
    skipped_keys: dict[str, int] = {}

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
            parsed = _parse_yyyyymmdd(replacement)
            if parsed is None:
                errors.append(
                    f"Line {line_no}: basedate must be YYYYMMDD, got {replacement!r}"
                )
                continue
            basedate[patient_id] = parsed
        elif keytype == "ddate":
            if not patient_id:
                errors.append(f"Line {line_no}: empty ddate patient id")
                continue
            parsed = _parse_tcia_ddate(replacement)
            if parsed is None:
                errors.append(
                    f"Line {line_no}: ddate must be M/D/YYYY or YYYYMMDD, got {replacement!r}"
                )
                continue
            ddate[patient_id] = parsed
        elif keytype == "cname":
            if not patient_id or not replacement:
                errors.append(f"Line {line_no}: empty cname key or value")
            else:
                cname[patient_id] = replacement
        elif keytype == "sname":
            if not patient_id or not replacement:
                errors.append(f"Line {line_no}: empty sname key or value")
            else:
                sname[patient_id] = replacement
        elif keytype == "siteid":
            if not patient_id or not replacement:
                errors.append(f"Line {line_no}: empty siteid key or value")
            else:
                siteid[patient_id] = replacement
        else:
            skipped_keys[keytype] = skipped_keys.get(keytype, 0) + 1

    if errors:
        raise LookupPropertiesError("\n".join(errors))

    if not ptid:
        raise LookupPropertiesError("No ptid/ entries found in properties file")

    if skipped_keys:
        parts = ", ".join(f"{key}×{count}" for key, count in sorted(skipped_keys.items()))
        logger.warning("CTP lookup skipped unsupported property key types: %s", parts)

    if dateoffset:
        _require_ptid_alignment(ptid, dateoffset, "dateoffset")

    if basedate:
        _require_ptid_alignment(ptid, basedate, "basedate")

    if ddate:
        _require_ptid_alignment(ptid, ddate, "ddate")

    if cname:
        _require_ptid_alignment(ptid, cname, "cname")

    if sname:
        _require_ptid_alignment(ptid, sname, "sname")

    if siteid:
        _require_ptid_alignment(ptid, siteid, "siteid")

    rows: list[LookupPatientRow] = []
    for patient_id, anon_patient_id in sorted(ptid.items()):
        base = basedate.get(patient_id) or ddate.get(patient_id)
        rows.append(
            LookupPatientRow(
                patient_id=patient_id,
                anon_patient_id=anon_patient_id,
                date_offset=dateoffset.get(patient_id),
                base_date=base,
                collection_name=cname.get(patient_id),
                site_name=sname.get(patient_id),
                lookup_site_id=siteid.get(patient_id),
            )
        )
    return rows


def _require_ptid_alignment(ptid: dict[str, str], other: dict[str, object], label: str) -> None:
    """Raise when other keys are not exactly the ptid patient set."""
    missing = sorted(set(ptid) - set(other))
    if missing:
        raise LookupPropertiesError(
            f"Every ptid patient must have a {label} entry. Missing: " + ", ".join(missing)
        )
    extra = sorted(set(other) - set(ptid))
    if extra:
        raise LookupPropertiesError(
            f"{label} entries without matching ptid: " + ", ".join(extra)
        )


def _parse_yyyyymmdd(raw: str) -> str | None:
    """Return YYYYMMDD when valid, else None."""
    text = str(raw or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None
    return text


def _parse_tcia_ddate(raw: str) -> str | None:
    """Parse TCIA ddate (M/D/YYYY or YYYYMMDD) to YYYYMMDD."""
    text = str(raw or "").strip()
    ymd = _parse_yyyyymmdd(text)
    if ymd is not None:
        return ymd
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return None


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
