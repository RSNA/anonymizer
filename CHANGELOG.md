# Changelog
All notable changes to this project will be documented in this file

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [19.0.4]
- Tests: align face-blur gate and mocked TotalSegmentator fixtures with JSON sidecars and mask-required `finalize_seg_cache` (CI green after 19.0.3)

## [19.0.3]
- Harmonize CT single-pass: keep multilabel segmentation in memory and write only Series View latch masks (fixes missing overlays after stats-only caches)
- Refuse to publish anatomy JSON without on-disk masks; heal incomplete caches; Clear required before re-Harmonize when masks remain
- Brain structures prompt for ambiguous anonymized CT (default No); skip ROI fallback after cancel
- Series View: show Segmentation thickness from cache; cancel-after-step UX for Harmonize / Face Blur

## [19.0.2]
- Help menu: User Manual (browser), Tutorials (YouTube), License (in-app HTMLView); drop per-chapter menu entries
- GitHub Pages: serve MkDocs Actions build at site root so user-manual landing links work
- Restore US RGB `project_t2` OCR test DICOM fixture deleted in 19.0.1

## [19.0.1]
- First official V19 release
- Clinician user manual: MkDocs Material site under `docs/en/` (English only for now), GitHub Pages workflow, Help menu opens the published manual in the browser (local `site/` fallback)
- Headless AI batch: companion `AiBatchConfig.json` plus `--ai-batch` / `--ai-batch-run` CLI flags (one-shot batch; SCP unchanged)
- Support Python 3.11 as well as 3.12 (`requires-python >=3.11,<3.13`; Ruff `py311`; CI matrix on both; docs updated) — ports [#38](https://github.com/RSNA/anonymizer/pull/38)
- Harmonize: RSNA Playbook slice-thickness tokens (`Thin`, `Thick`) inferred from DICOM geometry/tags; standard-range thickness omitted per CT Sandbox SeriesNameV4
- Harmonize: detect Series Type Modifier (`MPR` for derived reformats); show in dialog, omit from description per SeriesNameV4
- Harmonize: CT anatomy + contrast in one TotalSegmentator `total`+`statistics` pass (MR / contrast-off stay dual-path); cooperative UX and stage timings
- Harmonize / AI Features: persist workstation CT/MR resolution prefs in app state; Playbook gettext tokens; locale catalog refresh
- Series / Projection: faster startup path; harden Harmonize results UX and Series View load/latch behavior
- View Projections: convert RGB ultrasound single frames to grayscale before CLAHE/Canny (fixes OpenCV assert on color US)
- MVC: AI feature gates in `controller/ai/feature_availability.py`; AI prefs helpers in `tseg.config`; `resolve_primary_segment_files` in `seg_retention`; whitelist match I/O in `remove_pixel_phi`; memory warn/abort defaults in `utils.memory`
- Move developer scripts (`dev_anonymizer`, welcome sizing check, Harmonize benchmark) under `src/prototyping/`; simplify PyPI install docs (uv-first)
- Docs: refresh `class_diagram.md` for V19 MVC + AI packages; package flowcharts under `docs/mvc/`

## [19.0.0.dev12]
- Harmonize: cooperative cancellation (skip contrast/merge after cancel; in-flight TotalSegmentator inference still runs to completion)
- Harmonize: DICOM metadata body-part fallback when TotalSegmentator finds no Playbook regions
- DICOM geometry: single-slice topogram/scout with LOCALIZER ImageType or topogram naming classifies as localizer (not `single_slice_2d`)
- TS cache retention (`seg_retention`): keep volume NIfTI for CT head until face blur is applied; compact legacy seg caches
- Centralize TS skip / metadata harmonize classification in `series_classification.py`
- AI Features Setup: more compact dialog (short copy, size-only resolution menu on title row with Remove/Download)
- AI Features Harmonize status: one-line “In use / also installed” (drop task inventory bullets); Remove button label shortened to “Remove”
- Harmonize resolution: AI Features picks one active CT and one active MR workstation resolution (picker always visible; Download when the selected pack is missing); Series View and AI Batch no longer choose resolution per run
- Brain structures: opt-in moved to Harmonize Description Dialog for CT Head only (after total anatomy); removed from Series View toolbar
- MR Harmonize Description dialog: IV Contrast row from DICOM headers (not CT contrast phase / TotalSegmentator); label/source/evidence updated accordingly
- MR Harmonize: skip contrast-phase analysis (no MR IV model); Series View latch uses `total_mr` `vertebrae` / whole-lung masks; combined vertebrae no longer force Chest body-part codes
- Move AI Features UX into `view/ai/features/` (catalog, availability, panel); rename setup dialog to `ai_features_dialog`; delete `controller/ai/features`
- Drop ProjectModel-persisted AI Feature enable flags and resolutions; Harmonize resolution is process/session workstation choice in AI Features (not ProjectModel)
- AI Features setup is models/license/download/remove only (no enable checkboxes)
- Simplify AI model readiness: on-demand path.exists checks replace TsWeightState/TsegRuntimeStatus caches, AiFeatureSession, and disable lifecycle
- Fold OCR whitelist match presets into `remove_pixel_phi.py` (drop `ocr_whitelist_match.py`)
- Move Series View overlay DTOs and anatomy mask→polygon helpers to `view/series` (`series_overlay`, `anatomy_overlay`)
- Narrow `tseg` to TotalSegmentator CT/MR segmentation runtime; move Playbook/LOINC Harmonize terminology into `controller/ai/harmonize/` (`pipeline`, `playbook`, `loinc_study`); drop description formatting from `TS_result`
- AI Features: state fixed Face (1.5 mm) and Brain structures (0.5×0.5×1 mm) resolutions; tighten dialog copy (less duplication)
- AI Features Harmonize: per-modality anatomy resolution picker (1.5 / 3 / 6 mm) for CT and MR downloads and runs; clinician-friendly CT/MR model copy (no blur-algorithm wording on Face model cards)
- AI Features Harmonize / Face Blur: separate CT and MR model download sections
- Fix MR model readiness: probe task 852 / face_mr 856 with TotalSegmentator's `nnUNetTrainer_2000epochs_NoMirroring` (not CT trainers)
- MRI Harmonize / Face Blur: additive modality profile (`total_mr` / `face_mr`) keeps CT paths, caches, and contrast unchanged; MR skips contrast, uses intensity face fill, separate `face_mr.nii.gz` cache, and LOINC `MR ` study ranking
- Study Description Harmonization: after the last CT series is Harmonized, rank LOINC StudyDescription rows from Playbook series signals and TS region fractions (prefer dominant organ); auto-apply clear winners to the study and fingerprint peers; prompt only when candidates are ambiguous; persist `Study.harmonized_description`, DICOM StudyDescription `(0008,1030)`, and LOINC code in Procedure Code Sequence `(0008,1032)` (`LN`)

## [19.0.0.dev11]
- Series View Segmentation panel: latch colored ROI overlays from cached TS masks (opaque outlines, progressive contouring, spine/ribs/clavicles); Clear moved into panel; shared `series_overlay` DTOs
- Prefer `vertebrae_body` when present; fix brain_structures weight trainer/model paths; invalidate soft-tissue-only TS caches so skeletal segments appear after Harmonize
- Optional brain_structures Harmonize detail (licensed task 409) via AI Features / batch options
- Share File/Settings/Help menubar across secondary windows (fixes macOS `python3` menu) and list open windows under Window
- Single Projection View instance from Dataset; refresh Window menu labels when Series/Projection titles update
- Fix Series View Pixel PHI save for multi-frame files: merge all frame strings into one comma-delimited Instance digest
- Dataset View: succinct columns (description-only Study/Series; study AI Yes/No; series Pixel PHI text; PHI/Anon ID autosize; centered cells)
- Tighten CT Series View OCR veracity: drop short numeric and digit/symbol false positives (keep US unchanged)
- Dataset view (renamed from PHI Index): nested study → series Treeview with per-series Harmonized / FaceBlur / PixelPHI
- Patient Lookup CSV: one denormalized row per series (study keys repeated); filename `{site}_{project}_PHI_{patients}_{studies}_{series}.csv`; omit study AI rollups and HarmonizedDescription
- Move PHI dataset DTOs, CSV export, and Java index import to `controller/phi_io`; views use `ProjectController` only (no View→Model)

## [19.0.0.dev10]
- Lookup table import (CTP `.properties`), settings UI, and lookup-aware `capture_phi` / anonymizer script operands
- Theme-driven `AppFonts` replaces per-view font lifecycle; dialog teardown hardening in `ctk_safe`
- Series View: compact whitelist toolbar, per-modality match strictness (Exact), and modality whitelist preview in AI batch options
- CT-only OCR veracity guard drops single-character spurious detections without affecting US
- Welcome view: restore v18-style layout and dynamic window sizing from content
- Fix `int_entry()` empty-string CTk crash; keep blank fields editable on Return/FocusOut
- CI: CPU-only PyTorch/torchvision on Linux (~2 GB smaller installs), uv cache tuning, and test path/cwd fixes

## [19.0.0.dev9]
- Reorganize flat `view/` into domain subpackages: `common`, `shell`, `project`, `series`, `ai` (alongside existing `settings`)
- Update imports across app, controller, tests, and scripts; no compatibility shims

## [19.0.0.dev8]
- Unify background jobs on WorkState + JobPoller (batch, harmonize/face-blur preview, Series View OCR); poll-on-change with tiered intervals
- Move algorithm modules under `controller/ai/`; remove unused `batch_process` shim; update imports across app, tests, and prototyping
- Series View: fix OCR detect boxes not drawing when whitelist is loaded (display uses whitelist-only filter, not noise heuristics); refresh viewer after detect completes
- ImageViewer: correct BGR overlay colors and per-frame overlay dimensions

## [19.0.0.dev7]
- Fix Harmonize anatomy model download on fresh install: download weights when checkpoints are missing instead of failing dataset lookup
- Fix project window distorted after welcome screen: resize to dashboard dimensions when a project opens
- Welcome screen: phase lock and guard against Retina Configure drift; fixed width 730
- AI Features: INFO-level logging through model download workflow; log when anatomy models not found
- Series View: OCR detect progress logged at DEBUG (not per-image INFO spam)

## [19.0.0.dev6]
- Fix AI Features Harmonize model download: keep progress visible for the full worker lifecycle and surface download failures in the dialog

## [19.0.0.dev5]
- Fix welcome window still clipped on macOS: use fixed CTk dimensions instead of winfo_req*, re-apply after layout

## [19.0.0.dev4]
- Fix welcome screen clipped on macOS Retina (Tk 9): size main window after welcome layout
- Help menu: **AI Features** opens setup (not only the Welcome screen button)
- Readme: macOS install with `python-tk@3.12`, uv managed Python 3.12 with Tcl/Tk 9, in-venv Tk verification

## [19.0.0.dev3]
- English AI Features help: overview after Overview, linked tool pages (not in Help menu), in-app `help:` navigation, wider layout
- AI Features setup opened from Welcome screen only; help and UI messages updated accordingly
- Remove Burnt-in Annotation help: click green rectangles after Detect Text to whitelist text
- Readmes document uv-based install and upgrade for faster V19 setup

## [19.0.0.dev2]
- AI batch processing (harmonize, face blur, remove pixel PHI) with progress UI and memory guards
- Batch OCR and MONOCHROME1 blackout aligned with Series View pixel pipeline
- Series View load stability fix; blur export UTF-8 character set
- CI runs controller (including tseg) and model tests; view tests remain local-only
- Controller test layout reorganized under blur_face/, core/, and harmonize/

## [19.0.0.dev1]
- PyPI development pre-release of V19 (install with `pip install --pre rsna-anonymizer`)
- Series View processing status, harmonize batch, face blur metadata, and RadLex Playbook updates on V19

## [19.0.0]
- Implement FALCON for CT body part and intra-venous contrast detection from pixel data

## [18.0.7]
### Changed
- Bugfix: controller/project.py.get_study_uid_hierarchy was insisting C-FIND[series] responses contained SOPClassUID, some PACS/VNA's do not return this, not mandatory as per DICOM Standard
- Disabled unit test: test_aws_upload/test_send_1_dicomfile_to_AWS_S3_and_list_objects for CI (Due to: "AWS Cognito Get User Attributes failed" on 22 May 2026)

## [18.0.6]
### Changed
- Change UID generation from sequential to hash of phi UID value, as per TCIA (Michael Rutherford) recommendation
- Fix issue#35 UID of deleted instances remain in DB <= cause was due to new patient creation, anon_ptid now generated safely from max string in table
- Significant test refactoring to handle new UID hash

## [18.0.5]
### Added
- PR#34 Michael Rutherford: DPI call for Windows 
### Changed
- Dark Theme text color set to white

## [18.0.4]
### Added
- Fix issue#32, add uid mapping when importing java index

## [18.0.0]
### Changed
- AnonymizerModel based on SQLAlchemy ORM replaced AnonymizerModel using python dictionaries as lookup tables
- Integration of new AnonymizerModel with AnonymizerController and ProjectController
- Added LoggingLevels: sql and store_dicom_source

## [17.4.*]
### Added
- SeriesView and ImageViewer classes with text detection and removal using easyocr reader and blackout area with user defined rectangles
- ImageViewer includes histogram display of current frame
- SeriesView includes whitelist with associated modality specific default lists in assets/locales/*/whitelists
### Changed
- Modifications to index and projection modules for memory management and launching SeriesView with ImageViewer

## [17.3.*] 
### Changed
- Changed virual environment & build tool from pipenv to poetry, pyproject.toml replace pipfile
- Documentation readmes, html 
- Removed build.yml for creating platform executables
- refactored source directory structure to fit pyPI package: src/anonymizer/*
- replaced coverage module with pytest-cov dev dependency
- more efficient AnonymizerModel serialization using pickle.dumps with highest protocol 
- changed ProjectModel serialization from pickle to json using dataclass_json package
- display script file path in project settings after project created
- ProjectModel.abridged_path to handle display of storage directory and script path to depth of 4
- change Query => Search and Export => Send
- License changed from RSNA Public to Apache 2.0 license
## Added
- Distribution via pyPI, github action: release.yaml
- Unit testing via github action: tests.yaml
- src/utility unit testing
- Headless / Server mode via, start via rsna-anonmyizer <"path to ProjectModel.pkl">
- view/index.py: "View" button on dashboard with associated ViewIndex window
- view/projection.py: View projections for each series, opened from ViewIndex via View Pixels button
- controller/create_projections.py with functions to create projection objects for a series (2D or 3D)
- create_projection_from_series creates Projection.pkl files for caching projections

## [17.2.*] Release Candidate
### Changed
- anonymizer.py menu bar handling refactored, resolve issue [#14](https://github.com/RSNA/anonymizer/issues/14), 
- anonymizer.py remove menu font - * to verify on windows platforms
- Fix build.yml badge to point to correct github action build result in readme.md
- github action: build.yml change from python 3.11 to 3.12
- resolve issue [#4](https://github.com/RSNA/anonymizer/issues/4):
    - model/project.py default_local_server changed IP from 127.0.0.1 to 0.0.0.0
    - view/settings/dicom_node_dialog ensure "0.0.0.0" is provided to IP address dropdown
- Moved logger.info trace of incoming file in ProjectController._handle_store to AnonymizeController.anonymize_dataset in pydicom logging true clause
- resturctured src directory for pypi: src/anonymizer/...
- release.yaml github action for managing pypi releases
## Added
- Add tcl/tk install and test to development setup in readme.md
- Addressing issue [#18] (https://github.com/RSNA/anonymizer/issues/18) 
    - IF pydicom logging enabled then incoming datasets, either via network or file import, will be stored in private subdir or storage directory
    - Classify all critial errors in AnonmyizerModel.capture_phi so logger output is clearer

## [17.1.1] - July 15, 2024
### Radon raw totals:
{'LOC': 10367,
 **'LLOC': 5237**,
 'SLOC': 6990,
 'Comments': 737,
 'Multi': 1212,
 'Blank': 1638,
 'Single comments': 527}
### Changed
- Module structure refactor into src/ anticipating pypi module rsna-anonymizer for V18 for server cmd line deployment
- Moved local_storage_path from storage module to ProjectController
- OSX build process now createds dmg using create-dmg
- utils.ux_fields string entry width mods
- DICOMNode DNS lookup width increased to 255, entry display width 40 chars
- Storage directory location default: user home folder / Documents / RSNA Anonymizer / ProjectName
### Added
- Full code documentation including mermaid class diagram
- Translation infrastructure using gettext subsystem
- readme.md for each language
- language and build status badges in readme
- German, Spanish, French translations for messages and html help files
- Mermaid class diagrams, full: class_diagram.md, abridged in readme.md for Model, Controller, View
- ThemeManager controls all UI colors, ttk.Treeview customized, appearance mode tested
- pstuil module added for platform agnostic method of efficiently getting available memory
- Available memory and ProjectController backoff threshold used to implement backoff algo in _handle_store


## [17.1.0] - 2024-05-30
### Radon raw totals: 
{'LOC': 8624, **'LLOC': 4846**, 'SLOC': 6686, 'Comments': 800, 'Multi': 31, 'Blank': 1309, 'Single comments': 598}
### Added
- Add Default, Select All buttons to Transfer Classes View
- Creating new project based on existing project settings, ie Clone Current Project Settings
- Add Open Recent Project to File Menu & auto open current project at startup
- Load PHI index files (XLSX format) from Java version of Anonymizer
- Add Series & Instance count to PHI CSV line
- Allow files with compressed transfer syntaxes 
- Convert free text Modality field for in Query dialog to drop down with mapping to project's SOP (storage) Classes
- Study Level drop down for Move operation
- Notifying bulk move operation result via pop up summary dialog
- Verify all files are moved after bulk move operation
- AWS export full implemented
- Implementation Class UID and Implementation Version Name attributes RSNA specific
- Handle instances with blank/missing Patient Name and Patient ID - direct to single patient folder
- Removing all PHI from log output except if log level set to debug for pydicom
- Locating log files in storage directory accessible to user
- Query remote server before study export, implemented logic to prevent re-exporting study
- Importing File and Directory dialog provides inidividual file import status
- File/Import Directory able parse DICOMDIR for moveable media
- Import & Anonymize errors: move to error/quarantine sub-directory
- Add comprehensive documentation including explanation of Anonymization algorithms employed
- Provide logging levels for Anonymizer, Pynetdicom and Pydicom as project settings
- Allow Study Date Range entries:  YYYYMMDD-, -YYYYMMDD, YYYYMMDD-YYYYMMDD
- Auto generate unique site_id
- Open Recent Project File Menu
- Clone Project settings File Menu
- Select All & Default buttons added for Transfer Syntaxes and SOP Classes dialogs
- Implement round operand and associated round_age() in AnonymizerController
- Added assets/images/create_icns.sh script to auto generate icns for osx
- GUI App initialisation creation exception handling
- Output tkinter and customtkinter version to log at startup
- Set log levels Anonymizer, pynetdicom, pydicom
## Changed
- Moved de-identification string constants within AnonymizerController class
- unit-test.yml to build.yml, gh action build and upload steps for all platforms using build.py (renamed build_win.py) with automatic release if version does not contain "RC"
- If running from pyinstaller set log file to /var/log/Anonymizer (Linux), /Library/Logs/Anonymizer (OSX), C:\Users\Username\AppData\Local\Anonymizer (Windows)

## [17.0.7 Beta] - 2023-11-08
### Added
- Allow multiple concurrent file and directory import processes
- ProjectController.find_uids to get list of series_uids and instance_uids for study retrieval management
### Changed
- If local server does start on open project (eg. due to local server start / port open error) then still open project 
- Product Name = "Anonymizer" across platforms, File Description = "RSNA DICOM Anonymizer"
- Query & Retrieve import verification by verifying files in store
- Storage path naming, remove Series and Instance Number dependency, use uids
- Increased log file size to 60MB
### Removed
 - Removed 
