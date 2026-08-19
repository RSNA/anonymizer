"""CTP/TCIA properties lookup table — parse, preview, and commit."""

from __future__ import annotations

import logging
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from anonymizer.controller.project import ProjectController
from anonymizer.model.anonymizer import LookupPatient

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


def preview_ctp_lookup(properties_path: Path) -> CtpLookupPreview:
    """Parse properties, validate, and build script patch preview from the default template."""
    rows = _parse_properties(properties_path)
    has_dateoffset = any(row.date_offset is not None for row in rows)
    script_patch = _build_script_patch(has_dateoffset)
    return CtpLookupPreview(
        source_path=properties_path,
        rows=rows,
        script_patch=script_patch,
        has_dateoffset=has_dateoffset,
    )


def commit_ctp_lookup(project_controller: ProjectController, preview: CtpLookupPreview) -> Path:
    """
    Atomically commit CTP lookup: copy properties, write patched script, load SQL, update script path.

    Returns the private script path written.
    """
    project_model = project_controller.model
    anonymizer_model = project_controller.anonymizer.model

    private_dir = project_model.private_dir()
    private_dir.mkdir(parents=True, exist_ok=True)

    properties_dest = private_dir / f"{project_model.site_id}-lookup.properties"
    script_dest = private_dir / f"{project_model.site_id}-anonymizer.script"

    shutil.copy2(preview.source_path, properties_dest)
    write_patched_script(script_dest, preview.has_dateoffset)

    orm_rows = [
        LookupPatient(
            patient_id=row.patient_id,
            anon_patient_id=row.anon_patient_id,
            date_offset=row.date_offset,
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
    """Write patched anonymizer script to dest."""
    patch = _build_script_patch(has_dateoffset)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(patch.proposed_xml, encoding="utf-8")


def _parse_properties(path: Path) -> list[LookupPatientRow]:
    if not path.is_file():
        raise LookupPropertiesError(f"Properties file not found: {path}")

    ptid: dict[str, str] = {}
    dateoffset: dict[str, int] = {}
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

    rows: list[LookupPatientRow] = []
    for patient_id, anon_patient_id in sorted(ptid.items()):
        offset = dateoffset.get(patient_id)
        rows.append(LookupPatientRow(patient_id=patient_id, anon_patient_id=anon_patient_id, date_offset=offset))
    return rows


def _build_script_patch(has_dateoffset: bool) -> ScriptPatchResult:
    if not _DEFAULT_SCRIPT_PATH.is_file():
        raise LookupPropertiesError(f"Default anonymizer script not found: {_DEFAULT_SCRIPT_PATH}")

    tree = ET.parse(_DEFAULT_SCRIPT_PATH)
    root = tree.getroot()
    changes: list[ScriptTagChange] = []

    for element in root.findall("e"):
        tag = str(element.attrib.get("t", "")).upper()
        name = str(element.attrib.get("n", tag))
        before = (element.text or "").strip()
        if "@remove" in before:
            continue

        after = before
        if tag in _PATIENT_TAGS and "@ptid" in before:
            after = _LOOKUP_PTID
        elif has_dateoffset and "@hashdate" in before:
            after = _LOOKUP_DATEOFFSET

        if after != before:
            changes.append(ScriptTagChange(tag=tag, name=name, before=before, after=after))
            element.text = after

    xml_body = ET.tostring(root, encoding="unicode")
    proposed_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body
    if not proposed_xml.endswith("\n"):
        proposed_xml += "\n"
    return ScriptPatchResult(proposed_xml=proposed_xml, changes=changes)


def private_lookup_properties_path(project_model) -> Path:
    return project_model.private_dir() / f"{project_model.site_id}-lookup.properties"


def private_anonymizer_script_path(project_model) -> Path:
    return project_model.private_dir() / f"{project_model.site_id}-anonymizer.script"
