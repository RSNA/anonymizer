# Class diagram (V19)

MVC layout of the shipped `rsna-anonymizer` package. Classes are listed by layer and package; attributes, methods, and DTO fields are omitted.

```mermaid
flowchart TB
    subgraph VIEW["VIEW"]
        direction TB
        V_APP["anonymizer<br/>Anonymizer"]
        V_SHELL["view.shell<br/>WelcomeView<br/>Dashboard"]
        V_PROJECT["view.project<br/>DatasetView<br/>QueryView<br/>ExportView<br/>DeleteStudiesDialog<br/>ImportStudiesDialog<br/>ImportFilesDialog"]
        V_SERIES["view.series<br/>SeriesView<br/>SeriesViewStartupSpec<br/>SeriesLoadError<br/>ProjectionView<br/>ImageViewer<br/>Histogram"]
        V_SETTINGS["view.settings<br/>SettingsDialog<br/>DICOMNodeDialog<br/>SOPClassesDialog<br/>TransferSyntaxesDialog<br/>ModalitiesDialog<br/>NetworkTimeoutsDialog<br/>LookupTableDialog<br/>AWSCognitoDialog<br/>LoggingLevelsDialog"]
        V_AI["view.ai<br/>AiFeaturesSetupDialog<br/>AiBatchProcessDialog<br/>AiBatchProcessOptionsDialog<br/>AiBatchProcessOptionsResult<br/>HarmonizeStudiesDialog<br/>HarmonizeResultsView<br/>FaceBlurReviewDialog<br/>SetDescriptionDialog<br/>ModalityWhitelistPreviewDialog"]
        V_AI_FEAT["view.ai.features<br/>AiFeaturesPanel<br/>AiFeatureDownloadManager"]
        V_COMMON["view.common<br/>AppToplevel<br/>AppCTkToplevel<br/>AppMenuHost<br/>AppFonts<br/>JobPoller"]
        V_MCP["mcp<br/>MCPServer tools / ops / session / snapshots"]
        V_APP --- V_SHELL
        V_APP --- V_PROJECT
        V_APP --- V_SERIES
        V_APP --- V_SETTINGS
        V_APP --- V_AI
        V_AI --- V_AI_FEAT
        V_APP --- V_COMMON
    end

    subgraph CONTROLLER["CONTROLLER"]
        direction TB
        C_PROJECT["controller.project<br/>ProjectController<br/>…"]
        C_ANON["controller.anonymizer<br/>AnonymizerController"]
        C_WORK["controller.work_state<br/>WorkState"]
        C_RUN["controller.runner<br/>Runner / RemovePixelPhiRunner / …"]
        C_BATCH["controller.ai_batch_process / ai_batch_config"]
        C_IO["controller.series_io / …"]
        C_HARM["controller.ai.harmonize"]
        C_OCR["controller.ai.remove_pixel_phi"]
        C_PROJECT --- C_ANON
        C_PROJECT --- C_WORK
        C_PROJECT --- C_RUN
        C_PROJECT --- C_BATCH
        C_PROJECT --- C_IO
        C_BATCH --- C_HARM
        C_BATCH --- C_OCR
    end

    subgraph MODEL["MODEL"]
        direction TB
        M_PROJECT["model.project<br/>ProjectModel<br/>DICOMNode …"]
        M_ANON["model.anonymizer<br/>AnonymizerModel<br/>PHI / Study / Series …"]
        M_PROJECT --- M_ANON
    end

    VIEW -->|"calls public APIs"| CONTROLLER
    V_MCP -->|"ProjectController + AI public APIs"| C_PROJECT
    V_MCP -->|"AI pipelines"| C_BATCH
    V_MCP -->|"pixel PHI"| C_OCR
    CONTROLLER -->|"reads / writes"| MODEL
```

## Layer rules

| Layer | Owns | Must not import |
| --- | --- | --- |
| **View** | CustomTkinter UI (`Anonymizer` shell and `view.*`) **and** MCP (`anonymizer.mcp`) | Controller internals |
| **Controller** | DICOM/network, anonymization, AI pipelines, I/O | View |
| **Model** | `ProjectModel`, PHI/Study/Series ORM (`AnonymizerModel`) | View, Controller |

`utils` (logging, memory, storage, translate) sits beside MVC and must not import Controller or View.

MCP is a peer View: `mcp/tools` coerce args → `mcp/ops` + `mcp/session` (orchestration over existing `ProjectController` / AI APIs) → JSON envelope. MCP may use Model only where project create/open already requires `ProjectModel` construction; prefer controller public APIs otherwise.

Modules that expose functions rather than types (for example `controller.ai.feature_availability`, `controller.ai.tseg.config`, `view.series.anatomy_overlay`) are omitted from the boxes above.

Experimental CLIs: [`src/prototyping/`](src/prototyping/README.md) (not part of the wheel).
