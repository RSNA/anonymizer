# Description: Anonymization of DICOM datasets
# See https://mircwiki.rsna.org/index.php?title=The_CTP_DICOM_Anonymizer for legacy anonymizer documentation
import os
import re
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
from model.project import DICOMNode, Study, Series, PHI, ProjectModel
from model.anonymizer import AnonymizerModel

logger = logging.getLogger(__name__)


class AnonymizerController:
    # TODO: where best to put these string constants? Make available via UX?
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
    default_anon_date = "20000101"  # if source date is invalid or before 19000101

    _anonymize_time_slice_interval: float = 0.1  # seconds
    _anonymize_batch_size: int = 40  # number of items to process in a batch
    _clean_tag_translate_table = str.maketrans("", "", "() ,")
    # Required DICOM field attributes for accepting files:
    required_attributes = [
        "SOPClassUID",
        "SOPInstanceUID",
        "PatientID",  # TODO: handle missing PatientID
        "StudyInstanceUID",
        "SeriesInstanceUID",
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
            logger.info(f"Anonymizer Model initialised from: {project_model.anonymizer_script_path}")

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
            attr_name for attr_name in self.required_attributes if attr_name not in ds or getattr(ds, attr_name) == ""
        ]

    def save_model(self):
        anon_pkl_path = Path(self.project_model.storage_dir, AnonymizerModel.pickle_filename)
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

    def extract_first_digit(self, s):
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

        anon_patient_id = self.model.get_anon_patient_id(phi_ds.PatientID)

        if anon_patient_id == None:  # New patient
            new_anon_patient_id = self.get_next_anon_patient_id()
            # TODO: write init method for PHI using introspection for fields to look for in dataset
            phi = PHI(
                patient_name=str(phi_ds.PatientName),
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
        anon_patient_id = self.model.get_anon_patient_id(ds.PatientID)
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

    def anonymize_dataset_and_store(self, source: DICOMNode | str, ds: Dataset | None, dir: Path) -> None:
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
                logger.debug(f"_anonymize_worker processing batch size: {self._anonymize_batch_size}")
                batch = []
                for _ in range(self._anonymize_batch_size):  # Process a batch of items at a time
                    if not ds_Q.empty():
                        batch.append(ds_Q.get())

                for item in batch:
                    source, ds, dir = item

                    # Load dataset from file if dataset not provided: (eg. via local file/dir import)
                    if ds is None:
                        try:
                            assert os.path.exists(source)
                            ds = dcmread(source)
                        except Exception as e:
                            logger.error(f"dcmread error: {source}: {e}")
                            continue

                        # DICOM Dataset integrity checking:
                        missing_attributes = self.missing_attributes(ds)
                        if missing_attributes != []:
                            logger.error(f"Incoming dataset is missing required attributes: {missing_attributes}")
                            logger.error(f"\n{ds}")
                            continue

                        # Return success if instance is already stored:
                        if self.model.get_anon_uid(ds.SOPInstanceUID):
                            logger.info(f"Instance already stored: {ds.PatientID} {ds.SOPInstanceUID}")
                            continue

                    # Capture PHI and store for new studies:
                    if self.model.get_anon_uid(ds.StudyInstanceUID) == None:
                        self.capture_phi_from_new_study(ds, source)
                    else:
                        self.update_phi_from_new_instance(ds, source)

                    # Anonymize dataset (overwrite phi dataset) (prevents dataset copy)
                    ds.remove_private_tags()  # TODO: provide a switch for this? how does java anon handle this? see <r> tag
                    ds.walk(self._anonymize_element)

                    # Handle Global Tags:
                    ds.PatientIdentityRemoved = "YES"  # CS: (0012, 0062)
                    ds.DeidentificationMethod = self.deidentification_method  # LO: (0012,0063)
                    de_ident_seq = Sequence()  # SQ: (0012,0064)

                    for code, descr in self.deidentification_methods:
                        item = Dataset()
                        item.CodeValue = code
                        item.CodingSchemeDesignator = "DCM"
                        item.CodeMeaning = descr
                        de_ident_seq.append(item)

                    ds.DeidentificationMethodCodeSequence = de_ident_seq
                    block = ds.private_block(0x0013, self.private_block_name, create=True)
                    block.add_new(0x1, "SH", self.project_model.project_name)
                    # block.add_new(0x2, "SH", self.project_model.trial_name)
                    block.add_new(0x3, "SH", self.project_model.site_id)

                    logger.debug(f"ANON:\n{ds}")

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
