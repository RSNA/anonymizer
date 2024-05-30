# Changelog
All notable changes to this project will be documented in this file

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [17.1.0] - 2024-05-30
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
