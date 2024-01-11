# Changelog
All notable changes to this project will be documented in this file

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [17.0.8 Beta] -
### Added
- Auto generate unique site_id
- Open Recent Project File Menu
- Clone Project settings File Menu
- Select All & Default buttons added for Transfer Syntaxes and SOP Classes dialogs
- Verify all files are in storage directory after bulk move operation
- Implement round operand and associated round_age() in AnonymizerController

## Changed
- Moved de-identification string constants within AnonymizerController class
- unit-test.yml to build.yml, gh action build and upload steps

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
