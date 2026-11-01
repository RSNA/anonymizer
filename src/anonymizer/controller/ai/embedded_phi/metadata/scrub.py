"""Batch Clean Descriptors: detect PHI on free-text tags, replace, stamp.

Used by Embedded PHI AI Batch Metadata path (same detect → remove → save
flow as Series View Metadata assessment).

Detect (see metadata.detect) runs steps 1–5 (collect, frozen NER compile,
OpenMed, remap, post-NER). This module runs steps 6–7: IS/DS numeric path
logging, then remove_phi per cell and Clean Descriptors stamp when anything
changed. IS/DS are included in NER so embedded dates/PHI can be removed.
Tags with script @safe() are not sent to NER and are never rewritten here.
Same Content on multiple tags: detect once; write cleaned text to every match.

Public API
----------
scrub_dataset_descriptors(ds, *, replace_mode='blank', project_dir=None, script_operations=None) -> tuple[bool, list[str]]
    Detect PHI in free-text tags, blank/synth replace, stamp Clean Descriptors.

scrub_file_descriptors(dcm_path, *, replace_mode='blank', project_dir=None, script_operations=None) -> tuple[bool, list[str]]
    Load one DICOM file, scrub_dataset_descriptors, save when changed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydicom import dcmread
from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.detect import detect_phi_in_texts
from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    apply_text_at_path,
    extract_metadata_phi_rows,
    is_pure_numeric_string_value,
    omit_pure_numeric_from_descriptor_ner,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import format_tagged_entities
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import (
    MetadataNerItem,
    is_anon_identity_tag,
)
from anonymizer.controller.ai.embedded_phi.report.process_report_text import remove_phi
from anonymizer.controller.script.compile import project_script_operations
from anonymizer.controller.script.operands import is_safe_operation
from anonymizer.utils.dicom import DeidMethodCode, record_deid_method_codes

logger = logging.getLogger(__name__)

ReplaceMode = Literal["blank", "synth"]


def scrub_dataset_descriptors(
    ds: Dataset,
    *,
    replace_mode: ReplaceMode = "blank",
    project_dir: Path | None = None,
    script_operations: Mapping[str, str] | None = None,
) -> tuple[bool, list[str]]:
    """Detect PHI in free-text tags, blank/synth replace, stamp Clean Descriptors.

    Flat text rows only (SEQ compiled cells are left to Structured Content /
    Reports). Matches Metadata assessment Save: write cleaned Content then
    stamp Clean Descriptors when anything changed. Script @safe() tags are
    omitted from NER and never rewritten.

    Args:
        ds: Dataset to mutate in place.
        replace_mode: blank clears PHI spans; synth uses synthetic replacements.
        project_dir: Project dir for modality whitelist and compiled script.
        script_operations: Optional tag→operand map (tests); else loaded from
            project_dir's *-anonymizer.script.

    Returns:
        (changed, removed_span_texts).
    """
    ops = (
        {str(k).upper(): str(v) for k, v in script_operations.items()}
        if script_operations is not None
        else project_script_operations(project_dir)
    )
    rows = extract_metadata_phi_rows(ds)
    items: list[MetadataNerItem] = []
    safe_hexes: set[str] = set()
    for row in rows:
        if row.is_seq_text or row.is_date or row.is_anonymizer_field:
            continue
        if is_anon_identity_tag(tag_path=row.tag_path, tag=row.tag, field_name=row.name):
            continue
        text = str(row.text or "").strip()
        if not text:
            continue
        tag_hex = row.tag_hex
        op = ops.get(tag_hex, "")
        if is_safe_operation(op):
            safe_hexes.add(tag_hex)
            continue
        items.append(
            MetadataNerItem(
                text=row.text,
                field_name=row.name,
                tag=row.tag,
                vr=row.vr,
                tag_path=row.tag_path,
                is_anonymizer_field=row.is_anonymizer_field,
                is_date=row.is_date,
                script_operation=op,
            )
        )
    if not items:
        _log_is_ds_numeric_path(ds)
        return False, []

    modality = str(ds.get("Modality", "") or "").strip() or None
    entities_by_content = detect_phi_in_texts(
        ds=ds,
        items=items,
        project_dir=project_dir,
        modality=modality,
        script_operations=ops,
    )

    # --- 6. IS/DS numeric path (pure vs impure; both may be in NER) ---------
    _log_is_ds_numeric_path(ds)

    if not entities_by_content:
        return False, []

    # --- 7. Apply remove and stamp ------------------------------------------
    synthetic = replace_mode == "synth"
    removed: list[str] = []
    changed = False
    cleaned_by_text: dict[str, str] = {}
    tagged_lines: list[str] = []
    cleaned_lines: list[str] = []
    entity_total = 0
    fields_written = 0

    for row in rows:
        if row.is_seq_text or row.tag_hex in safe_hexes:
            continue
        if is_anon_identity_tag(tag_path=row.tag_path, tag=row.tag, field_name=row.name):
            continue
        if row.text not in entities_by_content:
            continue
        ents = entities_by_content[row.text]
        if not ents:
            continue
        # Same Content can appear on several tags. Detect once; write the
        # cleaned string to every matching tag (do not skip after the first).
        # Identity tags are excluded above so Patient ID is never blanked when
        # it shares Content with a descriptor that was cleaned.
        if row.text not in cleaned_by_text:
            removed.extend(
                span for e in ents if (span := row.text[e.start : e.end].strip())
            )
            field = str(row.name or row.tag_path or "field").strip() or "field"
            tagged_lines.append(f"{field}: {format_tagged_entities(row.text, ents)}")
            cleaned = remove_phi(row.text, list(ents), synthetic=synthetic, log=False)
            cleaned_lines.append(f"{field}: {cleaned}")
            entity_total += len(ents)
            cleaned_by_text[row.text] = cleaned
        apply_text_at_path(ds, row.tag_path, cleaned_by_text[row.text])
        fields_written += 1
        changed = True

    if changed:
        record_deid_method_codes(ds, {DeidMethodCode.CLEAN_DESCRIPTORS})
        logger.info(
            "Clean Descriptors step 7/7 apply entities=%d contents=%d fields=%d\n"
            "<<< tagged\n%s\n>>>\n"
            "<<< after remove\n%s\n>>>",
            entity_total,
            len(cleaned_by_text),
            fields_written,
            "\n".join(tagged_lines),
            "\n".join(cleaned_lines),
        )
    else:
        logger.info("Clean Descriptors step 7/7 apply (no PHI writes)")
    return changed, removed


def scrub_file_descriptors(
    dcm_path: Path,
    *,
    replace_mode: ReplaceMode = "blank",
    project_dir: Path | None = None,
    script_operations: Mapping[str, str] | None = None,
) -> tuple[bool, list[str]]:
    """Load one DICOM file, scrub_dataset_descriptors, save when changed.

    Args:
        dcm_path: Path to a DICOM instance.
        replace_mode: blank or synth.
        project_dir: Project dir for modality whitelist and script.
        script_operations: Optional tag→operand map (tests).

    Returns:
        (changed, removed_span_texts).
    """
    ds = dcmread(str(dcm_path))
    changed, removed = scrub_dataset_descriptors(
        ds,
        replace_mode=replace_mode,
        project_dir=project_dir,
        script_operations=script_operations,
    )
    if changed:
        ds.save_as(str(dcm_path), enforce_file_format=True)
    return changed, removed


def _log_is_ds_numeric_path(ds: Dataset) -> None:
    """Step 6: log pure vs impure IS/DS (both eligible for NER input)."""
    pure_notes: list[str] = []
    impure_notes: list[str] = []
    for elem in ds:
        vr = str(elem.VR or "").upper()
        if vr not in {"IS", "DS"}:
            continue
        name = str(getattr(elem, "keyword", None) or elem.tag)
        if omit_pure_numeric_from_descriptor_ner(
            vr, elem.value
        ) or is_pure_numeric_string_value(elem.value):
            pure_notes.append(f"{name}={_brief(elem.value)}")
        else:
            impure_notes.append(f"{name}={_brief(elem.value)}")
    logger.info(
        "Clean Descriptors step 6/7 IS/DS numeric pure=%d impure=%d "
        "(both in NER input VR list)%s%s",
        len(pure_notes),
        len(impure_notes),
        f" pure=[{'; '.join(pure_notes[:8])}]" if pure_notes else "",
        f" impure=[{'; '.join(impure_notes[:8])}]" if impure_notes else "",
    )


def _brief(value: object, *, limit: int = 40) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
