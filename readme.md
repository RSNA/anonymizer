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
1. Create tests/controller/.env file with your AWS_USERNAME and AWS_PASSWORD
2. pipenv shell
3. coverage run -m pytest tests
4. coverage report --omit="tests/*"
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
        <<model.project>>
        + ip
        + port
        + aet
        + local
    }
    class NetworkTimeouts {
        <<model.project>>
        + tcp_connection
        + acse
        + dimse
        + network
    }
    class LoggingLevels {
        <<model.project>>
        + anonymizer
        + pynetdicom
        + pydicom
    }
    class AWSCognito {
        <<model.project>>
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
        <<model.anonymizer>>
        + series_uid
        + series_desc
        + modality
        + instance_count
    }
    class Study {
        <<model.anonymizer>>
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
        <<model.anonymizer>>
        + patient_name
        + patient_id
        + sex
        + dob
        + ethnic_group
    }
    PHI "1" --* "*" Study: studies
    class Totals {
        <<model.anonymizer>>
        + patients
        + studies
        + series
        + instances
    }
    class JavaAnonymizerExportedStudy{
        <<utils.storage>>
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
        + default_anon_pt_id
        - _version
        - _site_id
        - _uid_root
        - _uid_prefix
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
    class PresentationContext {
        <<pynetdicom.presentation>>
    }
    class Event {
        <<pynetdicom.events>>
    }
    class Association {
        <<pynetdicom.association>>
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
        - _write_to_quarantine(exception, ds, quarantine_error) str
        - _autosave_manager()
        - _stop_worker_threads()
        - _hash_date(date, patient_id) (int, str)
        - _anonymize_element(dataset, data_element) 
        - _anonymize_worker(ds_Q: Queue)
        + model_changed() bool
        + save_model() bool
        + valid_date(date_str) bool
        + stop()
        + missing_attributes(ds) [str]
        + local_storage_path(base_dir, ds) Path
        + get_quarantine_path() Path
        + _round_age(age_string, width) str
        + move_to_quarantine(file, sub_dir) bool
        + anonymize(source, ds) str
        + anonymize_file(file) (str, Dataset)
        + anonymize_dataset_ex(source, ds)
    }
    AnonymizerController --* AnonymizerModel
    AnonymizerController --> ProjectModel
    AnonymizerController "1" ..> "*" Dataset
    
    class InstanceUIDHierarchy {
        <<controller.project>>
        + uid
        + number
    }
    class SeriesUIDHierarchy {
        <<controller.project>>
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
        <<controller.project>>
        + uid
        + ptid
        + last_error_msg
        + pending_instances
        + completed_sub_ops
        + failed_sub_ops
        + remaining_sub_ops
        + warning_sub_ops
        + get_number_of_instances() int
        + get_instances[InstanceUIDHierarchy]
        + update_move_states(status: Dataset)
        + find_instance(instance_uid) InstanceUIDHierarchy
    }
    StudyUIDHierarchy "1" --* "*" SeriesUIDHierarchy: series
    class EchoRequest {
        <<controller.project>>
        + scp
        + ux_Q
    }
    class EchoResponse {
        <<controller.project>>
        + success
        + error
    }
    class FindStudyRequest {
        <<controller.project>>
        + scp_name
        + name
        + id
        + acc_no
        + study_date
        + modality
        + ux_Q
    }
    class FindStudyResponse {
        <<controller.project>>
    }
    FindStudyResponse "1" --* "1" Dataset: status
    FindStudyResponse "1" --* "1" Dataset: study_result
    
    class MoveStudiesRequest {
        <<controller.project>>
        scp_name
        dest_scp_ae
        level
    }
    MoveStudiesRequest "1" --* "*" StudyUIDHierarchy: studies
    class ExportPatientsRequest {
        <<controller.project>>
        dest_name 
        patient_ids
        ux_Q
    }
    class ExportPatientsResponse {
        <<controller.project>>
        patient_id
        files_sent
        error
        complete
    }
    class ProjectController {
        <<controller.project>>       
        + PROJECT_MODEL_FILENAME
        - _VERIFICATION_CLASS
        - _STUDY_ROOT_QR_CLASSES
        - _handle_store_time_slice_interval
        - _export_file_time_slice_interval 
        - _patient_export_thread_pool_size 
        - _study_move_thread_pool_size
        - _memory_available_backoff_threshold
        - _required_attributes_study_query
        - _required_attributes_series_query
        - _required_attributes_instance_query
        - _query_result_fields_to_remove
        - _aws_credentials
        - _s3
        - _aws_expiration_datetime
        - _aws_user_directory
        - _aws_last_error
        - _strip_query_result_fields(ds)
        - _missing_attributes(required_attributes, ds)
        - _reset_scp_vars()
        - _update_model(new_model)
        + save_model(dest_dir)
        + set_dicom_timeouts(timeouts)
        + get_network_timeouts()
        + set_verification_context()
        + get_verification_context()
        + set_radiology_storage_contexts()
        + get_radiology_storage_contexts()
        + get_radiology_storage_contexts_BIGENDIAN()
        + set_study_root_qr_contexts()
        + get_study_root_qr_contexts() [PresentationContext]
        + get_study_root_find_contexts() [PresentationContext]
        + get_study_root_move_contexts() [PresentationContext]
        - _handle_echo(event)
        - _handle_store(event)
        - _connect_to_scp(scp, contexts) Association
        - _move_study_at_study_level(scp_name, dest_scp_ae, study: StudyUIDHierarchy) str
        - _move_study_at_series_level(scp_name, dest_scp_ae, study: StudyUIDHierarchy) str
        - _move_study_at_instance_level(scp_name, dest_scp_ae, study: StudyUIDHierarchy) str
        - _manage_move(req: MoveStudiesRequest)
        - _export_patient(dest_name, patient_id, ux_Q)
        - _manage_export(req: ExportStudyRequest)
        + AWS_credentials_valid() bool
        + AWS_authenticate()
        + AWS_autenticate_ex()
        + AWS_get_instances(anon_pt_id, study_uid) [str]
        + start_scp()
        + stop_scp()
        + echo(scp, ux_Q)
        + echo_ex(er: EchoRequest)
        + send(file_paths, scp_name, send_contexts)
        + abort_query()
        + find_studies(scp_name, name, id, acc_no, study_date, modality, ux_Q) [Dataset]
        + find_studies_via_acc_nos(scp_name, acc_no_list, ux_Q) [Dataset]
        + find_ex(fr: FindStudyRequest)
        + get_study_uid_hierarchy(scp_name, study_uid, patient_id, instance_level) (str, StudyUIDHierarchy)
        + get_study_uid_hierarchies(scp_name, studies: [StudyUIDHierarchy], instance_level) 
        + get_study_uid_hierarchies_ex(scp_name, studies: [StudyUIDHierarchy], instance_level)
        + get_number_of_pending_instances(study: StudyUIDHierarchy) int
        + bulk_move_active() bool
        + bulk_export_active() bool
        + abort_move()
        + abort_export()
        + move_studies_ex(mr: MoveStudiesRequest)
        + export_patients_ex(er: ExportStudyRequest)
        + create_phi_csv() Path
    }
    ApplicationEntity <|-- ProjectController
    ProjectController "1" --* "1" ProjectModel
    ProjectController "1" --* "1" AnonymizerController
    ProjectController "1" ..> "1" NetworkTimeouts
    ProjectController "1" ..> "*" PresentationContext
    ProjectController "1" ..> "*" Event
    ProjectController "1" ..> "*" Dataset
    ProjectController "1" ..> "*" Association
    ProjectController "1" ..> "1" EchoRequest
    ProjectController "1" ..> "1" EchoResponse
    ProjectController "1" ..> "*" StudyUIDHierarchy
    ProjectController "1" ..> "1" FindStudyRequest
    ProjectController "1" ..> "*" FindStudyResponse
    ProjectController "1" ..> "1" MoveStudiesRequest
    ProjectController "1" ..> "1" ExportPatientsRequest
    ProjectController "1" ..> "*" ExportPatientsResponse
    class Tk {
        <<tkinter>>
    }
    class CTk {
        <<customtkinter>>
    }
    class WelcomeView {
        <<view.welcome>>
        + TITLE
        + TITLE_FONT_SIZE
        + WELCOME_TEXT
        + WELCOME_TEXT_FONT_SIZE
        + TITLED_LOGO_FILE
        + TITLED_LOGO_WIDTH
        + TITLED_LOGO_HEIGHT
        + TEXT_BOX_WIDTH
        + TEXT_BOX_HEIGHT
    }
    class QueryView {
        <<view.query_retrieve_import>>
    }
    Tk <|-- CTk
    class Anonymizer {
        <<anonymizer>>
        + TITLE
        + THEME_FILE
        + CONFIG_FILENAME
        + project_open_startup_dwell_time
        + metric_loop_interval
        + menu_font
        
    }
    Anonymizer --* ProjectController: controller
    Anonymizer --* QueryView: query_view
    

    

    
    
    
    
    

```