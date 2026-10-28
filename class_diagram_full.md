# Full MVC class diagram (V19)

Generated from real `anonymizer.*` imports. **Strict MVC edges only**:
View → Controller, MCP → Controller, Controller → Model,
plus View/MCP → Model where those imports exist.
Same-layer and `utils` edges are omitted. Overview: [`class_diagram.md`](class_diagram.md).

Arrow `A --> B` means **A imports B**.

- Modules shown: **125**
- Strict cross-layer edges: **225**

```mermaid
flowchart TB
    subgraph CLIENTS[" "]
        direction LR

        subgraph VIEW["VIEW"]
            direction TB
            V_anonymizer["<b>anonymizer</b><br/>Anonymizer"]
            V_ai_ai_batch_process_dialog["<b>ai.ai_batch_process_dialog</b><br/>AiBatchProcessDialog"]
            V_ai_ai_batch_process_options_dialog["<b>ai.ai_batch_process_options_dialog</b><br/>AiBatchProcessOptionsResult<br/>AiBatchProcessOptionsDialog"]
            V_ai_blur_face_results["<b>ai.blur_face_results</b><br/>‹module›"]
            V_ai_face_blur_review_dialog["<b>ai.face_blur_review_dialog</b><br/>FaceBlurLoadError<br/>FaceBlurReviewOutcome<br/>FaceBlurReviewDialog"]
            V_ai_features_availability["<b>ai.features.availability</b><br/>DownloadCompleteEvent<br/>AiFeatureDownloadManager"]
            V_ai_features_catalog["<b>ai.features.catalog</b><br/>AiModelGroupSpec<br/>AiFeatureSpec"]
            V_ai_features_panel["<b>ai.features.panel</b><br/>AiFeaturesPanel"]
            V_ai_harmonize_description["<b>ai.harmonize_description</b><br/>‹module›"]
            V_ai_harmonize_results["<b>ai.harmonize_results</b><br/>HarmonizeSeriesItem<br/>HarmonizeSeriesOutcome<br/>HarmonizeBatchOutcome<br/>HarmonizeResultsView"]
            V_ai_harmonize_run_options_dialog["<b>ai.harmonize_run_options_dialog</b><br/>HarmonizeRunOptionsResult<br/>HarmonizeRunOptionsDialog"]
            V_ai_modality_whitelist_preview_dialog["<b>ai.modality_whitelist_preview_dialog</b><br/>ModalityWhitelistPreviewDialog"]
            V_ai_set_description_dialog["<b>ai.set_description_dialog</b><br/>SetDescriptionDialogResult<br/>RadLexComposeSpec<br/>SetDescriptionDialog"]
            V_common_job_poller["<b>common.job_poller</b><br/>JobPoller"]
            V_common_phi_action_labels["<b>common.phi_action_labels</b><br/>‹module›"]
            V_common_ux_fields["<b>common.ux_fields</b><br/>‹module›"]
            V_project_dataset["<b>project.dataset</b><br/>DatasetView"]
            V_project_delete_studies_dialog["<b>project.delete_studies_dialog</b><br/>DeleteStudiesDialog"]
            V_project_description_mappings["<b>project.description_mappings</b><br/>DescriptionMappingsDialog"]
            V_project_export["<b>project.export</b><br/>ExportView"]
            V_project_import_files_dialog["<b>project.import_files_dialog</b><br/>ImportFilesDialog"]
            V_project_import_studies_dialog["<b>project.import_studies_dialog</b><br/>ImportStudiesDialog"]
            V_project_query_retrieve_import["<b>project.query_retrieve_import</b><br/>QueryView"]
            V_reports_entity_colors["<b>reports.entity_colors</b><br/>‹module›"]
            V_reports_entity_legend["<b>reports.entity_legend</b><br/>EntityLegend"]
            V_reports_open_workspace["<b>reports.open_workspace</b><br/>‹module›"]
            V_reports_pdf_page_view["<b>reports.pdf_page_view</b><br/>PdfPageView"]
            V_reports_report_canvas["<b>reports.report_canvas</b><br/>ReportCanvas"]
            V_reports_report_text_review["<b>reports.report_text_review</b><br/>ReportTextReview"]
            V_series_anatomy_overlay["<b>series.anatomy_overlay</b><br/>‹module›"]
            V_series_image["<b>series.image</b><br/>ImageViewer"]
            V_series_metadata_assessment_dialog["<b>series.metadata_assessment_dialog</b><br/>MetadataTreePanel<br/>MetadataAssessmentDialog"]
            V_series_new_segment_dialog["<b>series.new_segment_dialog</b><br/>NewSegmentDialogResult<br/>NewSegmentDialog"]
            V_series_projection["<b>series.projection</b><br/>ProjectionView"]
            V_series_series["<b>series.series</b><br/>SeriesViewStartupSpec<br/>SeriesView"]
            V_series_series_overlay["<b>series.series_overlay</b><br/>‹module›"]
            V_settings_anonymizer_script_dialog["<b>settings.anonymizer_script_dialog</b><br/>AnonymizerScriptDialog<br/>OperandParamDialog<br/>AddFromDictionaryDialog"]
            V_settings_aws_cognito_dialog["<b>settings.aws_cognito_dialog</b><br/>AWSCognitoDialog"]
            V_settings_deidentification_options_dialog["<b>settings.deidentification_options_dialog</b><br/>DeidentificationOptionsDialog"]
            V_settings_dicom_node_dialog["<b>settings.dicom_node_dialog</b><br/>RemoteNodeFormValues<br/>DICOMNodeDialog"]
            V_settings_logging_levels_dialog["<b>settings.logging_levels_dialog</b><br/>LoggingLevelsDialog"]
            V_settings_lookup_table_dialog["<b>settings.lookup_table_dialog</b><br/>LookupTableDialog"]
            V_settings_modalites_dialog["<b>settings.modalites_dialog</b><br/>ModalitiesDialog"]
            V_settings_network_timeouts_dialog["<b>settings.network_timeouts_dialog</b><br/>NetworkTimeoutsDialog"]
            V_settings_script_editor["<b>settings.script_editor</b><br/>ScriptViewMode"]
            V_settings_settings_dialog["<b>settings.settings_dialog</b><br/>SettingsDialog"]
            V_settings_transfer_syntaxes_dialog["<b>settings.transfer_syntaxes_dialog</b><br/>TransferSyntaxesDialog"]
            V_shell_analytics_charts["<b>shell.analytics_charts</b><br/>ChartTheme<br/>WidgetSpec<br/>BoardPlacement<br/>BoardLayout<br/>BoardSections"]
            V_shell_dashboard["<b>shell.dashboard</b><br/>Dashboard"]
            V_anonymizer ~~~ V_ai_ai_batch_process_dialog
            V_ai_ai_batch_process_dialog ~~~ V_ai_ai_batch_process_options_dialog
            V_ai_ai_batch_process_options_dialog ~~~ V_ai_blur_face_results
            V_ai_blur_face_results ~~~ V_ai_face_blur_review_dialog
            V_ai_face_blur_review_dialog ~~~ V_ai_features_availability
            V_ai_features_availability ~~~ V_ai_features_catalog
            V_ai_features_catalog ~~~ V_ai_features_panel
            V_ai_features_panel ~~~ V_ai_harmonize_description
            V_ai_harmonize_description ~~~ V_ai_harmonize_results
            V_ai_harmonize_results ~~~ V_ai_harmonize_run_options_dialog
            V_ai_harmonize_run_options_dialog ~~~ V_ai_modality_whitelist_preview_dialog
            V_ai_modality_whitelist_preview_dialog ~~~ V_ai_set_description_dialog
            V_ai_set_description_dialog ~~~ V_common_job_poller
            V_common_job_poller ~~~ V_common_phi_action_labels
            V_common_phi_action_labels ~~~ V_common_ux_fields
            V_common_ux_fields ~~~ V_project_dataset
            V_project_dataset ~~~ V_project_delete_studies_dialog
            V_project_delete_studies_dialog ~~~ V_project_description_mappings
            V_project_description_mappings ~~~ V_project_export
            V_project_export ~~~ V_project_import_files_dialog
            V_project_import_files_dialog ~~~ V_project_import_studies_dialog
            V_project_import_studies_dialog ~~~ V_project_query_retrieve_import
            V_project_query_retrieve_import ~~~ V_reports_entity_colors
            V_reports_entity_colors ~~~ V_reports_entity_legend
            V_reports_entity_legend ~~~ V_reports_open_workspace
            V_reports_open_workspace ~~~ V_reports_pdf_page_view
            V_reports_pdf_page_view ~~~ V_reports_report_canvas
            V_reports_report_canvas ~~~ V_reports_report_text_review
            V_reports_report_text_review ~~~ V_series_anatomy_overlay
            V_series_anatomy_overlay ~~~ V_series_image
            V_series_image ~~~ V_series_metadata_assessment_dialog
            V_series_metadata_assessment_dialog ~~~ V_series_new_segment_dialog
            V_series_new_segment_dialog ~~~ V_series_projection
            V_series_projection ~~~ V_series_series
            V_series_series ~~~ V_series_series_overlay
            V_series_series_overlay ~~~ V_settings_anonymizer_script_dialog
            V_settings_anonymizer_script_dialog ~~~ V_settings_aws_cognito_dialog
            V_settings_aws_cognito_dialog ~~~ V_settings_deidentification_options_dialog
            V_settings_deidentification_options_dialog ~~~ V_settings_dicom_node_dialog
            V_settings_dicom_node_dialog ~~~ V_settings_logging_levels_dialog
            V_settings_logging_levels_dialog ~~~ V_settings_lookup_table_dialog
            V_settings_lookup_table_dialog ~~~ V_settings_modalites_dialog
            V_settings_modalites_dialog ~~~ V_settings_network_timeouts_dialog
            V_settings_network_timeouts_dialog ~~~ V_settings_script_editor
            V_settings_script_editor ~~~ V_settings_settings_dialog
            V_settings_settings_dialog ~~~ V_settings_transfer_syntaxes_dialog
            V_settings_transfer_syntaxes_dialog ~~~ V_shell_analytics_charts
            V_shell_analytics_charts ~~~ V_shell_dashboard
        end

        subgraph MCP["MCP"]
            direction TB
            M_api_schemas["<b>api.schemas</b><br/>EmptyArgs<br/>JobStatusArgs<br/>ProjectOpenArgs<br/>ImportDirectoryArgs<br/>ImportFileArgs<br/>PacsFindArgs<br/>PacsStudyRef<br/>PacsMoveArgs<br/>+3 more"]
            M_ops["<b>ops</b><br/>RemoteScpRole<br/>PacsMoveLevel<br/>PreviewImageFormat<br/>HeadlessOpsError"]
            M_session["<b>session</b><br/>ProjectSessionError<br/>ProjectSession"]
            M_snapshots["<b>snapshots</b><br/>‹module›"]
            M_api_schemas ~~~ M_ops
            M_ops ~~~ M_session
            M_session ~~~ M_snapshots
        end
    end

    subgraph CONTROLLER["CONTROLLER"]
        direction TB
            C_ai["<b>ai</b><br/>‹module›"]
            C_ai_batch_config["<b>ai.batch_config</b><br/>AiBatchConfigError<br/>AiBatchStudyRef<br/>AiBatchConfig"]
            C_ai_batch_process["<b>ai.batch_process</b><br/>AiBatchAlgorithm<br/>AiBatchProcessOptions<br/>AiBatchOutcome<br/>AiBatchAlgorithmTotals<br/>AiBatchSummary<br/>BatchRunCapture"]
            C_ai_blur_face["<b>ai.blur_face</b><br/>‹module›"]
            C_ai_blur_face_pipeline["<b>ai.blur_face.pipeline</b><br/>FaceBlurMode<br/>QaStats<br/>FaceBlurResult<br/>SeriesVolumeContext<br/>FaceBlurPreviewResult<br/>FaceBlurProgress"]
            C_ai_embedded_phi_classify_series["<b>ai.embedded_phi.classify_series</b><br/>SeriesKind"]
            C_ai_embedded_phi_entity_labels["<b>ai.embedded_phi.entity_labels</b><br/>‹module›"]
            C_ai_embedded_phi_metadata_detect["<b>ai.embedded_phi.metadata.detect</b><br/>‹module›"]
            C_ai_embedded_phi_metadata_extract["<b>ai.embedded_phi.metadata.extract</b><br/>SpanFragment<br/>MetadataPhiRow"]
            C_ai_embedded_phi_metadata_viewer_tree["<b>ai.embedded_phi.metadata.viewer_tree</b><br/>MetadataTreeNode"]
            C_ai_embedded_phi_ner_cache["<b>ai.embedded_phi.ner.cache</b><br/>NerModelOptions<br/>NerModelStatus"]
            C_ai_embedded_phi_ner_engine["<b>ai.embedded_phi.ner.engine</b><br/>Entity"]
            C_ai_embedded_phi_ner_radiology_filters["<b>ai.embedded_phi.ner.radiology_filters</b><br/>FilterHit<br/>MaskResult<br/>MetadataNerItem<br/>PreparedMetadataSegment"]
            C_ai_embedded_phi_pixel_cache["<b>ai.embedded_phi.pixel.cache</b><br/>OcrModelStatus"]
            C_ai_embedded_phi_pixel_detect_text["<b>ai.embedded_phi.pixel.detect_text</b><br/>OcrWhitelistMatchMode<br/>OcrWhitelistMatchSettings<br/>WhitelistMatchResult<br/>PixelPhiRemovalMode"]
            C_ai_embedded_phi_pixel_remove_pixel_phi["<b>ai.embedded_phi.pixel.remove_pixel_phi</b><br/>‹module›"]
            C_ai_embedded_phi_report_process_report_text["<b>ai.embedded_phi.report.process_report_text</b><br/>‹module›"]
            C_ai_feature_availability["<b>ai.feature_availability</b><br/>‹module›"]
            C_ai_feature_ids["<b>ai.feature_ids</b><br/>AiFeatureId<br/>AiModelGroupId"]
            C_ai_harmonize["<b>ai.harmonize</b><br/>‹module›"]
            C_ai_harmonize_description_mapping_store["<b>ai.harmonize.description_mapping_store</b><br/>SeriesDescriptionOverride<br/>StudyDescriptionOverride"]
            C_ai_harmonize_loinc_study["<b>ai.harmonize.loinc_study</b><br/>LoincStudyMatch<br/>StudyDescriptionAggregate<br/>StudyDescriptionOffer"]
            C_ai_harmonize_pipeline["<b>ai.harmonize.pipeline</b><br/>HarmonizeProgressStage<br/>HarmonizeProgress<br/>HarmonizedResult<br/>HarmonizeApplyOutcome<br/>HarmonizeStudiesSummary<br/>DescriptionEditSelection"]
            C_ai_harmonize_playbook["<b>ai.harmonize.playbook</b><br/>MetadataHarmonizeRoute<br/>PlaybookHarmonizeAttributes"]
            C_ai_harmonize_playbook_planar["<b>ai.harmonize.playbook_planar</b><br/>PlanarPlaybookAttributes"]
            C_ai_harmonize_xp_bodypart["<b>ai.harmonize.xp_bodypart</b><br/>‹module›"]
            C_ai_harmonize_xp_bodypart_preprocess["<b>ai.harmonize.xp_bodypart.preprocess</b><br/>‹module›"]
            C_ai_harmonize_xr_chest_view["<b>ai.harmonize.xr_chest_view</b><br/>‹module›"]
            C_ai_model_download["<b>ai.model_download</b><br/>DownloadProgress"]
            C_ai_tseg_config["<b>ai.tseg.config</b><br/>‹module›"]
            C_ai_tseg_dicom_geometry["<b>ai.tseg.dicom_geometry</b><br/>SeriesGeometryResult"]
            C_ai_tseg_model_cache["<b>ai.tseg.model_cache</b><br/>‹module›"]
            C_ai_tseg_readiness["<b>ai.tseg.readiness</b><br/>‹module›"]
            C_ai_tseg_seg_retention["<b>ai.tseg.seg_retention</b><br/>‹module›"]
            C_analytics_dataset["<b>analytics.dataset</b><br/>CountBucket<br/>Distribution<br/>OrganVolumeSample<br/>OrganVolumeDistribution<br/>AgeHistogram<br/>DemographicsAnalytics<br/>ImagingAnalytics<br/>AnatomyAnalytics<br/>+2 more"]
            C_analytics_prefs["<b>analytics.prefs</b><br/>‹module›"]
            C_annotations["<b>annotations</b><br/>‹module›"]
            C_annotations_store["<b>annotations.store</b><br/>LabelEntry<br/>StrokeUndo<br/>AnnotateSession"]
            C_anonymizer["<b>anonymizer</b><br/>QuarantineDirectories<br/>LookupTableMissError<br/>AnonymizerController"]
            C_ctp_lookup["<b>ctp_lookup</b><br/>LookupPropertiesError<br/>LookupPatientRow<br/>ScriptTagChange<br/>ScriptPatchResult<br/>CtpLookupPreview<br/>LookupTableContext"]
            C_dates["<b>dates</b><br/>‹module›"]
            C_dicom["<b>dicom</b><br/>‹module›"]
            C_dicom_association["<b>dicom.association</b><br/>AssociationMixin"]
            C_dicom_dicomweb_qido["<b>dicom.dicomweb.qido</b><br/>‹module›"]
            C_dicom_dicomweb_session["<b>dicom.dicomweb.session</b><br/>DicomWebSession"]
            C_dicom_dicomweb_stow["<b>dicom.dicomweb.stow</b><br/>‹module›"]
            C_dicom_dicomweb_wado["<b>dicom.dicomweb.wado</b><br/>‹module›"]
            C_dicom_echo_scu["<b>dicom.echo_scu</b><br/>EchoMixin"]
            C_dicom_find_scu["<b>dicom.find_scu</b><br/>FindMixin"]
            C_dicom_hierarchies["<b>dicom.hierarchies</b><br/>InstanceUIDHierarchy<br/>SeriesUIDHierarchy<br/>StudyUIDHierarchy"]
            C_dicom_requests["<b>dicom.requests</b><br/>EchoRequest<br/>EchoResponse<br/>FindStudyRequest<br/>FindStudyResponse<br/>MoveStudiesRequest<br/>ExportPatientsRequest<br/>ExportPatientsResponse"]
            C_dicom_retrieve_scu["<b>dicom.retrieve_scu</b><br/>RetrieveMixin"]
            C_dicom_scp["<b>dicom.scp</b><br/>ScpMixin"]
            C_dicom_store_scu["<b>dicom.store_scu</b><br/>StoreMixin"]
            C_headless["<b>headless</b><br/>‹module›"]
            C_jobs_runner["<b>jobs.runner</b><br/>OcrEditContext<br/>OcrRemoveMode<br/>RunOptions<br/>ModelHandle<br/>BatchSpec<br/>BatchSummary<br/>Runner<br/>RemovePixelPhiRunner<br/>+2 more"]
            C_jobs_work_state["<b>jobs.work_state</b><br/>Algorithm<br/>WorkState"]
            C_phi_phi_io["<b>phi.phi_io</b><br/>PHI_SeriesIndexRecord<br/>PHI_IndexRecord"]
            C_project["<b>project</b><br/>ImportPathsResult<br/>ProjectController"]
            C_script_date_rules["<b>script.date_rules</b><br/>‹module›"]
            C_script_document["<b>script.document</b><br/>ScriptRule<br/>ScriptRRule<br/>ScriptDocument"]
            C_script_operands["<b>script.operands</b><br/>OperandId<br/>OperandSpec"]
            C_script_option_explanations["<b>script.option_explanations</b><br/>DeidOptionExplanation"]
            C_script_options["<b>script.options</b><br/>‹module›"]
            C_script_paths["<b>script.paths</b><br/>‹module›"]
            C_series_create_projections["<b>series.create_projections</b><br/>Projection<br/>ProjectionImageSizeConfig<br/>ProjectionImageSize"]
            C_series_series_io["<b>series.series_io</b><br/>SeriesProjections<br/>LoadedSeries"]
            C_series_series_overlay["<b>series.series_overlay</b><br/>LayerType<br/>OCRText<br/>UserRectangle<br/>PolygonPoint<br/>Segmentation<br/>OverlayData"]
            C_series_workspace["<b>series.workspace</b><br/>SeriesLoadError<br/>SeriesWorkspaceLoad<br/>SeriesViewSaveRequest<br/>SeriesViewSaveResult<br/>OcrFrameRemoveResult<br/>SeriesWorkspace"]
            C_ai ~~~ C_ai_batch_config
            C_ai_batch_config ~~~ C_ai_batch_process
            C_ai_batch_process ~~~ C_ai_blur_face
            C_ai_blur_face ~~~ C_ai_blur_face_pipeline
            C_ai_blur_face_pipeline ~~~ C_ai_embedded_phi_classify_series
            C_ai_embedded_phi_classify_series ~~~ C_ai_embedded_phi_entity_labels
            C_ai_embedded_phi_entity_labels ~~~ C_ai_embedded_phi_metadata_detect
            C_ai_embedded_phi_metadata_detect ~~~ C_ai_embedded_phi_metadata_extract
            C_ai_embedded_phi_metadata_extract ~~~ C_ai_embedded_phi_metadata_viewer_tree
            C_ai_embedded_phi_metadata_viewer_tree ~~~ C_ai_embedded_phi_ner_cache
            C_ai_embedded_phi_ner_cache ~~~ C_ai_embedded_phi_ner_engine
            C_ai_embedded_phi_ner_engine ~~~ C_ai_embedded_phi_ner_radiology_filters
            C_ai_embedded_phi_ner_radiology_filters ~~~ C_ai_embedded_phi_pixel_cache
            C_ai_embedded_phi_pixel_cache ~~~ C_ai_embedded_phi_pixel_detect_text
            C_ai_embedded_phi_pixel_detect_text ~~~ C_ai_embedded_phi_pixel_remove_pixel_phi
            C_ai_embedded_phi_pixel_remove_pixel_phi ~~~ C_ai_embedded_phi_report_process_report_text
            C_ai_embedded_phi_report_process_report_text ~~~ C_ai_feature_availability
            C_ai_feature_availability ~~~ C_ai_feature_ids
            C_ai_feature_ids ~~~ C_ai_harmonize
            C_ai_harmonize ~~~ C_ai_harmonize_description_mapping_store
            C_ai_harmonize_description_mapping_store ~~~ C_ai_harmonize_loinc_study
            C_ai_harmonize_loinc_study ~~~ C_ai_harmonize_pipeline
            C_ai_harmonize_pipeline ~~~ C_ai_harmonize_playbook
            C_ai_harmonize_playbook ~~~ C_ai_harmonize_playbook_planar
            C_ai_harmonize_playbook_planar ~~~ C_ai_harmonize_xp_bodypart
            C_ai_harmonize_xp_bodypart ~~~ C_ai_harmonize_xp_bodypart_preprocess
            C_ai_harmonize_xp_bodypart_preprocess ~~~ C_ai_harmonize_xr_chest_view
            C_ai_harmonize_xr_chest_view ~~~ C_ai_model_download
            C_ai_model_download ~~~ C_ai_tseg_config
            C_ai_tseg_config ~~~ C_ai_tseg_dicom_geometry
            C_ai_tseg_dicom_geometry ~~~ C_ai_tseg_model_cache
            C_ai_tseg_model_cache ~~~ C_ai_tseg_readiness
            C_ai_tseg_readiness ~~~ C_ai_tseg_seg_retention
            C_ai_tseg_seg_retention ~~~ C_analytics_dataset
            C_analytics_dataset ~~~ C_analytics_prefs
            C_analytics_prefs ~~~ C_annotations
            C_annotations ~~~ C_annotations_store
            C_annotations_store ~~~ C_anonymizer
            C_anonymizer ~~~ C_ctp_lookup
            C_ctp_lookup ~~~ C_dates
            C_dates ~~~ C_dicom
            C_dicom ~~~ C_dicom_association
            C_dicom_association ~~~ C_dicom_dicomweb_qido
            C_dicom_dicomweb_qido ~~~ C_dicom_dicomweb_session
            C_dicom_dicomweb_session ~~~ C_dicom_dicomweb_stow
            C_dicom_dicomweb_stow ~~~ C_dicom_dicomweb_wado
            C_dicom_dicomweb_wado ~~~ C_dicom_echo_scu
            C_dicom_echo_scu ~~~ C_dicom_find_scu
            C_dicom_find_scu ~~~ C_dicom_hierarchies
            C_dicom_hierarchies ~~~ C_dicom_requests
            C_dicom_requests ~~~ C_dicom_retrieve_scu
            C_dicom_retrieve_scu ~~~ C_dicom_scp
            C_dicom_scp ~~~ C_dicom_store_scu
            C_dicom_store_scu ~~~ C_headless
            C_headless ~~~ C_jobs_runner
            C_jobs_runner ~~~ C_jobs_work_state
            C_jobs_work_state ~~~ C_phi_phi_io
            C_phi_phi_io ~~~ C_project
            C_project ~~~ C_script_date_rules
            C_script_date_rules ~~~ C_script_document
            C_script_document ~~~ C_script_operands
            C_script_operands ~~~ C_script_option_explanations
            C_script_option_explanations ~~~ C_script_options
            C_script_options ~~~ C_script_paths
            C_script_paths ~~~ C_series_create_projections
            C_series_create_projections ~~~ C_series_series_io
            C_series_series_io ~~~ C_series_series_overlay
            C_series_series_overlay ~~~ C_series_workspace
    end

    subgraph MODEL["MODEL"]
        direction TB
            M_anonymizer["<b>anonymizer</b><br/>Base<br/>Instance<br/>Series<br/>Study<br/>PHI<br/>UID<br/>CtpLookupPhiRow<br/>StudyPhiHeader<br/>+4 more"]
            M_project["<b>project</b><br/>DICOMRuntimeError<br/>AuthenticationError<br/>DICOMNode<br/>NetworkTimeouts<br/>LoggingLevels<br/>AWSCognito<br/>ProjectModel"]
            M_settings_validate["<b>settings_validate</b><br/>SettingsValidationError"]
            M_anonymizer ~~~ M_project
            M_project ~~~ M_settings_validate
    end

    %% Strict MVC import edges (A imports B)
    V_anonymizer --> C_ai_batch_config
    V_anonymizer --> C_ai_batch_process
    V_anonymizer --> C_ai_embedded_phi_ner_cache
    V_anonymizer --> C_ai_embedded_phi_pixel_cache
    V_anonymizer --> C_ai_harmonize_description_mapping_store
    V_anonymizer --> C_ai_tseg_config
    V_anonymizer --> C_ai_tseg_readiness
    V_anonymizer --> C_analytics_prefs
    V_anonymizer --> C_ctp_lookup
    V_anonymizer --> C_headless
    V_anonymizer --> C_project
    V_anonymizer --> M_project
    C_ai_batch_config --> M_anonymizer
    C_ai_batch_process --> M_anonymizer
    C_ai_batch_process --> M_project
    C_ai_embedded_phi_pixel_remove_pixel_phi --> M_anonymizer
    C_ai_feature_availability --> M_project
    C_ai_harmonize_pipeline --> M_anonymizer
    C_analytics_dataset --> M_anonymizer
    C_anonymizer --> M_anonymizer
    C_anonymizer --> M_project
    C_ctp_lookup --> M_anonymizer
    C_ctp_lookup --> M_project
    C_dicom_association --> M_project
    C_dicom_dicomweb_qido --> M_project
    C_dicom_dicomweb_session --> M_project
    C_dicom_dicomweb_stow --> M_project
    C_dicom_dicomweb_wado --> M_project
    C_dicom_echo_scu --> M_project
    C_dicom_find_scu --> M_project
    C_dicom_requests --> M_project
    C_dicom_retrieve_scu --> M_project
    C_dicom_scp --> M_project
    C_dicom_store_scu --> M_project
    C_headless --> M_project
    C_phi_phi_io --> M_anonymizer
    C_project --> M_anonymizer
    C_project --> M_project
    C_script_options --> M_project
    C_script_paths --> M_project
    C_series_workspace --> M_anonymizer
    M_api_schemas --> M_project
    M_api_schemas --> M_settings_validate
    M_ops --> C_ai_batch_process
    M_ops --> C_ai_embedded_phi_pixel_detect_text
    M_ops --> C_ai_harmonize
    M_ops --> C_ai_harmonize_xp_bodypart_preprocess
    M_ops --> C_dicom_hierarchies
    M_ops --> C_dicom_requests
    M_ops --> C_jobs_runner
    M_ops --> C_project
    M_ops --> C_script_options
    M_ops --> C_script_paths
    M_ops --> C_series_series_io
    M_ops --> M_anonymizer
    M_ops --> M_project
    M_ops --> M_settings_validate
    M_session --> C_headless
    M_session --> C_jobs_runner
    M_session --> C_project
    M_session --> C_script_paths
    M_session --> M_project
    M_snapshots --> C_dicom_hierarchies
    M_snapshots --> C_project
    M_snapshots --> M_project
    M_snapshots --> M_settings_validate
    V_ai_ai_batch_process_dialog --> C_ai_batch_process
    V_ai_ai_batch_process_dialog --> C_ai_tseg_config
    V_ai_ai_batch_process_dialog --> C_jobs_work_state
    V_ai_ai_batch_process_dialog --> C_project
    V_ai_ai_batch_process_options_dialog --> C_ai_batch_process
    V_ai_ai_batch_process_options_dialog --> C_ai_blur_face
    V_ai_ai_batch_process_options_dialog --> C_ai_embedded_phi_pixel_detect_text
    V_ai_ai_batch_process_options_dialog --> C_ai_feature_availability
    V_ai_ai_batch_process_options_dialog --> C_ai_feature_ids
    V_ai_ai_batch_process_options_dialog --> C_ai_harmonize_description_mapping_store
    V_ai_ai_batch_process_options_dialog --> C_jobs_runner
    V_ai_blur_face_results --> C_ai_blur_face
    V_ai_face_blur_review_dialog --> C_ai_blur_face
    V_ai_face_blur_review_dialog --> C_ai_tseg_dicom_geometry
    V_ai_face_blur_review_dialog --> C_jobs_runner
    V_ai_face_blur_review_dialog --> C_jobs_work_state
    V_ai_face_blur_review_dialog --> C_series_create_projections
    V_ai_face_blur_review_dialog --> C_series_series_io
    V_ai_face_blur_review_dialog --> C_series_series_overlay
    V_ai_face_blur_review_dialog --> M_anonymizer
    V_ai_features_availability --> C_ai
    V_ai_features_availability --> C_ai_embedded_phi_ner_cache
    V_ai_features_availability --> C_ai_embedded_phi_pixel_cache
    V_ai_features_availability --> C_ai_feature_ids
    V_ai_features_availability --> C_ai_model_download
    V_ai_features_availability --> C_ai_tseg_config
    V_ai_features_availability --> C_ai_tseg_model_cache
    V_ai_features_availability --> C_ai_tseg_readiness
    V_ai_features_catalog --> C_ai_embedded_phi_ner_cache
    V_ai_features_catalog --> C_ai_embedded_phi_pixel_cache
    V_ai_features_catalog --> C_ai_feature_ids
    V_ai_features_catalog --> C_ai_harmonize_xp_bodypart
    V_ai_features_catalog --> C_ai_harmonize_xr_chest_view
    V_ai_features_catalog --> C_ai_tseg_readiness
    V_ai_features_panel --> C_ai_feature_availability
    V_ai_features_panel --> C_ai_feature_ids
    V_ai_features_panel --> C_ai_harmonize_xp_bodypart
    V_ai_features_panel --> C_ai_harmonize_xr_chest_view
    V_ai_features_panel --> C_ai_model_download
    V_ai_features_panel --> C_ai_tseg_config
    V_ai_features_panel --> C_ai_tseg_readiness
    V_ai_harmonize_description --> C_ai_feature_availability
    V_ai_harmonize_results --> C_ai_blur_face_pipeline
    V_ai_harmonize_results --> C_ai_feature_availability
    V_ai_harmonize_results --> C_ai_harmonize
    V_ai_harmonize_results --> C_ai_harmonize_description_mapping_store
    V_ai_harmonize_results --> C_ai_harmonize_playbook
    V_ai_harmonize_results --> C_ai_harmonize_playbook_planar
    V_ai_harmonize_results --> C_ai_tseg_config
    V_ai_harmonize_results --> C_ai_tseg_model_cache
    V_ai_harmonize_results --> C_jobs_runner
    V_ai_harmonize_results --> C_jobs_work_state
    V_ai_harmonize_results --> M_anonymizer
    V_ai_harmonize_run_options_dialog --> C_ai_feature_ids
    V_ai_harmonize_run_options_dialog --> C_ai_harmonize_description_mapping_store
    V_ai_modality_whitelist_preview_dialog --> C_ai_batch_process
    V_ai_modality_whitelist_preview_dialog --> C_ai_embedded_phi_pixel_detect_text
    V_ai_set_description_dialog --> C_ai_harmonize_playbook
    V_common_job_poller --> C_jobs_runner
    V_common_job_poller --> C_jobs_work_state
    V_common_phi_action_labels --> C_ai_embedded_phi_ner_engine
    V_common_ux_fields --> M_settings_validate
    V_project_dataset --> C_ai_feature_availability
    V_project_dataset --> C_ai_harmonize
    V_project_dataset --> C_ai_harmonize_description_mapping_store
    V_project_dataset --> C_phi_phi_io
    V_project_dataset --> C_project
    V_project_delete_studies_dialog --> C_project
    V_project_description_mappings --> C_ai_harmonize_description_mapping_store
    V_project_description_mappings --> C_ai_harmonize_loinc_study
    V_project_export --> C_annotations
    V_project_export --> C_dicom_requests
    V_project_export --> C_project
    V_project_export --> M_project
    V_project_import_files_dialog --> C_anonymizer
    V_project_import_studies_dialog --> C_dicom_hierarchies
    V_project_import_studies_dialog --> C_dicom_requests
    V_project_import_studies_dialog --> C_project
    V_project_query_retrieve_import --> C_dicom_hierarchies
    V_project_query_retrieve_import --> C_dicom_requests
    V_project_query_retrieve_import --> C_project
    V_reports_entity_colors --> C_ai_embedded_phi_entity_labels
    V_reports_entity_colors --> C_ai_embedded_phi_ner_engine
    V_reports_entity_colors --> C_ai_embedded_phi_report_process_report_text
    V_reports_entity_legend --> C_ai_embedded_phi_ner_engine
    V_reports_open_workspace --> C_ai_embedded_phi_classify_series
    V_reports_open_workspace --> C_project
    V_reports_pdf_page_view --> C_ai_embedded_phi_report_process_report_text
    V_reports_report_canvas --> C_ai_embedded_phi_ner_engine
    V_reports_report_text_review --> C_ai_embedded_phi_ner_engine
    V_reports_report_text_review --> C_ai_embedded_phi_report_process_report_text
    V_reports_report_text_review --> C_ai_feature_availability
    V_reports_report_text_review --> C_project
    V_series_anatomy_overlay --> C_ai_tseg_config
    V_series_anatomy_overlay --> C_ai_tseg_seg_retention
    V_series_anatomy_overlay --> C_series_series_overlay
    V_series_image --> C_ai_tseg_config
    V_series_image --> C_series_series_io
    V_series_image --> C_series_series_overlay
    V_series_metadata_assessment_dialog --> C_ai_embedded_phi_metadata_detect
    V_series_metadata_assessment_dialog --> C_ai_embedded_phi_metadata_extract
    V_series_metadata_assessment_dialog --> C_ai_embedded_phi_metadata_viewer_tree
    V_series_metadata_assessment_dialog --> C_ai_embedded_phi_ner_engine
    V_series_metadata_assessment_dialog --> C_ai_embedded_phi_ner_radiology_filters
    V_series_metadata_assessment_dialog --> C_ai_embedded_phi_pixel_detect_text
    V_series_metadata_assessment_dialog --> C_ai_embedded_phi_report_process_report_text
    V_series_metadata_assessment_dialog --> C_ai_feature_availability
    V_series_new_segment_dialog --> C_ai_tseg_config
    V_series_new_segment_dialog --> C_analytics_dataset
    V_series_new_segment_dialog --> C_annotations_store
    V_series_projection --> C_phi_phi_io
    V_series_projection --> C_project
    V_series_projection --> C_series_create_projections
    V_series_series --> C_project
    V_series_series --> C_series_series_io
    V_series_series --> C_series_series_overlay
    V_series_series --> C_series_workspace
    V_series_series_overlay --> C_series_series_overlay
    V_settings_anonymizer_script_dialog --> C_ctp_lookup
    V_settings_anonymizer_script_dialog --> C_dates
    V_settings_anonymizer_script_dialog --> C_project
    V_settings_anonymizer_script_dialog --> C_script_date_rules
    V_settings_anonymizer_script_dialog --> C_script_document
    V_settings_anonymizer_script_dialog --> C_script_operands
    V_settings_anonymizer_script_dialog --> C_script_option_explanations
    V_settings_anonymizer_script_dialog --> C_script_options
    V_settings_anonymizer_script_dialog --> C_script_paths
    V_settings_anonymizer_script_dialog --> M_project
    V_settings_aws_cognito_dialog --> M_project
    V_settings_deidentification_options_dialog --> C_ai_feature_availability
    V_settings_deidentification_options_dialog --> C_ai_feature_ids
    V_settings_deidentification_options_dialog --> C_script_option_explanations
    V_settings_deidentification_options_dialog --> M_project
    V_settings_dicom_node_dialog --> C_dicom
    V_settings_dicom_node_dialog --> C_dicom_requests
    V_settings_dicom_node_dialog --> C_project
    V_settings_dicom_node_dialog --> M_project
    V_settings_logging_levels_dialog --> M_project
    V_settings_lookup_table_dialog --> C_ctp_lookup
    V_settings_lookup_table_dialog --> C_project
    V_settings_lookup_table_dialog --> C_script_document
    V_settings_modalites_dialog --> M_project
    V_settings_network_timeouts_dialog --> M_project
    V_settings_script_editor --> C_script_date_rules
    V_settings_script_editor --> C_script_document
    V_settings_script_editor --> C_script_operands
    V_settings_settings_dialog --> C_ctp_lookup
    V_settings_settings_dialog --> C_project
    V_settings_settings_dialog --> C_script_options
    V_settings_settings_dialog --> C_script_paths
    V_settings_settings_dialog --> M_project
    V_settings_transfer_syntaxes_dialog --> M_project
    V_shell_analytics_charts --> C_analytics_dataset
    V_shell_analytics_charts --> C_analytics_prefs
    V_shell_dashboard --> C_analytics_dataset
    V_shell_dashboard --> C_analytics_prefs
    V_shell_dashboard --> C_dicom_requests
    V_shell_dashboard --> C_project
    V_shell_dashboard --> M_anonymizer
```

## Edge legend

| Direction | Meaning | Count |
| --- | --- | ---: |
| view → controller | GUI View imports Controller | 156 |
| mcp → controller | MCP imports Controller | 17 |
| controller → model | Controller imports Model | 29 |
| view → model | View imports Model (Settings / create paths) | 15 |
| mcp → model | MCP imports Model (project open/create) | 8 |

## Notes

- Module labels drop the layer prefix (`view.`, `controller.`, …); the subgraph is the layer.
- Public classes are listed (up to 8 per module). Private `_` classes omitted.
- Same-layer wiring is omitted here; see the overview diagram.
- Regenerate: `python3 docs/dev/generate_class_diagram_full.py`
