"""Harmonize AI Feature: Playbook series descriptions and LOINC study offers.

Public API
----------
(none)
    Import concrete submodules (or names re-exported by this package).
"""
from anonymizer.controller.ai.harmonize.description_components import (
    PLANAR_COMPONENT_FIELDS as PLANAR_COMPONENT_FIELDS,
)
from anonymizer.controller.ai.harmonize.description_components import (
    TSEG_COMPONENT_FIELDS as TSEG_COMPONENT_FIELDS,
)
from anonymizer.controller.ai.harmonize.description_components import (
    PlanarComponentSelection as PlanarComponentSelection,
)
from anonymizer.controller.ai.harmonize.description_components import (
    PlaybookComponentSelection as PlaybookComponentSelection,
)
from anonymizer.controller.ai.harmonize.description_components import (
    format_planar_component_description as format_planar_component_description,
)
from anonymizer.controller.ai.harmonize.description_components import (
    format_playbook_series_description as format_playbook_series_description,
)
from anonymizer.controller.ai.harmonize.description_components import (
    format_series_playbook_fields as format_series_playbook_fields,
)
from anonymizer.controller.ai.harmonize.description_components import (
    series_playbook_component_field_order as series_playbook_component_field_order,
)
from anonymizer.controller.ai.harmonize.description_components import (
    series_playbook_component_initial as series_playbook_component_initial,
)
from anonymizer.controller.ai.harmonize.description_components import (
    series_playbook_component_options as series_playbook_component_options,
)
from anonymizer.controller.ai.harmonize.loinc_study import StudyDescriptionOffer as StudyDescriptionOffer
from anonymizer.controller.ai.harmonize.pipeline import (
    MIN_DESCRIPTION_CHOICES as MIN_DESCRIPTION_CHOICES,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    DescriptionEditSelection as DescriptionEditSelection,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeApplyOutcome as HarmonizeApplyOutcome,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizedResult as HarmonizedResult,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeProgress as HarmonizeProgress,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeProgressCallback as HarmonizeProgressCallback,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeStudiesBatchHook as HarmonizeStudiesBatchHook,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeStudiesCancelledCallback as HarmonizeStudiesCancelledCallback,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeStudiesLogCallback as HarmonizeStudiesLogCallback,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeStudiesProgressCallback as HarmonizeStudiesProgressCallback,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    HarmonizeStudiesSummary as HarmonizeStudiesSummary,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    apply_harmonized_description as apply_harmonized_description,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    apply_harmonized_study_description as apply_harmonized_study_description,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    apply_series_descriptions as apply_series_descriptions,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    apply_study_description_offer as apply_study_description_offer,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    apply_study_descriptions as apply_study_descriptions,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    auto_apply_best_study_descriptions as auto_apply_best_study_descriptions,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    auto_apply_study_description_offer as auto_apply_study_description_offer,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    classify_description_edit_selection as classify_description_edit_selection,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    ct_series_paths_for_study as ct_series_paths_for_study,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    ensure_min_description_choices as ensure_min_description_choices,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    enumerate_ct_series_for_studies as enumerate_ct_series_for_studies,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    enumerate_harmonize_series_for_studies as enumerate_harmonize_series_for_studies,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    enumerate_planar_series_for_studies as enumerate_planar_series_for_studies,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    enumerate_tseg_series_for_studies as enumerate_tseg_series_for_studies,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    find_similar_series_uids as find_similar_series_uids,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    find_similar_study_uids as find_similar_study_uids,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    find_studies_with_fingerprint as find_studies_with_fingerprint,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    format_harmonize_batch_contrast_log_lines as format_harmonize_batch_contrast_log_lines,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    format_harmonize_batch_progress_text as format_harmonize_batch_progress_text,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    format_harmonize_batch_series_label as format_harmonize_batch_series_label,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    format_harmonize_progress_message as format_harmonize_progress_message,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    group_study_description_offers_by_fingerprint as group_study_description_offers_by_fingerprint,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    harmonize_and_apply_series as harmonize_and_apply_series,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    harmonize_context_hint as harmonize_context_hint,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    harmonize_series as harmonize_series,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    harmonize_studies_batch as harmonize_studies_batch,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    harmonized_description_from_cache as harmonized_description_from_cache,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    log_harmonize_playbook_rows as log_harmonize_playbook_rows,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    maybe_offer_study_description_harmonize as maybe_offer_study_description_harmonize,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    missing_series_description_label as missing_series_description_label,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    planar_series_paths_for_study as planar_series_paths_for_study,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    series_description_cohort_key as series_description_cohort_key,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    series_description_edit_choices as series_description_edit_choices,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    series_description_group_choices as series_description_group_choices,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    series_description_is_harmonized as series_description_is_harmonized,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    study_description_edit_choices as study_description_edit_choices,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    study_description_edit_offer as study_description_edit_offer,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    study_description_group_choices as study_description_group_choices,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    study_harmonize_status as study_harmonize_status,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    study_loinc_prefix_for_edit as study_loinc_prefix_for_edit,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    study_ready_for_description_edit as study_ready_for_description_edit,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    study_root_for_series as study_root_for_series,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    study_series_description_fingerprint as study_series_description_fingerprint,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    tseg_series_paths_for_study as tseg_series_paths_for_study,
)
from anonymizer.controller.ai.harmonize.playbook import (
    PLAYBOOK_TREE_IIDS as PLAYBOOK_TREE_IIDS,
)
from anonymizer.controller.ai.harmonize.playbook import (
    PlaybookHarmonizeAttributes as PlaybookHarmonizeAttributes,
)
from anonymizer.controller.ai.harmonize.playbook import (
    build_localizer_playbook_attributes as build_localizer_playbook_attributes,
)
from anonymizer.controller.ai.harmonize.playbook import (
    harmonize_analysis_rows as harmonize_analysis_rows,
)
from anonymizer.controller.ai.harmonize.playbook import (
    harmonize_dicom_rows as harmonize_dicom_rows,
)
from anonymizer.controller.ai.harmonize.playbook import (
    is_localizer_geometry as is_localizer_geometry,
)
from anonymizer.controller.ai.harmonize.playbook import (
    playbook_body_part_row_values as playbook_body_part_row_values,
)
from anonymizer.controller.ai.harmonize.playbook import (
    playbook_iv_contrast_row_values as playbook_iv_contrast_row_values,
)
from anonymizer.controller.ai.harmonize.playbook import (
    playbook_plane_row_values as playbook_plane_row_values,
)
from anonymizer.controller.ai.harmonize.playbook import (
    playbook_series_type_modifier_row_values as playbook_series_type_modifier_row_values,
)
from anonymizer.controller.ai.harmonize.playbook import (
    playbook_series_type_row_values as playbook_series_type_row_values,
)
from anonymizer.controller.ai.harmonize.playbook import (
    playbook_slice_thickness_row_values as playbook_slice_thickness_row_values,
)
from anonymizer.controller.ai.harmonize.timings import HarmonizeStageTimings as HarmonizeStageTimings
from anonymizer.controller.ai.harmonize.timings import HarmonizeTimingCollector as HarmonizeTimingCollector

