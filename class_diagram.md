# Class diagram (V19)

MVC layout of the shipped `rsna-anonymizer` package. Each box is one module (or tight package); **module names are bold** (layer prefix omitted — the subgraph is the layer). Attributes, methods, and DTO field detail are omitted.

For **real cross-layer import edges** (View/MCP → Controller → Model), see [`class_diagram_full.md`](class_diagram_full.md).

```mermaid
flowchart TB
    subgraph CLIENTS[" "]
        direction LR

        subgraph VIEW["VIEW"]
            direction TB
            V_APP["<b>anonymizer</b><br/>Anonymizer"]
            V_SHELL["<b>shell</b><br/>WelcomeView<br/>Dashboard<br/>ChartTheme · BoardLayout"]
            V_PROJECT["<b>project</b><br/>DatasetView<br/>DescriptionMappingsDialog<br/>QueryView<br/>ExportView<br/>DeleteStudiesDialog<br/>ImportStudiesDialog<br/>ImportFilesDialog"]
            V_SERIES["<b>series</b><br/>SeriesView<br/>SeriesViewStartupSpec<br/>ProjectionView<br/>ImageViewer<br/>Histogram<br/>MetadataAssessmentDialog<br/>MetadataTreePanel<br/>NewSegmentDialog"]
            V_REPORTS["<b>reports</b><br/>ReportTextReview<br/>PdfPageView<br/>ReportCanvas<br/>EntityLegend<br/>open_workspace"]
            V_SETTINGS["<b>settings</b><br/>SettingsDialog<br/>DeidentificationOptionsDialog<br/>AnonymizerScriptDialog<br/>DICOMNodeDialog<br/>SOPClassesDialog<br/>TransferSyntaxesDialog<br/>ModalitiesDialog<br/>NetworkTimeoutsDialog<br/>LookupTableDialog<br/>AWSCognitoDialog<br/>LoggingLevelsDialog"]
            V_AI["<b>ai</b><br/>AiFeaturesSetupDialog<br/>AiBatchProcessDialog<br/>AiBatchProcessOptionsDialog<br/>HarmonizeResultsView<br/>HarmonizeRunOptionsDialog<br/>FaceBlurReviewDialog<br/>SetDescriptionDialog<br/>ModalityWhitelistPreviewDialog"]
            V_AI_FEAT["<b>ai.features</b><br/>AiFeaturesPanel<br/>AiFeatureDownloadManager<br/>AiFeatureSpec<br/>AiModelGroupSpec"]
            V_COMMON["<b>common</b><br/>AppToplevel<br/>AppCTkToplevel<br/>AppMenuHost<br/>AppFonts<br/>JobPoller<br/>HTMLView<br/>HoverTooltipBinding"]
            V_APP --- V_SHELL
            V_APP --- V_PROJECT
            V_APP --- V_SERIES
            V_APP --- V_REPORTS
            V_APP --- V_SETTINGS
            V_APP --- V_AI
            V_APP --- V_COMMON
            V_AI --- V_AI_FEAT
        end

        subgraph MCP["MCP"]
            direction TB
            M_SESSION["<b>session</b><br/>ProjectSession<br/>ProjectSessionError"]
            M_OPS["<b>ops</b><br/>RemoteScpRole<br/>PacsMoveLevel<br/>HeadlessOpsError"]
            M_API["<b>api</b><br/>ToolSpec<br/>schemas · catalog"]
            M_MW["<b>middleware</b><br/>McpCallLoggingMiddleware"]
            M_SESSION --- M_OPS
            M_OPS --- M_API
            M_SESSION --- M_MW
        end
    end

    subgraph CONTROLLER["CONTROLLER"]
        direction TB
        C_PROJECT["<b>project</b><br/>ProjectController<br/>ImportPathsResult"]
        C_ANON["<b>anonymizer</b><br/>AnonymizerController<br/>QuarantineDirectories<br/>LookupTableMissError"]
        C_SCRIPT["<b>script</b><br/>ScriptDocument · ScriptRule<br/>OperandId · OperandSpec<br/>DeidOptionExplanation<br/>RetainTagEntry<br/>compile · options · document"]
        C_SERIES["<b>series</b><br/>SeriesWorkspace<br/>SeriesWorkspaceLoad<br/>LoadedSeries · SeriesProjections<br/>Projection · OverlayData<br/>OCRText · UserRectangle<br/>Segmentation"]
        C_DICOM["<b>dicom</b><br/>AssociationMixin<br/>EchoMixin · FindMixin<br/>RetrieveMixin · StoreMixin<br/>ScpMixin<br/>StudyUIDHierarchy<br/>EchoRequest · FindStudyRequest<br/>DicomWebSession"]
        C_PRIVATE["<b>private_tags</b><br/>PrivateTagEntry<br/>PrivateTagAction<br/>TCIA KB lookup"]
        C_PHI_IO["<b>phi</b><br/>PHI_IndexRecord<br/>PHI_SeriesIndexRecord"]
        C_CTP["<b>ctp_lookup</b><br/>CtpLookupPreview<br/>LookupPatientRow<br/>LookupTableContext<br/>ScriptPatchResult"]
        C_JOBS["<b>jobs</b><br/>WorkState · Algorithm<br/>Runner<br/>RemovePixelPhiRunner<br/>HarmonizeRunner<br/>FaceBlurRunner<br/>RunOptions · BatchSpec"]
        C_ANALYTICS["<b>analytics</b><br/>DatasetAnalytics<br/>DemographicsAnalytics<br/>ImagingAnalytics<br/>AnatomyAnalytics<br/>SeriesLedgerRow"]
        C_ANNOT["<b>annotations</b><br/>AnnotateSession<br/>LabelEntry<br/>ImportProfile · ImportResult"]
        C_BATCH["<b>ai.batch</b><br/>AiBatchConfig<br/>AiBatchProcessOptions<br/>AiBatchOutcome<br/>AiBatchSummary<br/>AiBatchAlgorithm"]
        C_HARM["<b>ai.harmonize</b><br/>HarmonizeProgress<br/>HarmonizedResult<br/>PlaybookHarmonizeAttributes<br/>PlanarPlaybookAttributes<br/>LoincStudyMatch<br/>SeriesDescriptionOverride<br/>StudyDescriptionOverride"]
        C_TSEG["<b>ai.tseg</b><br/>AnalysisProgress<br/>RegionResult · TS_result<br/>FaceSegResult<br/>TsSuitability<br/>ContrastResult<br/>SeriesGeometryResult<br/>FaceBlurEligibility"]
        C_FACE["<b>ai.blur_face</b><br/>FaceBlurMode<br/>FaceBlurResult<br/>FaceBlurPreviewResult<br/>QaStats · FaceBlurProgress"]
        C_EPHI["<b>ai.embedded_phi</b><br/>SeriesKind<br/>Entity · NerModelOptions<br/>PixelPhiRemovalMode<br/>MetadataPhiRow<br/>MetadataTreeNode<br/>QcSeriesReport"]
        C_PROJECT --- C_ANON
        C_PROJECT --- C_SCRIPT
        C_PROJECT --- C_SERIES
        C_PROJECT --- C_DICOM
        C_PROJECT --- C_PRIVATE
        C_PROJECT --- C_PHI_IO
        C_PROJECT --- C_CTP
        C_PROJECT --- C_JOBS
        C_PROJECT --- C_ANALYTICS
        C_PROJECT --- C_ANNOT
        C_PROJECT --- C_BATCH
        C_ANON --- C_SCRIPT
        C_ANON --- C_PRIVATE
        C_BATCH --- C_HARM
        C_BATCH --- C_FACE
        C_BATCH --- C_EPHI
        C_JOBS --- C_HARM
        C_JOBS --- C_FACE
        C_JOBS --- C_EPHI
        C_HARM --- C_TSEG
        C_FACE --- C_TSEG
        C_SERIES --- C_EPHI
    end

    subgraph MODEL["MODEL"]
        direction TB
        M_PROJECT["<b>project</b><br/>ProjectModel<br/>DICOMNode<br/>NetworkTimeouts<br/>LoggingLevels<br/>AWSCognito<br/>DICOMRuntimeError<br/>AuthenticationError"]
        M_ANON["<b>anonymizer</b><br/>AnonymizerModel<br/>Base<br/>PHI · Study · Series<br/>Instance · UID<br/>CtpLookupPhiRow<br/>StudyPhiHeader<br/>Totals<br/>SeriesProcessingStatus<br/>MissingSessionError"]
        M_VALIDATE["<b>settings_validate</b><br/>SettingsValidationError"]
        M_PROJECT --- M_ANON
        M_PROJECT --- M_VALIDATE
    end

    VIEW --> CONTROLLER
    MCP --> CONTROLLER
    CONTROLLER --> MODEL
```

## Layer rules

| Layer | Owns | Must not import |
| --- | --- | --- |
| **View** | CustomTkinter UI (`Anonymizer`, `view.*`) | Controller internals |
| **MCP** | Headless FastMCP surface (`anonymizer.mcp`) — peer of View | Controller internals; View |
| **Controller** | DICOM/network, anonymization, AI pipelines, series I/O, script compile | View, MCP |
| **Model** | `ProjectModel`, PHI/Study/Series ORM (`AnonymizerModel`) | View, MCP, Controller |

`utils` (logging, memory, storage, translate, modalities, `DeidMethodCode`) sits beside MVC and must not import Controller, View, or MCP.

MCP: `mcp/tools` → `mcp/ops` + `mcp/session` over `ProjectController` and AI public APIs. Prefer controller APIs over Model except where create/open already builds `ProjectModel`.

Function-only leaves (for example `controller.ai.feature_availability`, `controller.ai.tseg.config`, `view.series.anatomy_overlay`, `view.common.treeview_chrome`) are omitted from the boxes.

Series vs Encapsulated PDF / SR: `view.reports.open_workspace` routes to `ReportTextReview` or `SeriesView`. Description mapping CSVs under project `mappings/` are owned by `controller.ai.harmonize.description_mapping_store`.

Experimental CLIs: [`src/prototyping/`](src/prototyping/README.md) (not in the wheel; topic folders `dev/`, `harmonize/`, `ffr/`, `ui/`, …).
