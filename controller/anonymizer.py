# Description: Anonymization of DICOM datasets
# See https://mircwiki.rsna.org/index.php?title=The_CTP_DICOM_Anonymizer for legacy anonymizer documentation
import os
import time
import logging
import threading
import hashlib
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
from pydicom import Dataset, Sequence, dcmread
from utils.translate import _
from utils.storage import local_storage_path
from model.project import DICOMNode, Study, PHI, ProjectModel
from model.anonymizer import AnonymizerModel

logger = logging.getLogger(__name__)

# TODO: where best to put these string constants?
# TODO: link to app title & version
deidentification_method = _("RSNA DICOM ANONYMIZER")
deidentification_methods = [
    ("113100", _("Basic Application Confidentiality Profile")),
    (
        "113107",
        _("Retain Longitudinal Temporal Information Modified Dates Option"),
    ),
    ("113108", _("Retain Patient Characteristics Option")),
]
private_block_name = _("RSNA")


class AnonymizerController:
    default_anon_date = "20000101"  # if source date is invalid or before 19000101
    _anonymize_time_slice_interval: float = 0.1  # seconds
    _anonymize_batch_size: int = 40  # number of items to process in a batch
    _clean_tag_translate_table = str.maketrans("", "", "() ,")
    # Required DICOM field attributes for accepting files:
    required_attributes = [
        "PatientID",
        "PatientName",
        "StudyInstanceUID",
        # "StudyDate",
        # "AccessionNumber",
        "Modality",
        "SeriesNumber",
        "InstanceNumber",
    ]

    def __init__(self, project_model: ProjectModel):
        self.project_model = project_model

        # If present, load pickled AnonymizerModel from project directory:
        anon_pkl_path = Path(project_model.storage_dir, AnonymizerModel.pickle_filename)
        if os.path.exists(anon_pkl_path):
            with open(anon_pkl_path, "rb") as pkl_file:
                self.model = pickle.load(pkl_file)
                logger.info(f"Anonymizer Model loaded from: {anon_pkl_path}")
        else:
            # Initialise AnonymizerModel if no pickle file found in project directory:
            self.model = AnonymizerModel(project_model.anonymizer_script_path)
            logger.info(
                f"Anonymizer Model initialised from: {project_model.anonymizer_script_path}"
            )

        self._anon_Q: Queue = Queue()

        self._active = True

        self._worker = threading.Thread(
            target=self._anonymize_worker,
            args=(self._anon_Q,),
            daemon=True,
        ).start()

    def __del__(self):
        self._active = False

    def stop(self):
        self._active = False

    def missing_attributes(self, ds: Dataset) -> list[str]:
        return [
            attr_name
            for attr_name in self.required_attributes
            if attr_name not in ds or getattr(ds, attr_name) == ""
        ]

    def save_model(self):
        anon_pkl_path = Path(
            self.project_model.storage_dir, AnonymizerModel.pickle_filename
        )
        with open(anon_pkl_path, "wb") as pkl_file:
            pickle.dump(self.model, pkl_file)
            pkl_file.close()

        logger.debug(f"Model saved to: {anon_pkl_path}")

    def get_next_anon_patient_id(self) -> str:
        next_patient_index = self.model.get_patient_id_count() + 1
        return f"{self.project_model.site_id}-{next_patient_index:06}"

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
            return 0, self.default_anon_date

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

    # Extract PHI from new study and store:
    def capture_phi_from_new_study(self, phi_ds: Dataset, source: DICOMNode | str):
        def study_from_dataset(ds: Dataset) -> Study:
            return Study(
                str(ds.StudyDate) if hasattr(phi_ds, "StudyDate") else "?",
                self._hash_date(ds.StudyDate, phi_ds.PatientID)[0]
                if hasattr(phi_ds, "StudyDate") and hasattr(phi_ds, "PatientID")
                else 0,
                str(ds.AccessionNumber) if hasattr(phi_ds, "AccessionNumber") else "?",
                str(ds.StudyInstanceUID)
                if hasattr(phi_ds, "StudyInstanceUID")
                else "?",
                source,
            )

        anon_patient_id = self.model.get_anon_patient_id(phi_ds.PatientID)

        if anon_patient_id == None:  # New patient
            new_anon_patient_id = self.get_next_anon_patient_id()
            phi = PHI(
                str(phi_ds.PatientName),
                str(phi_ds.PatientID),
                [
                    study_from_dataset(phi_ds),
                ],
            )
            self.model.set_phi(new_anon_patient_id, phi)

        else:  # Existing patient now with more than one study
            phi = self.model.get_phi(anon_patient_id)
            if phi == None:
                raise Exception(
                    f"Existing patient {anon_patient_id} not found in phi_lookup"
                )
            phi.studies.append(study_from_dataset(phi_ds))
            self.model.set_phi(anon_patient_id, phi)

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
            anon_pt_id = self.model.get_anon_patient_id(dataset.PatientID)
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
            _, anon_date = self._hash_date(data_element.value, dataset.PatientID)
            dataset[tag].value = anon_date
        return

    def anonymize_dataset_and_store(
        self, source: DICOMNode | str, ds: Dataset | None, dir: Path
    ) -> None:
        self._anon_Q.put((source, ds, dir))
        return

    # TODO: Error handling & reporting - how to reflect missing attributes, queue overflows & file system errors back to UX?
    # TODO: OPTIMIZE: i/o bound, investigate thread pool for processing batch concurrently
    def _anonymize_worker(self, ds_Q: Queue) -> None:
        logger.info("_anonymize_worker start")
        while self._active:
            # timeslice worker thread for UX responsivity:
            time.sleep(self._anonymize_time_slice_interval)

            while not ds_Q.empty():
                logger.debug(
                    f"_anonymize_worker processing batch size: {self._anonymize_batch_size}"
                )
                batch = []
                for _ in range(
                    self._anonymize_batch_size
                ):  # Process a batch of items at a time
                    if not ds_Q.empty():
                        batch.append(ds_Q.get())

                for item in batch:
                    source, ds, dir = item

                    # Load dataset from file if not provided: (eg. via local file/dir import)
                    if ds is None:
                        try:
                            assert os.path.exists(source)
                            ds = dcmread(source)
                        except Exception as e:
                            logger.error(f"dcmread error: {source}: {e}")
                            continue

                        # Ensure dataset has required attributes:
                        missing_attributes = self.missing_attributes(ds)
                        if missing_attributes != []:
                            logger.error(
                                f"Incoming dataset is missing required attributes: {missing_attributes}"
                            )
                            logger.error(f"\n{ds}")
                            continue

                        # Return success if instance is already stored:
                        if self.model.get_anon_uid(ds.SOPInstanceUID):
                            logger.info(
                                f"Instance already stored: {ds.PatientID} {ds.SOPInstanceUID}"
                            )
                            continue

                    # TOOO: add Trace level?
                    # logger.debug(f"PHI:\n{ds}")

                    # Capture PHI and store for new studies:
                    if self.model.get_anon_uid(ds.StudyInstanceUID) == None:
                        self.capture_phi_from_new_study(ds, source)

                    # Anonymize dataset (overwrite phi dataset) (prevents dataset copy)
                    ds.remove_private_tags()  # TODO: provide a switch for this? how does java anon handle this? see <r> tag
                    ds.walk(self._anonymize_element)

                    # Handle Global Tags:
                    ds.PatientIdentityRemoved = "YES"  # CS: (0012, 0062)
                    ds.DeidentificationMethod = (
                        deidentification_method  # LO: (0012,0063)
                    )
                    de_ident_seq = Sequence()  # SQ: (0012,0064)

                    for code, descr in deidentification_methods:
                        item = Dataset()
                        item.CodeValue = code
                        item.CodingSchemeDesignator = "DCM"
                        item.CodeMeaning = descr
                        de_ident_seq.append(item)

                    ds.DeidentificationMethodCodeSequence = de_ident_seq
                    block = ds.private_block(0x0013, private_block_name, create=True)
                    block.add_new(0x1, "SH", self.project_model.project_name)
                    block.add_new(0x2, "SH", self.project_model.trial_name)
                    block.add_new(0x3, "SH", self.project_model.site_id)

                    # logger.debug(f"ANON:\n{ds}")

                    # TODO: custom filtering via script specifying dicom field patterns to keep / quarantine / discard
                    # Save anonymized dataset to dicom file in local storage:
                    filename = local_storage_path(dir, ds)
                    logger.info(f"ANON STORE: {source} => {filename}")
                    try:
                        ds.save_as(filename, write_like_original=False)
                    except Exception as exception:
                        logger.error("Failed writing instance to storage directory")
                        logger.exception(exception)

                # Save model to disk after processing batch:
                self.save_model()

        logger.info("_anonymize_worker end")
        return
