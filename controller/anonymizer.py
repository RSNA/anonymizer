# Description: Anonymization of DICOM datasets
# See https://mircwiki.rsna.org/index.php?title=The_CTP_DICOM_Anonymizer for legacy anonymizer documentation
import os
from shutil import copyfile
from copy import copy
import re
import time
import logging
import threading
import hashlib
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue, Empty
from pydicom import Dataset, Sequence, dcmread
from pydicom.errors import InvalidDicomError
from utils.translate import _
from utils.storage import local_storage_path
from model.project import DICOMRuntimeError, DICOMNode, Study, Series, PHI, ProjectModel
from model.anonymizer import AnonymizerModel

logger = logging.getLogger(__name__)


class AnonymizerController:
    ANONYMIZER_MODEL_FILENAME = "AnonymizerModel.pkl"
    DEIDENTIFICATION_METHOD = "RSNA DICOM ANONYMIZER"
    # Quarantine Errors / Sub-directories:
    QUARANTINE_MISSING_ATTRIBUTES = "Missing_Attributes"
    QUARANTINE_INVALID_DICOM = "Invalid_DICOM"
    QUARANTINE_FILE_READ_ERROR = "File_Read_Error"
    QUARANTINE_DICOM_READ_ERROR = "DICOM_Read_Error"
    QUARANTINE_STORAGE_ERROR = "Storage_Error"

    # See docs/RSNA-Covid-19-Deindentification-Protocol.pdf
    # TODO: if user edits default anonymization script these values should be updated accordingly
    DEIDENTIFICATION_METHODS = [
        ("113100", "Basic Application Confidentiality Profile"),
        (
            "113107",
            "Retain Longitudinal Temporal Information Modified Dates Option",
        ),
        ("113108", "Retain Patient Characteristics Option"),
    ]
    PRIVATE_BLOCK_NAME = "RSNA"
    DEFAULT_ANON_DATE = "20000101"  # if source date is invalid or before 19000101

    _anonymize_time_slice_interval: float = 0.1  # seconds
    _anonymizer_model_autosave_interval: int = 60  # seconds
    # _anonymize_batch_size: int = 40  # number of items to process in a batch
    _clean_tag_translate_table = str.maketrans("", "", "() ,")

    # Required DICOM field attributes for accepting files:
    required_attributes = [
        "SOPClassUID",
        "SOPInstanceUID",
        "StudyInstanceUID",
        "SeriesInstanceUID",
    ]

    def __init__(self, project_model: ProjectModel):
        self.project_model = project_model
        # Initialise AnonymizerModel datafile full path:
        self.model_filename = Path(self.project_model.private_dir(), self.ANONYMIZER_MODEL_FILENAME)

        # If present, load pickled AnonymizerModel from project directory:
        if os.path.exists(self.model_filename):
            try:
                with open(self.model_filename, "rb") as pkl_file:
                    file_model = pickle.load(pkl_file)
                    if not isinstance(file_model, AnonymizerModel):
                        raise TypeError("Loaded object is not an instance of AnonymizerModel")
            except Exception as e:
                # TODO: Try and open last backup file
                logger.error(f"Anonymizer Model datafile corrupt: {e}")
                raise RuntimeError(f"Anonymizer datafile: {self.model_filename} corrupt\n\n{str(e)}")

            logger.info(f"Anonymizer Model successfully loaded from: {self.model_filename}")

            if not hasattr(file_model, "_version"):
                logger.error(f"Anonymizer Model datafile corrupt: version missing")
                raise RuntimeError(f"Anonymizer datafile: {self.model_filename} corrupt")

            logger.info(f"Anonymizer Model loaded successfully, version: {file_model._version}")

            if file_model._version != AnonymizerModel.MODEL_VERSION:
                logger.info(
                    f"Anonymizer Model version mismatch: {file_model._version} != {AnonymizerModel.MODEL_VERSION} upgrading accordingly"
                )
                self.model = AnonymizerModel(
                    project_model.site_id, project_model.anonymizer_script_path
                )  # new default model
                # TODO: handle new & deleted fields in nested objects
                self.model = copy(file_model)  # copy over corresponding attributes from the old model (file_model)
                self.model._version = AnonymizerModel.MODEL_VERSION  # upgrade version
                self.save_model()
                logger.info(f"Anonymizer Model upgraded successfully to version: {self.model._version}")
            else:
                self.model = file_model

        else:
            # Initialise New Default AnonymizerModel if no pickle file found in project directory:
            self.model = AnonymizerModel(project_model.site_id, project_model.anonymizer_script_path)
            logger.info(f"New Default Anonymizer Model initialised from: {project_model.anonymizer_script_path}")

        self._anon_Q: Queue = Queue()

        self._active = False

        self._worker = threading.Thread(
            target=self._anonymize_worker,
            args=(self._anon_Q,),
            daemon=True,
        ).start()

        time.sleep(0.2)  # Allow worker thread to start

        if not self._active:
            logger.error("AnonymizerController failed to start worker thread")
            raise RuntimeError("AnonymizerController failed to start worker thread")

    def __del__(self):
        self._active = False

    def stop(self):
        self._active = False

    def missing_attributes(self, ds: Dataset) -> list[str]:
        return [
            attr_name for attr_name in self.required_attributes if attr_name not in ds or getattr(ds, attr_name) == ""
        ]

    def get_quarantine_path(self) -> Path:
        return Path(self.project_model.storage_dir, self.project_model.PRIVATE_DIR, self.project_model.QUARANTINE_DIR)

    def save_model(self) -> bool:
        try:
            with open(self.model_filename, "wb") as pkl_file:
                pickle.dump(self.model, pkl_file)
            logger.debug(f"Anonymizer Model saved to: {self.model_filename}")
            return True
        except Exception as e:
            logger.error(f"Fatal Error saving AnonymizerModel  error: {e}")
            return False

    def get_next_anon_patient_id(self) -> str:
        next_patient_index = self.model.get_patient_id_count()
        return f"{self.project_model.site_id}-{next_patient_index:06}"  # TODO: handle more than 999999 patients

    # Date must be YYYYMMDD format and a valid date after 19000101:
    def valid_date(self, date_str: str) -> bool:
        try:
            date_obj = datetime.strptime(date_str, "%Y%m%d")
            if date_obj < datetime(1900, 1, 1):
                return False
            return True
        except ValueError:
            return False

    # Increment date by a number of days determined by MD5 hash of PatientID mod 10 years
    # DICOM Date format: YYYYMMDD
    # Returns tuple of (days incremented, incremented date)
    def _hash_date(self, date: str, patient_id: str) -> tuple[int, str]:
        if not self.valid_date(date) or not len(patient_id):
            return 0, self.DEFAULT_ANON_DATE

        # Calculate MD5 hash of PatientID
        md5_hash = hashlib.md5(patient_id.encode()).hexdigest()
        # Convert MD5 hash to an integer
        hash_integer = int(md5_hash, 16)
        # Calculate number of days to increment (10 years in days)
        days_to_increment = hash_integer % 3652
        # Parse the input date as a datetime object
        input_date = datetime.strptime(date, "%Y%m%d")
        # Increment the date by the calculated number of days
        incremented_date = input_date + timedelta(days=days_to_increment)
        # Format the incremented date as "YYYYMMDD"s
        formatted_date = incremented_date.strftime("%Y%m%d")

        return days_to_increment, formatted_date

    def extract_first_digit(self, s: str):
        match = re.search(r"\d", s)
        return match.group(0) if match else None

    def _round_age(self, age_string: str, width: int) -> str | None:
        if age_string is None:
            return ""

        age_string = age_string.strip()
        if len(age_string) == 0:
            return ""

        try:
            age_float = float("".join(filter(str.isdigit, age_string))) / width
            age = round(age_float) * width
            result = str(age) + "".join(filter(str.isalpha, age_string))

            if len(result) % 2 != 0:
                result = "0" + result

        except ValueError:
            logger.error(f"Invalid age string: {age_string}, round_age operation failed, keeping original value")
            result = age_string

        return result

    # Extract PHI from new study and store:
    def capture_phi_from_new_study(self, phi_ds: Dataset, source: DICOMNode | str):
        def study_from_dataset(ds: Dataset) -> Study:
            return Study(
                str(ds.StudyDate) if hasattr(phi_ds, "StudyDate") else "?",
                (
                    self._hash_date(ds.StudyDate, phi_ds.PatientID)[0]
                    if hasattr(phi_ds, "StudyDate") and hasattr(phi_ds, "PatientID")
                    else 0
                ),
                str(ds.AccessionNumber) if hasattr(phi_ds, "AccessionNumber") else "?",
                (str(ds.StudyInstanceUID) if hasattr(phi_ds, "StudyInstanceUID") else "?"),
                source,
                [
                    Series(
                        (ds.SeriesInstanceUID if hasattr(phi_ds, "SeriesInstanceUID") else "?"),
                        (str(ds.SeriesDescription) if hasattr(phi_ds, "SeriesDescription") else "?"),
                        str(ds.Modality) if hasattr(phi_ds, "Modality") else "?",
                        1,
                    )
                ],
            )

        # If PHI PatientID is missing, as per DICOM Standard, pydicom will return ""
        # this corresponds to AnonymizerModel.DEFAULT_ANON_PATIENT_ID ("000000") initialised in AnonymizerModel
        anon_patient_id = self.model.get_anon_patient_id(phi_ds.PatientID if hasattr(phi_ds, "PatientID") else "")

        if anon_patient_id == None:  # New patient
            new_anon_patient_id = self.get_next_anon_patient_id()
            # TODO: write init method for PHI(phi_ds) using introspection for fields to look for in dataset
            phi = PHI(
                patient_name=str(phi_ds.PatientName) if hasattr(phi_ds, "PatientSex") else "U",
                patient_id=str(phi_ds.PatientID),
                sex=phi_ds.PatientSex if hasattr(phi_ds, "PatientSex") else "U",
                dob=phi_ds.PatientBirthDate if hasattr(phi_ds, "PatientBirthDate") else None,
                weight=phi_ds.PatientWeight if hasattr(phi_ds, "PatientWeight") else None,
                bmi=phi_ds.PatientBodyMassIndex if hasattr(phi_ds, "PatientBodyMassIndex") else None,
                size=phi_ds.PatientSize if hasattr(phi_ds, "PatientSize") else None,
                smoker=phi_ds.SmokingStatus if hasattr(phi_ds, "SmokingStatus") else None,
                medical_alerts=phi_ds.MedicalAlerts if hasattr(phi_ds, "MedicalAlerts") else None,
                allergies=phi_ds.Allergies if hasattr(phi_ds, "Allergies") else None,
                ethnic_group=phi_ds.EthnicGroup if hasattr(phi_ds, "EthnicGroup") else None,
                reason_for_visit=(
                    phi_ds.ReasonForTheRequestedProcedure if hasattr(phi_ds, "ReasonForTheRequestedProcedure") else None
                ),
                admitting_diagnoses=(
                    phi_ds.AdmittingDiagnosesDescription if hasattr(phi_ds, "AdmittingDiagnosesDescription") else None
                ),
                history=phi_ds.PatientHistory if hasattr(phi_ds, "PatientHistory") else None,
                additional_history=(
                    phi_ds.AdditionalPatientHistory if hasattr(phi_ds, "AdditionalPatientHistory") else None
                ),
                comments=phi_ds.PatientComments if hasattr(phi_ds, "PatientComments") else None,
                studies=[
                    study_from_dataset(phi_ds),
                ],
            )
            self.model.set_phi(new_anon_patient_id, phi)

        else:  # Existing patient now with more than one study
            phi = self.model.get_phi(anon_patient_id)
            if phi == None:
                msg = f"Existing patient {anon_patient_id} not found in phi_lookup"
                logger.error(msg)
                raise RuntimeError(msg)

            phi.studies.append(study_from_dataset(phi_ds))
            self.model.set_phi(anon_patient_id, phi)

    def update_phi_from_new_instance(self, ds: Dataset, source: DICOMNode | str):
        # Study PHI already captured, update series and instance counts from new instance:
        anon_patient_id = self.model.get_anon_patient_id(ds.PatientID if hasattr(ds, "PatientID") else "")
        assert anon_patient_id != None
        phi = self.model.get_phi(anon_patient_id)
        if phi == None:
            msg = f"Existing patient {anon_patient_id} not found in phi_lookup"
            logger.error(msg)
            raise RuntimeError(msg)

        # Find study in PHI:
        if phi.studies is not None and ds.StudyInstanceUID is not None:
            study = next(
                (study for study in phi.studies if study.study_uid == ds.StudyInstanceUID),
                None,
            )
        else:
            study = None
        if study == None:
            msg = f"Existing study {ds.StudyInstanceUID} not found in phi_lookup"
            logger.error(msg)
            raise RuntimeError(msg)

        # Find series in study:
        if study.series is not None and ds.SeriesInstanceUID is not None:
            series = next(
                (series for series in study.series if series.series_uid == ds.SeriesInstanceUID),
                None,
            )
        else:
            series = None

        if series == None:
            # NEW series, add to study:
            study.series.append(
                Series(
                    str(ds.SeriesInstanceUID),
                    str(ds.SeriesDescription),
                    str(ds.Modality),
                    1,
                )
            )
        else:
            series.instances += 1

    def _anonymize_element(self, dataset, data_element):
        # removes parentheses, spaces, and commas from tag
        tag = str(data_element.tag).translate(self._clean_tag_translate_table).upper()
        # Remove data_element if not in _tag_keep:
        if tag not in self.model._tag_keep:
            del dataset[tag]
            return
        operation = self.model._tag_keep[tag]
        value = data_element.value
        # Keep data_element if no operation:
        if operation == "":
            return
        # Anonymize operations:
        if "@empty" in operation:  # data_element.value:
            dataset[tag].value = ""
        elif "uid" in operation:
            anon_uid = self.model.get_anon_uid(value)
            if not anon_uid:
                next_uid_ndx = self.model.get_uid_count() + 1
                anon_uid = f"{self.project_model.uid_root}.{self.project_model.site_id}.{next_uid_ndx}"
                self.model.set_anon_uid(value, anon_uid)
            dataset[tag].value = anon_uid
            return
        elif "ptid" in operation:
            anon_pt_id = self.model.get_anon_patient_id(dataset.PatientID if hasattr(dataset, "PatientID") else "")
            if not anon_pt_id:
                anon_pt_id = self.get_next_anon_patient_id()
                self.model.set_anon_patient_id(dataset.PatientID, anon_pt_id)
            dataset[tag].value = anon_pt_id
        elif "acc" in operation:
            anon_acc_no = self.model.get_anon_acc_no(value)
            if not anon_acc_no:
                anon_acc_no = self.model.get_acc_no_count() + 1
                self.model.set_anon_acc_no(value, str(anon_acc_no))
            dataset[tag].value = str(anon_acc_no)
        elif "hashdate" in operation:
            _, anon_date = self._hash_date(
                data_element.value, dataset.PatientID if hasattr(dataset, "PatientID") else ""
            )
            dataset[tag].value = anon_date
        elif "@round" in operation:
            # TODO: operand is named round but it is age format specific, should be renamed round_age
            # create separate operand for round that can be used for other numeric values
            if value is None:
                return
            parameter = self.extract_first_digit(operation.replace("@round", ""))
            if parameter is None:
                logger.error(f"Invalid round operation: {operation}, ignoring operation, return unmodified value")
                dataset[tag].value = value
                return
            else:
                width = int(parameter)
            logger.debug(f"round_age: Age:{value} Width:{width}")
            dataset[tag].value = self._round_age(value, width)
            logger.debug(f"round_age: Result:{dataset[tag].value}")
        return

    def anonymize(self, source: DICOMNode | str, ds: Dataset) -> str | None:
        # Capture PHI and source for new studies:
        if self.model.get_anon_uid(ds.StudyInstanceUID) == None:
            self.capture_phi_from_new_study(ds, source)
        else:
            self.update_phi_from_new_instance(ds, source)

        # To minimize computation overhead DO NOT MAKE COPY of source dataset
        phi_instance_uid = ds.SOPInstanceUID  # if exception, remove this instance from uid_lookup

        try:
            # Anonymize dataset (overwrite phi dataset) (prevents dataset copy)
            # TODO: process in AnonymizerModel: Script line: <r en="T" t="privategroups">Remove private groups</r>
            ds.remove_private_tags()  # remove all private elements
            ds.walk(self._anonymize_element)
            # Handle missing PHI PatientID:
            if not hasattr(ds, "PatientID") or ds.PatientID == "":
                ds.PatientID = self.model.default_anon_pt_id

            # Handle Global Tags:
            ds.PatientIdentityRemoved = "YES"  # CS: (0012, 0062)
            ds.DeidentificationMethod = self.DEIDENTIFICATION_METHOD  # LO: (0012,0063)
            de_ident_seq = Sequence()  # SQ: (0012,0064)

            for code, descr in self.DEIDENTIFICATION_METHODS:
                item = Dataset()
                item.CodeValue = code
                item.CodingSchemeDesignator = "DCM"
                item.CodeMeaning = descr
                de_ident_seq.append(item)

            ds.DeidentificationMethodCodeSequence = de_ident_seq
            block = ds.private_block(0x0013, self.PRIVATE_BLOCK_NAME, create=True)
            block.add_new(0x1, "SH", self.project_model.project_name)
            block.add_new(0x3, "SH", self.project_model.site_id)

            logger.debug(f"ANON:\n{ds}")

            # Save ANONYMIZED dataset to dicom file in local storage:
            filename = local_storage_path(self.project_model.images_dir(), ds)
            logger.info(f"ANON STORE: {source} => {filename}")
            ds.save_as(filename, write_like_original=False)
            return None

        except Exception as e:
            # remove this phi instance UID from lookup if anonymization or storage fails
            # leave other PHI intact for this patient
            self.model.remove_uid(phi_instance_uid)
            qpath: Path = self.get_quarantine_path().joinpath(self.QUARANTINE_STORAGE_ERROR)
            filename: Path = local_storage_path(qpath, ds)
            try:
                error_msg: str = f"Storage error={e}, QUARANTINE {ds.SOPInstanceUID} to {filename}"
                logger.error(error_msg)
                ds.save_as(qpath)
            except:
                logger.error(f"Error writing incoming dataset to QUARANTINE: {e}")

            return error_msg

    def move_to_quarantine(self, file: Path, sub_dir: str):
        """Writes the file to the specified quarantine sub-directory.

        Args:
            file: file to be quarantined
            sub_dir: quarantine sub-directory

        Returns:
            True on successful move, False otherwise.
        """
        try:
            qpath = self.get_quarantine_path().joinpath(sub_dir, file.name)
            logger.error(f"QUARANTINE {file} to {qpath}")
            copyfile(file, qpath)
            return True
        except Exception as e:
            logger.error(f"Error Copying to QUARANTINE: {e}")
            return False

    def anonymize_file(self, file: Path) -> tuple[str | None, Dataset | None]:
        try:
            ds: Dataset = dcmread(file)
        except (FileNotFoundError, IsADirectoryError, PermissionError) as e:
            self.move_to_quarantine(file, self.QUARANTINE_FILE_READ_ERROR)
            return str(e), None
        except InvalidDicomError as e:
            self.move_to_quarantine(file, self.QUARANTINE_INVALID_DICOM)
            return str(e), None
        except Exception as e:
            self.move_to_quarantine(file, self.QUARANTINE_DICOM_READ_ERROR)
            return str(e), None

        # DICOM Dataset integrity checking:
        missing_attributes: list[str] = self.missing_attributes(ds)
        if missing_attributes != []:
            self.move_to_quarantine(file, self.QUARANTINE_MISSING_ATTRIBUTES)
            return f"Missing Attributes: {missing_attributes}", ds

        # Skip instance if already stored:
        if self.model.get_anon_uid(ds.SOPInstanceUID):
            logger.info(
                f"Instance already stored:{ds.PatientID}/{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}"
            )
            return (f"Instance already stored", ds)

        return self.anonymize(str(file), ds), ds

    def anonymize_dataset_and_store(self, source: DICOMNode | str, ds: Dataset | None) -> None:
        self._anon_Q.put((source, ds))
        return

    # TODO: OPTIMIZE: i/o bound, investigate thread pool for concurrent processing
    def _anonymize_worker(self, ds_Q: Queue) -> None:
        logger.info("_anonymize_worker start")

        self._active = True  # Worker thread active flag, signal back to controller constructor
        slices_before_save = 0
        while self._active:
            # timeslice worker thread for UX responsivity:
            time.sleep(self._anonymize_time_slice_interval)
            slices_before_save += 1
            try:
                source, ds = ds_Q.get(block=False)
                error_msg = self.anonymize(source, ds)
                # TODO: track specific anonymization errors of incoming datasets in lookup: [ds.SOPInstanceUID]=error_msg for UX
            except Empty:
                # Save Anonymizer Model every _anonymizer_model_autosave_interval seconds:
                if slices_before_save > (
                    self._anonymizer_model_autosave_interval / self._anonymize_time_slice_interval
                ):
                    self.save_model()
                    slices_before_save = 0
                continue
            except Exception as e:
                logger.error(f"Anonymizer Worker Error: {e}")
                continue

        logger.info("_anonymize_worker end")
        return
