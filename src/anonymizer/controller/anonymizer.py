"""Anonymization of DICOM datasets.

Public API
----------
QuarantineDirectories
    QuarantineDirectories type.

LookupTableMissError
    Raised when a required CTP lookup patient id is not in PHI (lookup not committed).

AnonymizerController
    The Anonymizer Controller class to handle the anonymization of DICOM datasets and manage the Anonymizer Model.
"""
import logging
import os
import re
import threading
import time
from enum import Enum
from pathlib import Path
from queue import Queue
from shutil import copyfile

from pydicom import DataElement, Dataset, dcmread
from pydicom.datadict import dictionary_VR
from pydicom.errors import InvalidDicomError
from pydicom.tag import Tag

from anonymizer.controller.dates import (
    DEFAULT_ANON_DATE,
    apply_day_delta,
    is_date_delta_operation,
    resolve_date_delta,
    stamp_dates_modified,
    stamp_rebase_registration,
    valid_date,
)
from anonymizer.controller.private_tags import private_tag_operation
from anonymizer.controller.script.document import (
    load_script_rules,
    tag_keep_from_document,
)
from anonymizer.controller.script.operands import (
    always_literal_text,
    is_remove_operation,
)
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.model.project import AT_INGEST, DICOMNode, ProjectModel
from anonymizer.utils.dicom import DeidMethodCode, record_deid_method_codes
from anonymizer.utils.storage.dicom_tree import DICOM_FILE_SUFFIX
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class QuarantineDirectories(Enum):
    INVALID_DICOM = _("Invalid_DICOM")
    DICOM_READ_ERROR = _("DICOM_Read_Error")
    MISSING_ATTRIBUTES = _("Missing_Attributes")
    INVALID_STORAGE_CLASS = _("Invalid_Storage_Class")
    CAPTURE_PHI_ERROR = _("Capture_PHI_Error")
    STORAGE_ERROR = _("Storage_Error")
    LOOKUP_MISS = _("Lookup_Miss")


class LookupTableMissError(Exception):
    """Raised when a required CTP lookup patient id is not in PHI (lookup not committed)."""

    def __init__(self, patient_id: str):
        self.patient_id = patient_id
        super().__init__(f"Lookup miss for patient_id={patient_id!r}")


class AnonymizerController:
    """
    The Anonymizer Controller class to handle the anonymization of DICOM datasets and manage the Anonymizer Model.
    """

    ANONYMIZER_MODEL_FILENAME = "AnonymizerModel.pkl"
    DEIDENTIFICATION_METHOD = "RSNA DICOM ANONYMIZER"  # (0012,0063)

    PRIVATE_BLOCK_NAME = "RSNA"
    DEFAULT_ANON_DATE = DEFAULT_ANON_DATE  # from controller.dates

    NUMBER_OF_DATASET_WORKER_THREADS = 1
    WORKER_THREAD_SLEEP_SECS = 0.075  # for UX responsiveness

    # if LoggingLevels.store_dicom_source is set, the incoming DICOM files will be stored in this directory
    # in the project's private directory, under the INCOMING_DICOM_DIR sub-directory
    INCOMING_DICOM_DIR = _("incoming")

    _clean_tag_translate_table: dict[int, int | None] = str.maketrans("", "", "() ,")

    # Required DICOM field attributes for accepting files:
    required_attributes: list[str] = [
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
        self.model = AnonymizerModel(
            project_model.site_id,
            project_model.uid_root,
            project_model.anonymizer_script_path,
            project_model.get_db_url(),
        )
        self.reload_script(project_model.anonymizer_script_path)
        self._model_change_flag = False
        logger.info(f"SAFE_PRIVATE enabled: {self.safe_private_enabled}")
        logger.info(f"Anonymizer Model initialised from script: {project_model.anonymizer_script_path}")

        self._anon_ds_Q: Queue = Queue()  # queue for dataset workers
        self._worker_threads = []

        # Spawn Anonymizer DATASET worker threads:
        for i in range(self.NUMBER_OF_DATASET_WORKER_THREADS):
            ds_worker = threading.Thread(
                target=self._anonymize_dataset_worker,
                name=f"AnonDatasetWorker_{i + 1}",
                args=(self._anon_ds_Q,),
            )
            ds_worker.start()
            self._worker_threads.append(ds_worker)

        self._active = True
        logger.info("Anonymizer Controller initialised")

    def reload_script(self, script_path: Path) -> None:
        """
        Load a script file into the runtime keep table.

        Args:
            script_path: Path to the anonymizer .script file.

        Returns:
            None.

        Raises:
            FileNotFoundError: When the script file is missing.
        """
        path = Path(script_path)
        document = load_script_rules(path)
        self.model.replace_tag_keep(
            tag_keep_from_document(document),
            script_path=path,
        )
        logger.info(f"Anonymizer keep-table reloaded from {path}")

    @property
    def safe_private_enabled(self) -> bool:
        """True when Retain Safe Private is one of the project's confidentiality options."""
        return DeidMethodCode.SAFE_PRIVATE in self.project_model.confidentiality_options

    def model_changed(self) -> bool:
        if self._model_change_flag:
            # Reset model change flag
            self._model_change_flag = False
            return True
        return False

    def idle(self) -> bool:
        return self._anon_ds_Q.empty()

    def queued(self) -> int:
        return self._anon_ds_Q.qsize()

    def _stop_worker_threads(self):
        logger.info("Stopping Anonymizer Worker Threads")

        if not self._active:
            logger.error("_stop_worker_threads but AnonymizerController not active")
            return

        # Send sentinel value to worker threads to terminate:
        for __ in range(self.NUMBER_OF_DATASET_WORKER_THREADS):
            self._anon_ds_Q.put((None, None))

        # Wait for all sentinal values to be processed
        self._anon_ds_Q.join()

        # Wait for all worker threads to finish
        for worker in self._worker_threads:
            worker.join()

        self._active = False

    def __del__(self):
        if self._active:
            self.stop()

    def stop(self):
        self._stop_worker_threads()
        # Always dispose after workers join so pooled sqlite connections are not
        # left open for GC (ResourceWarning on Python 3.13+).
        self.model.close()

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
        return Path(
            self.project_model.storage_dir,
            self.project_model.PRIVATE_DIR,
            self.project_model.QUARANTINE_DIR,
        )

    def _move_file_to_quarantine(self, file: Path, quarantine: QuarantineDirectories) -> bool:
        """Writes the file to the specified quarantine sub-directory.

        Args:
            file (Path): The file to be quarantined.
            sub_dir (str): The quarantine sub-directory.

        Returns:
            bool: True on successful move, False otherwise.
        """
        try:
            qpath = self.get_quarantine_path().joinpath(quarantine.value, f"{file.name}.{time.strftime('%H%M%S')}")
            logger.error(f"QUARANTINE {file} to {qpath}")
            if qpath.exists():
                logger.error(f"File {file} already exists")
                return False
            os.makedirs(qpath.parent, exist_ok=True)
            copyfile(file, qpath)
            return True
        except Exception as e:
            logger.error(f"Error Copying to QUARANTINE: {e}")
            return False

    def _write_dataset_to_quarantine(self, e: Exception, ds: Dataset, quarantine_error: QuarantineDirectories) -> str:
        """
        Writes the given dataset to the quarantine directory and logs any errors.

        Args:
            e (Exception): The exception that occurred.
            ds (Dataset): The dataset to be written to quarantine.
            quarantine_error (str): The quarantine error directory name.

        Returns:
            str: The error message indicating the storage error and the path to the saved dataset.
        """
        qpath: Path = self.get_quarantine_path().joinpath(quarantine_error.value)
        os.makedirs(qpath, exist_ok=True)
        filename: Path = self.local_storage_path(qpath, ds)
        try:
            estr = repr(e)
            error_msg: str = f"Storage Error = {estr}, QUARANTINE {ds.SOPInstanceUID} to {filename}"
            logger.error(error_msg)
            ds.save_as(filename)
        except Exception as e2:
            e2str = repr(e2)
            logger.critical(f"Critical Error writing incoming dataset to QUARANTINE: {e2str}")

        return error_msg

    def extract_first_digit(self, s: str) -> str | None:
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

    def _insert_always_missing_elements(self, ds: Dataset) -> None:
        """
        Create absent DICOM elements that the script marks with @always()….

        ds.walk only visits existing tags. CTP @always()LITERAL also
        requires creating the element when the source dataset omits it (for
        example fixed de-identification stamps). For each _tag_keep entry
        whose operation is @always()…, if the tag is missing, add it with
        the dictionary VR (or LO) and the literal text.

        Sequences (VR SQ) are skipped; nested creation is not supported here.

        Args:
            ds: Anonymized dataset after the script walk (mutated in place).

        Returns:
            None.
        """

        for tag_hex, operation in self.model._tag_keep.items():
            op = str(operation or "").strip()
            if not op.lower().startswith("@always()"):
                continue
            literal = always_literal_text(op)
            if literal is None:
                continue
            try:
                tag = Tag(int(tag_hex, 16))
            except ValueError:
                logger.warning("Invalid tag in script for @always(): %s", tag_hex)
                continue
            if tag in ds:
                continue
            try:
                vr = dictionary_VR(tag)
            except Exception:
                vr = "LO"
            if str(vr).upper() == "SQ":
                continue
            try:
                ds.add_new(tag, vr, literal)
            except Exception:
                logger.warning(
                    "Unable to create %s via @always(): %s",
                    tag_hex,
                    op,
                    exc_info=True,
                )

    def _anonymize_element(
        self,
        dataset: Dataset,
        data_element: DataElement,
        phi_ptid: str,
        anon_ptid: str,
        anon_acc_no: str | None,
        date_delta: int | None,
    ) -> None:
        """
        Apply script keep/remove/transform rules to one data element.

        Args:
            dataset: Dataset containing the element (mutated).
            data_element: Element to anonymize.
            phi_ptid: PHI PatientID.
            anon_ptid: Anonymized PatientID.
            anon_acc_no: Anonymized accession number, or None.
            date_delta: The file's single resolved day delta for date
                operations, or None when no delta could be resolved.

        Returns:
            None.
        """
        tag = str(data_element.tag).translate(self._clean_tag_translate_table).upper()

        if data_element.tag.is_private:
            operation = private_tag_operation(
                dataset,
                data_element,
                retain_uids=DeidMethodCode.RETAIN_UIDS
                in self.project_model.confidentiality_options,
                date_delta=date_delta,
            )
        elif tag in self.model._tag_keep:
            operation = str(self.model._tag_keep[tag] or "").strip() or "@keep"
        else:
            operation = "@remove()"

        if is_remove_operation(operation):
            del dataset[tag]
            return

        if "@keep" in operation or "@safe" in operation:
            return

        value = data_element.value
        raw = str(value) if value is not None else ""

        if "@empty" in operation:
            dataset[tag].value = ""
        elif "@uid" in operation:
            dataset[tag].value = self.model.get_or_create_anon_uid(value)
        elif "@ptid" in operation:
            dataset[tag].value = anon_ptid
        elif "@acc" in operation:
            if value == "":
                dataset[tag].value = ""
            elif anon_acc_no:
                dataset[tag].value = anon_acc_no
        elif is_date_delta_operation(operation):
            # Date ops only write DA/DT calendar text. Numeric private VRs (e.g. SL
            # unix-time) cannot hold YYYYMMDD; remove those tags instead.
            vr = (getattr(data_element, "VR", None) or "").upper()
            if vr not in {"DA", "DT"}:
                del dataset[tag]
                return
            if date_delta is None:
                logger.error(f"No date delta resolved for patient {phi_ptid}; leaving {tag} unchanged ({operation})")
                return
            # @hashdate: invalid/empty date or missing PatientID → fixed sentinel (not a shifted value).
            if "@hashdate" in operation and (not phi_ptid or not valid_date(raw.strip()[:8])):
                dataset[tag].value = DEFAULT_ANON_DATE
            else:
                dataset[tag].value = apply_day_delta(raw, date_delta)
        elif "@lookup" in operation:
            dataset[tag].value = anon_ptid
        elif "@round" in operation:
            # TODO: operand is named round but it is age format specific, should be renamed round_age
            if value is None:
                return
            parameter = self.extract_first_digit(operation.replace("@round", ""))
            if parameter is None:
                logger.error(f"Invalid round operation: {operation}, ignoring operation, return unmodified value")
                dataset[tag].value = value
                return
            width = int(parameter)
            logger.debug(f"round_age: Age:{value} Width:{width}")
            dataset[tag].value = self._round_age(value, width)
            logger.debug(f"round_age: Result:{dataset[tag].value}")
        else:
            literal = always_literal_text(operation)
            if literal is not None:
                dataset[tag].value = literal

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

        Notes:
            - The anonymization process involves removing PHI from the dataset and saving the anonymized dataset to a DICOM file in project's storage directory.
            - If an error occurs capturing PHI or storing the anonymized file, the dataset is moved to the quarantine for further analysis.
        """
        self._model_change_flag = True

        # If User has set to store incoming dicom source, trace phi UIDs and store incoming phi file in private directory
        if self.project_model.logging_levels.store_dicom_source:
            logger.debug(f"=>{ds.PatientID}/{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}")

            filename = self.local_storage_path(self.project_model.private_dir() / self.INCOMING_DICOM_DIR, ds)
            logger.debug(f"SOURCE STORE: {source} => {filename}")
            try:
                ds.save_as(filename)
            except Exception as e:
                logger.error(f"Error storing source file: {str(e)}")

        # Resolve the file's single date delta from the StudyDate operation,
        # then verify valid DICOM format and CAPTURE PHI and source into DATABASE:
        phi_patient_id = str(ds.PatientID).strip() if hasattr(ds, "PatientID") else ""
        phi_record = self.model.get_phi_by_phi_patient_id(phi_patient_id)
        phi_study_date = str(getattr(ds, "StudyDate", "") or "").strip() or None
        base_date = phi_record.base_date if phi_record is not None else None
        date_delta = resolve_date_delta(
            self.model._tag_keep.get("00080020") or None,
            patient_id=phi_patient_id,
            days_from_lookup=(
                phi_record.date_offset
                if phi_record is not None and phi_record.date_offset is not None
                else 0
            ),
            base_date=phi_record.base_date if phi_record is not None else None,
        )
        try:
            phi_ptid, anon_ptid, anon_acc_no, _date_offset = self.model.capture_phi(
                str(source), ds, date_delta or 0
            )
        except KeyError as e:
            return self._write_dataset_to_quarantine(e, ds, QuarantineDirectories.LOOKUP_MISS)
        except ValueError as e:
            return self._write_dataset_to_quarantine(e, ds, QuarantineDirectories.INVALID_DICOM)
        except Exception as e:
            return self._write_dataset_to_quarantine(e, ds, QuarantineDirectories.CAPTURE_PHI_ERROR)

        phi_instance_uid = ds.SOPInstanceUID  # if exception, remove this instance from uid_lookup
        try:
            # To minimize memory/computation overhead DO NOT MAKE COPY of source dataset
            # Anonymize dataset (overwrite phi dataset) (prevents dataset copy)

            if not self.safe_private_enabled:
                ds.remove_private_tags()

            # if ds.PatientID not present, set to '' so that anonymization script can process the element:
            if not hasattr(ds, "PatientID"):
                ds.PatientID = ""

            def pydicom_callback(current_ds_item, data_element):
                self._anonymize_element(
                    current_ds_item,
                    data_element,
                    phi_ptid,
                    anon_ptid,
                    None if anon_acc_no is None else str(anon_acc_no),
                    date_delta,
                )

            ds.walk(pydicom_callback)  # recursive by default, recurses into embedded dataset sequences

            # Create missing non-SQ elements whose script uses @always()… (CTP create-if-missing).
            self._insert_always_missing_elements(ds)

            if self.model.date_operands_present:
                stamp_dates_modified(ds)
            if base_date:
                stamp_rebase_registration(ds, phi_study_date, base_date)

            # All elements now anonymized according to script, now handle Anonymization specific Tags:
            ds.PatientIdentityRemoved = "YES"  # CS: (0012, 0062)
            ds.DeidentificationMethod = self.DEIDENTIFICATION_METHOD  # LO: (0012,0063)
            record_deid_method_codes(ds, self.project_model.confidentiality_options & AT_INGEST)
            block = ds.private_block(0x0013, self.PRIVATE_BLOCK_NAME, create=True)
            block.add_new(0x1, "SH", self.project_model.site_id)
            block.add_new(0x3, "SH", self.project_model.project_name)

            # Save ANONYMIZED dataset to dicom file in local storage:
            filename = self.local_storage_path(self.project_model.images_dir(), ds)
            logger.debug(f"ANON STORE: {source} => {filename}")

            # TODO: Optimize / Transcoding / DICOM Compliance File Verification - as per extra project options
            ds.save_as(filename, enforce_file_format=True)

            return None

        except Exception as e:
            # Remove this phi instance UID from lookup if anonymization or storage fails
            # Leave other PHI intact for this patient
            self.model.remove_uid(phi_instance_uid)
            return self._write_dataset_to_quarantine(e, ds, QuarantineDirectories.STORAGE_ERROR)

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
        self._model_change_flag = True

        try:
            ds: Dataset = dcmread(file)
        except (FileNotFoundError, IsADirectoryError, PermissionError) as e:
            logger.error(str(e))
            return str(e), None
        except InvalidDicomError as e:
            self._move_file_to_quarantine(file, QuarantineDirectories.INVALID_DICOM)
            return str(e) + " -> " + _("Quarantined"), None
        except Exception as e:
            self._move_file_to_quarantine(file, QuarantineDirectories.DICOM_READ_ERROR)
            return str(e) + " -> " + _("Quarantined"), None

        # DICOM Dataset integrity checking:
        missing_attributes: list[str] = self.missing_attributes(ds)
        if missing_attributes != []:
            self._move_file_to_quarantine(file, QuarantineDirectories.MISSING_ATTRIBUTES)
            return _("Missing Attributes") + f": {missing_attributes}" + " -> " + _("Quarantined"), ds

        # Skip instance if already stored:
        if self.model.instance_received(ds.SOPInstanceUID):
            logger.info(
                f"Instance already stored:{ds.PatientID}/{ds.StudyInstanceUID}/{ds.SeriesInstanceUID}/{ds.SOPInstanceUID}"
            )
            return (_("Instance already stored"), ds)

        # Ensure Storage Class (SOPClassUID which is a required attribute) is present in project storage classes
        if ds.SOPClassUID not in self.project_model.storage_classes:
            self._move_file_to_quarantine(file, QuarantineDirectories.INVALID_STORAGE_CLASS)
            return _("Storage Class mismatch") + f": {ds.SOPClassUID}" + " -> " + _("Quarantined"), ds

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
        self._anon_ds_Q.put((source, ds))

    def _anonymize_dataset_worker(self, ds_Q: Queue) -> None:
        """
        An internal worker method that performs the anonymization process.

        Args:
            ds_Q (Queue): The queue containing the data sources to be anonymized.

        Returns:
            None
        """
        logger.info(f"thread={threading.current_thread().name} start")

        try:
            while True:
                time.sleep(self.WORKER_THREAD_SLEEP_SECS)
                source, ds = ds_Q.get()  # Blocks by default
                if ds is None:  # sentinel value
                    ds_Q.task_done()
                    break
                self.anonymize(source, ds)
                ds_Q.task_done()
        finally:
            # Ensure this worker's scoped session is dropped before the thread exits.
            self.model.session_factory.remove()
            logger.info(f"thread={threading.current_thread().name} end")
