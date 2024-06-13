# RSNA DICOM Anonymizer V17
![WelcomeView](src/assets/html/WelcomeView.png)
## Installation 
Select the correct binary download for your platform from the available [releases](https://github.com/mdevans/anonymizer/releases)
### 1. Windows
Download and extract zip to desired application directory.
Execute Anonymizer.exe and override User Account Control to allow the program to "Run anyway".
### 2. Mac OSX
Download and extract zip file to desired application directory.
Open a Terminal at the dist sub-directory and run the following commmand to remove the extended atrributes from the application: 
```
xattr -r -c Anonymizer_17.*.*.app 
```
Double click the application icon to execute.
### 3. Ubuntu

## Documentation
[Help files](https://mdevans.github.io/anonymizer/index.html)
## Development
### Setup
1. Setup python enviroment (>3.10), recommend using pyenv
2. ```pip install pipenv```
3. Clone repository
4. Setup virtual enviroment and install all  dependencies listed in Pipfile: ```pipenv install --dev```
### Unit Testing 
#### For model and controller with coverage
```
1. pipenv shell
2. coverage run -m pytest tests
3. coverage report --omit="tests/*"
```
### Code Metrics 
#### Using radon
```
1. pipenv shell
2. radon raw -i "tests,docs,prototyping" . > radon_results.txt
3. python src/radon_raw_totals.py
```
### Software Architecture
```mermaid
classDiagram
    class DICOMNode {
        + ip
        + port
        + aet
        + local
    }
    class NetworkTimeouts {
        + tcp_connection
        + acse
        + dimse
        + network
    }
    class LoggingLevels {
        + anonymizer
        + pynetdicom
        + pydicom
    }
    class AWSCognito {
        + account_id
        + region_name
        + app_client_id
        + user_pool_id
        + identity_pool_id
        + s3_bucket
        + s3_prefix
        + username
        + password
    }
    class ProjectModel {
        <<model.project>>
        + MODEL_VERSION
        + PRIVATE_DIR
        + PUBLIC_DIR
        + PHI_EXPORT_DIR
        + QUARANTINE_DIR
        + RSNA_ROOT_ORG_UID
        + IMPLEMENTATION_CLASS_UID
        + IMPLEMENTATION_VERSION_NAME
        + site_id
        + project_name
        + uid_root
        + storage_dir
        + modalities
        + storage_classes
        + transfer_syntaxes
        + anonymizer_script_path
        + export_to_aws
        + images_dir()
        + private_dir()
        + abridged_stored_dir()
        + phi_export_dir()
        + regenerate_site_id()
        + set_storage_classes_from_modalities()
        + add_storage_class(storage_class)
        + remove_storage_class(storage_class)
        + add_transfer_syntax(transfer_syntax)
        + remove_transfer_syntax(transfer_syntax)
    }
    ProjectModel --* "1" LoggingLevels: logging_levels
    ProjectModel --* "1" NetworkTimeouts: network_timeouts
    ProjectModel --* "1" AWSCognito: aws_cognito
    ProjectModel --* "1" DICOMNode: scu
    ProjectModel --* "1" DICOMNode: scp
    ProjectModel --* "*" DICOMNode: remote_scps
    
    class Series {
        + series_uid
        + series_desc
        + modality
        + instance_count
    }
    class Study{
        + source
        + study_uid
        + study_date
        + anon_date_delta
        + accession_number
        + study_desc
        + target_instance_count
    }
    Study "1" --* "*" Series: series
    class PHI{
        + patient_name
        + patient_id
        + sex
        + dob
        + ethnic_group
    }
    PHI "1" --* "*" Study: studies
    class Totals {
        + patients
        + studies
        + series
        + instances
    }
    class JavaAnonymizerExportedStudy{
        ANON_PatientNamer
        ANON_PatientID
        PHI_PatientName
        PHI_PatientID
        DateOffset
        ANON_StudyDate
        PHI_StudyDate
        ANON_Accession
        PHI_Accession
        ANON_StudyInstanceUID
        PHI_StudyInstanceUID
    }
    class AnonymizerModel {
        <<model.anonymizer>>
        + MODEL_VERSION
        + MAX_PATIENTS
        - _version
        - _site_id
        - _uid_root
        - _uid_prefix
        + default_anon_pt_id
        - _tag_keep
        - _patient_id_lookup
        - _uid_lookup
        - _acc_no_lookup
        - _patients
        - _studies
        - _series
        - _instances
        + load_script()
        + clear_lookups()
        + get_totals() Totals
        + get_phi(anon_patient_id) PHI
        + get_phi_name(anon_patient_id) str
        + set_phi(anon_patient_id, phi)
        + get_anon_patient_id(phi_patient_id) str
        + get_next_anon_patient_id(phi_patient_id) str
        + get_patient_id_count() int
        + set_anon_patient_id(phi_patient_id, anon_patient_id)
        + uid_received(phi_uid) bool
        + remove_uid(phi_uid)
        + get_anon_uid(phi_uid) str
        + get_uid_count() int
        + set_anon_uid(phi_uid, anon_uid)
        + get_next_anon_uid(phi_uid) str
        + get_anon_acc_no(phi_acc_no) str
        + set_anon_acc_no(phi_acc_no, anon_acc_no)
        + get_next_anon_acc_no(phi_acc_no) str
        + get_acc_no_count() int
        + get_stored_instance_count(ptid, study_uid) int
        + get_pending_instance_count(ptid, study_uid, target_count) int
        + series_complete(ptid, study_uid, series_uid, target_count) bool
        + study_imported(ptid, study_uid) bool
        + new_study_from_dataset(ds, source, date_delta) Study
        + capture_phi(source, ds, date_delta) 
        + process_java_phi_studies(java_studies: [JavaAnonymizerExportedStudy])
    }
    AnonymizerModel "1" --* "*" PHI: _phi_lookup
    AnonymizerModel "1" ..> "*" JavaAnonymizerExportedStudy
    AnonymizerModel "1" ..> "1" Totals
    class ApplicationEntity {
        <<pynetdicom.ae>> 
        - _implementation_class_uid
        - _implementation_version_name 
        - _connection_timeout
        - _acse_timeout
        - _dimse_timeout
        - _network_timeout      
    }
    class Dataset {
        <<pydicom.Dataset>>
    }
    class AnonymizerController {
        <<controller.anonymizer>>
        + ANONYMIZER_MODEL_FILENAME
        + DEIDENTIFICATION_METHOD
        + QUARANTINE_INVALID_DICOM
        + QUARANTINE_DICOM_READ_ERROR
        + QUARANTINE_MISSING_ATTRIBUTES
        + QUARANTINE_INVALID_STORAGE_CLASS
        + QUARANTINE_CAPTURE_PHI_ERROR
        + QUARANTINE_STORAGE_ERROR
        + DEIDENTIFICATION_METHODS
        + PRIVATE_BLOCK_NAME
        + DEFAULT_ANON_DATE
        + NUMBER_OF_WORKER_THREADS
        + WORKER_THREAD_SLEEP_SECS
        + MODEL_AUTOSAVE_INTERVAL_SECS
        + required_attributes
        - _active
        - _anon_Q
        - _worker_threads
        - _model_change_flag
        - _autosave_event
        - _autosave_worker_thread
        + model_changed() bool
        - _stop_worker_threads()
        + stop()
        + missing_attributes(ds) [str]
        + local_storage_path(base_dir, ds) Path
        + get_quarantine_path() Path
        - _write_to_quarantine(exception, ds, quarantine_error) str
        - _autosave_manager()
        + save_model() bool
        + valid_date(date_str) bool
        - _hash_date(date, patient_id) (int, str)
        + _round_age(age_string, width) str
        - _anonymize_element(dataset, data_element) 
        + anonymize(source, ds) str
        + move_to_quarantine(file, sub_dir) bool
        + anonymize_file(file) (str, Dataset)
        + anonymize_dataset_ex(source, ds)
        - _anonymize_worker(ds_Q: Queue)
    }
    AnonymizerController --> ProjectModel
    class InstanceUIDHierarchy {
        + uid
        + number
    }
    class SeriesUIDHierarchy {
        + uid
        + number
        + modality
        + sop_class_uid
        + instance_count
        + description
        + completed_sub_ops
        + failed_sub_ops
        + remaining_sub_ops
        + warning_sub_ops
        + get_number_of_instances() int
        + find_instance(instance_uid) InstanceUIDHierarchy
        + update_move_stats(status: Dataset)

    }
    SeriesUIDHierarchy "1" --* "*" InstanceUIDHierarchy: instances
    class StudyUIDHierarchy {
        + uid
        + ptid
        + last_error_msg
        + pending_instances
        completed_sub_ops
        failed_sub_ops
        remaining_sub_ops
        warning_sub_ops
    }
    StudyUIDHierarchy "1" --* "*" SeriesUIDHierarchy: series
    class ProjectController {
        <<controller.project>>       
        + attribute1
        + method1()
    }
    ProjectController "1" --* "1" ProjectModel
    ProjectController "1" --* "1" AnonymizerController

    

    
    ApplicationEntity <|-- ProjectController
    
    AnonymizerController --o AnonymizerModel
    

```