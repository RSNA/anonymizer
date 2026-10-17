"""Metadata free-text / date PHI extract for Series View Metadata assessment.

Import concrete submodules for runtime use. Package ``__getattr__`` re-exports
the Public API lazily so light modules (e.g. ``process_private_tags_tcia``)
do not pull the anonymizer/script import graph.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "ACTION_PRIORITY",
    "BUNDLED_DICOM_EDITION",
    "VR_SEQ_TEXT",
    "MetadataPhiRow",
    "MetadataTreeNode",
    "SeriesMetadataAssessmentRow",
    "SpanFragment",
    "TciaPrivateEntry",
    "allowed_tags_for_sop_class",
    "apply_text_at_path",
    "build_assessment_note",
    "build_metadata_tree",
    "clinical_dateinc_days",
    "collapse_retain_safe_action",
    "consolidate_series_metadata",
    "detect_phi_in_texts",
    "display_metadata_vr",
    "element_display_name",
    "entity_count_by_label",
    "extract_metadata_phi_rows",
    "extract_sop_metadata_rows",
    "filter_metadata_tree",
    "incrementdate_operand",
    "intern_metadata_rows",
    "is_anonymizer_field",
    "is_anonymizer_stamp_row",
    "load_dicom_info",
    "load_tcia_private_kb",
    "mark_iod_unexpected",
    "match_tcia_private",
    "metadata_text_occurrence_count",
    "process_private_tags_tcia",
    "scrub_span_in_row",
    "tcia_disposition_to_operand",
    "unique_metadata_texts",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "ACTION_PRIORITY": (".tcia_kb", "ACTION_PRIORITY"),
    "BUNDLED_DICOM_EDITION": (".iod_allowlist", "BUNDLED_DICOM_EDITION"),
    "VR_SEQ_TEXT": (".extract", "VR_SEQ_TEXT"),
    "MetadataPhiRow": (".extract", "MetadataPhiRow"),
    "MetadataTreeNode": (".viewer_tree", "MetadataTreeNode"),
    "SeriesMetadataAssessmentRow": (".series_assessment", "SeriesMetadataAssessmentRow"),
    "SpanFragment": (".extract", "SpanFragment"),
    "TciaPrivateEntry": (".tcia_kb", "TciaPrivateEntry"),
    "allowed_tags_for_sop_class": (".iod_allowlist", "allowed_tags_for_sop_class"),
    "apply_text_at_path": (".extract", "apply_text_at_path"),
    "build_assessment_note": (".series_assessment", "build_assessment_note"),
    "build_metadata_tree": (".viewer_tree", "build_metadata_tree"),
    "clinical_dateinc_days": (".process_private_tags_tcia", "clinical_dateinc_days"),
    "collapse_retain_safe_action": (".tcia_kb", "collapse_retain_safe_action"),
    "consolidate_series_metadata": (".series_assessment", "consolidate_series_metadata"),
    "detect_phi_in_texts": (".detect", "detect_phi_in_texts"),
    "display_metadata_vr": (".series_assessment", "display_metadata_vr"),
    "element_display_name": (".extract", "element_display_name"),
    "entity_count_by_label": (".detect", "entity_count_by_label"),
    "extract_metadata_phi_rows": (".extract", "extract_metadata_phi_rows"),
    "extract_sop_metadata_rows": (".series_index", "extract_sop_metadata_rows"),
    "filter_metadata_tree": (".viewer_tree", "filter_metadata_tree"),
    "incrementdate_operand": (".process_private_tags_tcia", "incrementdate_operand"),
    "intern_metadata_rows": (".series_index", "intern_metadata_rows"),
    "is_anonymizer_field": (".extract", "is_anonymizer_field"),
    "is_anonymizer_stamp_row": (".extract", "is_anonymizer_stamp_row"),
    "load_dicom_info": (".iod_allowlist", "load_dicom_info"),
    "load_tcia_private_kb": (".tcia_kb", "load_tcia_private_kb"),
    "mark_iod_unexpected": (".iod_allowlist", "mark_iod_unexpected"),
    "match_tcia_private": (".tcia_kb", "match_tcia_private"),
    "metadata_text_occurrence_count": (".series_index", "metadata_text_occurrence_count"),
    "process_private_tags_tcia": (".process_private_tags_tcia", "process_private_tags_tcia"),
    "scrub_span_in_row": (".extract", "scrub_span_in_row"),
    "tcia_disposition_to_operand": (".process_private_tags_tcia", "tcia_disposition_to_operand"),
    "unique_metadata_texts": (".series_index", "unique_metadata_texts"),
}


def __getattr__(name: str) -> Any:
    spec = _EXPORTS.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod_name, attr = spec

    mod = import_module(mod_name, __name__)
    value = getattr(mod, attr)
    globals()[name] = value
    return value
