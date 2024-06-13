# Description: Anonymization of DICOM datasets
# See https://mircwiki.rsna.org/index.php?title=The_CTP_DICOM_Anonymizer for legacy anonymizer documentation
import os
import time
from shutil import copyfile
import re
import logging
import threading
import hashlib
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
from pydicom import Dataset, Sequence, dcmread
from pydicom.errors import InvalidDicomError
from utils.translate import _
from utils.storage import DICOM_FILE_SUFFIX
from model.project import DICOMNode, ProjectModel
from model.anonymizer import AnonymizerModel

logger = logging.getLogger(__name__)


class AnonymizerController:
    """
    The Anonymizer Controller class to handle the anonymization of DICOM datasets and manage the Anonymizer Model.
    """

    ANONYMIZER_MODEL_FILENAME = "AnonymizerModel.pkl"
    DEIDENTIFICATION_METHOD = "RSNA DICOM ANONYMIZER"  # (0012,0063)

    # Quarantine Errors / Sub-directories:
    QUARANTINE_INVALID_DICOM = "Invalid_DICOM"
    QUARANTINE_DICOM_READ_ERROR = "DICOM_Read_Error"
    QUARANTINE_MISSING_ATTRIBUTES = "Missing_Attributes"
    QUARANTINE_INVALID_STORAGE_CLASS = "Invalid_Storage_Class"
    QUARANTINE_CAPTURE_PHI_ERROR = "Capture_PHI_Error"
    QUARANTINE_STORAGE_ERROR = "Storage_Error"

    # See assets/docs/RSNA-Covid-19-Deindentification-Protocol.pdf
    # TODO: if user edits default anonymization script these values should be updated accordingly
    # TODO: simpler to provide UX for different de-identification methods, esp. enable/disable sub-options
    # DeIdentificationMethodCodeSequence (0012,0064)
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

    NUMBER_OF_WORKER_THREADS = 2
    WORKER_THREAD_SLEEP_SECS = 0.075  # for UX responsiveness
    MODEL_AUTOSAVE_INTERVAL_SECS = 30

    _clean_tag_translate_table = str.maketrans("", "", "() ,")

    # Required DICOM field attributes for accepting files:
    required_attributes = [
        "SOPClassUID",
        "SOPInstanceUID",
        "StudyInstanceUID",
        "SeriesInstanceUID",
    ]

    def __init__(self, project_model: ProjectModel):
        self._active = False
        self.project_model = project_model
        # Initialise AnonymizerModel datafile full path:
        self.model_filename = Path(self.project_model.private_dir(), self.ANONYMIZER_MODEL_FILENAME)
        # If present, load pickled AnonymizerModel from project directory:
        if self.model_filename.exists():
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
                self.model.__dict__.update(
                    file_model.__dict__
                )  # copy over corresponding attributes from the old model (file_model)
                self.model._version = AnonymizerModel.MODEL_VERSION  # upgrade version
                self.save_model()
                logger.info(f"Anonymizer Model upgraded successfully to version: {self.model._version}")
            else:
                self.model: AnonymizerModel = file_model

        else:
            # Initialise New Default AnonymizerModel if no pickle file found in project directory:
            self.model = AnonymizerModel(
                project_model.site_id, project_model.uid_root, project_model.anonymizer_script_path
            )
            logger.info(f"New Default Anonymizer Model initialised from script: {project_model.anonymizer_script_path}")

        self._anon_Q: Queue = Queue()
        self._worker_threads = []

        # Spawn Anonymizer worker threads:
        for i in range(self.NUMBER_OF_WORKER_THREADS):
            worker = self._worker = threading.Thread(
                target=self._anonymize_worker,
                name=f"AnonWorker_{i+1}",
                args=(self._anon_Q,),
                # daemon=True,
            )
            worker.start()
            self._worker_threads.append(worker)

        # Setup Model Autosave Thread:
        self._model_change_flag = False
        self._autosave_event = threading.Event()
        self._autosave_worker_thread = threading.Thread(
            target=self._autosave_manager, name="AnonModelSaver", daemon=True
        )
        self._autosave_worker_thread.start()

        self._active = True
        logger.info("Anonymizer Controller initialised")

    def model_changed(self) -> bool:
        return self._model_change_flag

    def _stop_worker_threads(self):
        logger.info("Stopping Anonymizer Worker Threads")

        if not self._active:
            logger.error("_stop_worker_threads but controller not active")
            return

        # Send sentinel value to worker threads to terminate:
        for _ in range(self.NUMBER_OF_WORKER_THREADS):
            self._anon_Q.put((None, None))

        # Wait for all tasks to be processed
        self._anon_Q.join()

        # Wait for all worker threads to finish
        for worker in self._worker_threads:
            worker.join()

        self._autosave_event.set()
        self._active = False

    def __del__(self):
        if self._active:
            self._stop_worker_threads()

    def stop(self):
        self._stop_worker_threads()

    def missing_attributes(self, ds: Dataset) -> list[str]:
        return [
            attr_name for attr_name in self.required_attributes if attr_name not in ds or getattr(ds, attr_name) == ""
        ]

    def local_storage_path(self, base_dir: Path, ds: Dataset) -> Path:
        """
        Generate the local storage path in the anonymizer store for a given anonymized dataset.

        Args:
            base_dir (Path): The base directory where the dataset will be stored.
            ds (Dataset): The dataset containing the necessary attributes.

        Returns:
            Path: The local storage path for the dataset.
        """
        if self.missing_attributes(ds):
            raise ValueError(_("Dataset missing required attributes"))

        dest_path = Path(
            base_dir,
            ds.get("PatientID", self.model.default_anon_pt_id),
            ds.StudyInstanceUID,
            ds.SeriesInstanceUID,
            ds.SOPInstanceUID + DICOM_FILE_SUFFIX,
        )
        # Ensure all directories in the path exist
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        return dest_path

    def get_quarantine_path(self) -> Path:
        return Path(self.project_model.storage_dir, self.project_model.PRIVATE_DIR, self.project_model.QUARANTINE_DIR)

    def _write_to_quarantine(self, e: Exception, ds: Dataset, quarantine_error: str) -> str:
        """
        Writes the given dataset to the quarantine directory and logs any errors.

        Args:
            e (Exception): The exception that occurred.
            ds (Dataset): The dataset to be written to quarantine.
            quarantine_error (str): The quarantine error directory name.

        Returns:
            str: The error message indicating the storage error and the path to the saved dataset.
        """
        qpath: Path = self.get_quarantine_path().joinpath(quarantine_error)
        os.makedirs(qpath, exist_ok=True)
        filename: Path = self.local_storage_path(qpath, ds)
        try:
            error_msg: str = f"Storage Error = {e}, QUARANTINE {ds.SOPInstanceUID} to {filename}"
            logger.error(error_msg)
            ds.save_as(filename, write_like_original=True)
        except:
            logger.critical(f"Critical Error writing incoming dataset to QUARANTINE: {e}")

        return error_msg

    def _autosave_manager(self):
        logger.info(f"thread={threading.current_thread().name} start")

        while self._active:
            self._autosave_event.wait(timeout=self.MODEL_AUTOSAVE_INTERVAL_SECS)
            if self._model_change_flag:
                self.save_model()
                self._model_change_flag = False

        logger.info(f"thread={threading.current_thread().name} end")

    def save_model(self) -> bool:
        self.model.save(self.model_filename)

    def valid_date(self, date_str: str) -> bool:
        """
        Check if a date string is valid.
        Date must be YYYYMMDD format and a valid date after 19000101:

        Args:
            date_str (str): The date string to be validated.

        Returns:
            bool: True if the date string is valid, False otherwise.
        """
        try:
            date_obj = datetime.strptime(date_str, "%Y%m%d")
            if date_obj < datetime(1900, 1, 1):
                return False
            return True
        except ValueError:
            return False

    def _hash_date(self, date: str, patient_id: str) -> tuple[int, str]:
        """
        Hashes the given date based on the patient ID.
        Increment date by a number of days determined by MD5 hash of PatientID mod 10 years

        Args:
            date (str): The date to be hashed in the format "YYYYMMDD".
            patient_id (str): The patient ID used for hashing.

        Returns:
            tuple[int, str]: A tuple containing the number of days incremented and the formatted hashed date.
            If invalid date or empty PatientID, returns (0, DEFAULT_ANON_DATE)
        """
        if not self.valid_date(date) or not len(patient_id):
            return 0, self.DEFAULT_ANON_DATE

        # Calculate MD5 hash of PatientID
        md5_hash = hashlib.md5(patient_id.encode()).hexdigest()
        # Convert MD5 hash to an integer
        hash_integer = int(md5_hash, 16)
        # Calculate number of days to increment (modulus 10 years in days)
        days_to_increment = hash_integer % 3652
        # Parse the input date as a datetime object
        input_date = datetime.strptime(date, "%Y%m%d")
        # Increment the date by the calculated number of days
        incremented_date = input_date + timedelta(days=days_to_increment)
        # Format the incremented date as "YYYYMMDD"
        formatted_date = incremented_date.strftime("%Y%m%d")

        return days_to_increment, formatted_date

    def extract_first_digit(self, s: str) -> str:
        """
        Extracts the first digit from a given string.

        Args:
            s (str): The input string.

        Returns:
            str: The first digit found in the string, or None if no digit is found.
        """
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

    def _anonymize_element(self, dataset, data_element) -> None:
        """
        Anonymizes a data element in the dataset based on the specified operations.

        Args:
            dataset (dict): The dataset containing the data elements.
            data_element (DataElement): The data element to be anonymized.

        Returns:
            None
        """
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
        if "@empty" in operation:
            dataset[tag].value = ""
        elif "uid" in operation:
            anon_uid = self.model.get_anon_uid(value)
            if not anon_uid:
                anon_uid = self.model.get_next_anon_uid(value)
            dataset[tag].value = anon_uid
        elif "acc" in operation:
            anon_acc_no = self.model.get_anon_acc_no(value)
            if not anon_acc_no:
                anon_acc_no = self.model.get_next_anon_acc_no(value)
            dataset[tag].value = str(anon_acc_no)
        elif "@hashdate" in operation:
            _, anon_date = self._hash_date(data_element.value, dataset.get("PatientID", ""))
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

    def anonymize(self, source: DICOMNode | str, ds: Dataset) -> str | None:
        """
        Anonymizes the DICOM dataset by removing PHI (Protected Health Information) and
        saving the anonymized dataset to a DICOM file.

        Args:
            source (DICOMNode | str): The source of the DICOM dataset.
            ds (Dataset): The DICOM dataset to be anonymized.

        Returns:
            str | None: If an error occurs during the anonymization process, returns the error message.
                        Otherwise, returns None.

        Raises:
            LookupError: If an error occurs while capturing PHI from the dataset.

        Notes:
            - The anonymization process involves removing PHI from the dataset and saving the anonymized dataset to a DICOM file.
            - If an error occurs during the anonymization process, the dataset is moved to the quarantine for further analysis.
        """
        self._model_change_flag = True  # for autosave manager

        # Calculate date delta from StudyDate and PatientID:
        date_delta = 0
        if hasattr(ds, "StudyDate") and hasattr(ds, "PatientID"):
            date_delta, _ = self._hash_date(ds.StudyDate, ds.PatientID)

        # Capture PHI and source:
        try:
            self.model.capture_phi(source, ds, date_delta)  # May raise LookupError
        except LookupError as e:
            return self._write_to_quarantine(e, ds, self.QUARANTINE_CAPTURE_PHI_ERROR)

        try:
            # To minimize memory/computation overhead DO NOT MAKE COPY of source dataset
            phi_instance_uid = ds.SOPInstanceUID  # if exception, remove this instance from uid_lookup

            # Anonymize dataset (overwrite phi dataset) (prevents dataset copy)
            ds.remove_private_tags()  # remove all private elements (odd group number)
            ds.walk(self._anonymize_element)  # recursive by default, recurses into embedded dataset sequences
            # All elements now anonymized according to script, finally anonymizer PatientID and PatientName elements:
            anon_ptid = self.model.get_anon_patient_id(ds.get("PatientID", ""))  # created by capture_phi
            if anon_ptid is None:
                logger.critical(
                    f"Critical error, PHI Capture did not create anonymized patient id, resort to default: {self.model.default_anon_pt_id}"
                )
                anon_ptid = self.model.default_anon_pt_id
            ds.PatientID = anon_ptid
            ds.PatientName = anon_ptid

            # Handle Anonymization specific Tags:
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
            block.add_new(0x1, "SH", self.project_model.site_id)
            block.add_new(0x3, "SH", self.project_model.project_name)

            # Save ANONYMIZED dataset to dicom file in local storage:
            filename = self.local_storage_path(self.project_model.images_dir(), ds)
            logger.debug(f"ANON STORE: {source} => {filename}")

            # TODO: Optimize / Transcoding / DICOM Compliance File Verification - as per extra project options
            # see options for write_like_original=True
            ds.save_as(filename, write_like_original=False)
            return None

        except Exception as e:
            # Remove this phi instance UID from lookup if anonymization or storage fails
            # Leave other PHI intact for this patient
            self.model.remove_uid(phi_instance_uid)
            return self._write_to_quarantine(e, ds, self.QUARANTINE_STORAGE_ERROR)

    def move_to_quarantine(self, file: Path, sub_dir: str) -> bool:
        """Writes the file to the specified quarantine sub-directory.

        Args:
            file (Path): The file to be quarantined.
            sub_dir (str): The quarantine sub-directory.

        Returns:
            bool: True on successful move, False otherwise.
        """
        try:
            qpath = self.get_quarantine_path().joinpath(sub_dir, file.name)
            logger.error(f"QUARANTINE {file} to {qpath}")
            os.makedirs(qpath.parent, exist_ok=True)
            copyfile(file, qpath)
            return True
        except Exception as e:
            logger.error(f"Error Copying to QUARANTINE: {e}")
            return False

    def anonymize_file(self, file: Path) -> tuple[str | None, Dataset | None]:
        """
        Anonymizes a DICOM file.

        Args:
            file (Path): The path to the DICOM file to be anonymized.

        Returns:
            tuple[str | None, Dataset | None]: A tuple containing an error message (if any) and the anonymized DICOM dataset.
                - If an error occurs during the anonymization process, the error message will be returned along with None.
                - If the anonymization is successful, None will be returned as the error message along with the anonymized DICOM dataset.

        Raises:
            FileNotFoundError: If the specified file is not found.
            IsADirectoryError: If the specified file is a directory.
            PermissionError: If there is a permission error while accessing the file.
            InvalidDicomError: If the DICOM file is invalid.
            Exception: If any other unexpected exception occurs during the anonymization process.
        """
        try:
            ds: Dataset = dcmread(file)
        except (FileNotFoundError, IsADirectoryError, PermissionError) as e:
            logger.error(str(e))
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

        # Ensure Storage Class (SOPClassUID which is a required attribute) is present in project storage classes
        if ds.SOPClassUID not in self.project_model.storage_classes:
            self.move_to_quarantine(file, self.QUARANTINE_INVALID_STORAGE_CLASS)
            return f"Storage Class: {ds.SOPClassUID} mismatch", ds

        return self.anonymize(str(file), ds), ds

    def anonymize_dataset_ex(self, source: DICOMNode | str, ds: Dataset | None) -> None:
        """
        Schedules a dataset to be anonymized by background worker thread

        Args:
            source (DICOMNode | str): The source of the dataset.
            ds (Dataset | None): The dataset to be anonymized.
                ds = None is the sentinel value to terminate the worker thread(s)

        Returns:
            None
        """
        self._anon_Q.put((source, ds))

    def _anonymize_worker(self, ds_Q: Queue) -> None:
        """
        An internal worker method that performs the anonymization process.

        Args:
            ds_Q (Queue): The queue containing the data sources to be anonymized.

        Returns:
            None
        """
        logger.info(f"thread={threading.current_thread().name} start")

        while True:
            time.sleep(self.WORKER_THREAD_SLEEP_SECS)
            source, ds = ds_Q.get()  # Blocks by default
            if ds is None:  # sentinel value
                ds_Q.task_done()
                break
            self.anonymize(source, ds)
            ds_Q.task_done()

        logger.info(f"thread={threading.current_thread().name} end")