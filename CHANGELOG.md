# Changelog
All notable changes to this project will be documented in this file

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


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

## Added
- Distribution via pyPI, github action: release.yaml
- Unit testing via github action: tests.yaml
- src/utility unit testing
- Headless / Server mode via, start via rsna-anonmyizer <"path to ProjectModel.pkl">
- "View Pixels" and "View Index" buttons on dashboard with associated views

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
