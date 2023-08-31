# Description: Anonymization functions for DICOM datasets
# See https://mircwiki.rsna.org/index.php?title=The_CTP_DICOM_Anonymizer for legacy anonymizer documentation
from typing import Dict, Tuple, List
import logging
import threading
from queue import Queue
from pprint import pformat
import time
import xml.etree.ElementTree as ET
from controller.dicom_ae import DICOMNode, DICOMRuntimeError
from model.project import UIDROOT, SITEID, PROJECTNAME, TRIALNAME
from pydicom import Dataset, Sequence
import utils.config as config
from utils.translate import _
from utils.storage import local_storage_path
from model.project import SITEID


logger = logging.getLogger(__name__)

# Default values:
anonymizer_script_filename = "assets/scripts/default-anonymizer.script"
# TODO: link to app title & version
deidentification_method = _("RSNA DICOM ANONYMIZER")

# Lookup tables for anonymization:
# TODO: move to pandas dataframe and/or sqlite db, hf5, parquet
patient_id_lookup: Dict[str, str] = {}
uid_lookup: Dict[str, str] = {}
acc_no_lookup: Dict[str, str] = {}
phi_lookup: Dict[str, Tuple[str, str, List[Tuple[str, str, str, str]]]] = {}

# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)

_tag_keep: Dict[str, str] = {}  # DICOM Tag: Operation
_anon_Q: Queue = Queue()
_anonymize_time_slice_interval: float = 0.2  # seconds
_anonymize_batch_size: int = 40  # number of items to process in a batch

deidentification_methods = [
    ("113100", _("Basic Application Confidentiality Profile")),
    (
        "113107",
        _("Retain Longitudinal Temporal Information Modified Dates Option"),
    ),
    ("113108", _("Retain Patient Characteristics Option")),
]
private_block_name = _("RSNA")


def clear_lookups():
    global patient_id_lookup, uid_lookup, acc_no_lookup
    patient_id_lookup.clear()
    uid_lookup.clear()
    acc_no_lookup.clear()
    phi_lookup.clear()


def update_lookups():
    config.save_bulk(
        __name__,
        {
            "patient_id_lookup": patient_id_lookup,
            "uid_lookup": uid_lookup,
            "acc_no_lookup": acc_no_lookup,
            "phi_lookup": phi_lookup,
        },
    )


# Anonymization functions for each script operation
def _hash_date(date: str, patient_id: str) -> str:
    return "20000101"


def init(script_filename: str = anonymizer_script_filename) -> bool:
    # Parse the anonymize script and create a dict of tags to keep: _tag_keep["tag"] = "operation"
    # The anonymization function indicated by the script operation will be used to transform source dataset

    # Open and parse the XML script file
    try:
        root = ET.parse(script_filename).getroot()

        # Extract 'e' tags into _tag_keep dictionary
        for e in root.findall("e"):  # type: ignore
            tag = str(e.attrib.get("t"))
            operation = e.text if e.text is not None else ""
            if "@remove" not in operation:
                _tag_keep[tag] = operation

        filtered_tag_keep = {k: v for k, v in _tag_keep.items() if v != ""}
        logger.info(
            f"_tag_keep has {len(_tag_keep)} entries with {len(filtered_tag_keep)} operations"
        )
        logger.info(f"_tag_keep operations:\n{pformat(filtered_tag_keep)}")
        return True

    except FileNotFoundError:
        logger.error(f"{script_filename} not found")

    except ET.ParseError:
        logger.error(
            f"Error parsing the script file {script_filename}. Please ensure it's a valid XML."
        )

    except Exception as e:
        # Catch other generic exceptions and print the error message
        logger.error(f"Error Parsing script file {script_filename}: {str(e)}")

    return False


def get_next_anon_pt_id() -> str:
    next_patient_index = len(patient_id_lookup) + 1
    return f"{SITEID}-{next_patient_index:06}"


def phi_name(anon_pt_id: str) -> str:
    return phi_lookup[anon_pt_id][0]


# Get PHI from dataset and update lookup tables
# Returns tuple of (anon_patient_id, phi update: (patient_name, patient_id, study_tuples))
def phi_from_dataset(phi_ds: Dataset, source: DICOMNode | str) -> tuple:
    def study_tuple_from_dataset(ds: Dataset) -> tuple[str, str, str, str]:
        return (
            str(ds.StudyDate),
            str(ds.AccessionNumber) if hasattr(phi_ds, "AccessionNumber") else "?",
            str(ds.StudyInstanceUID),
            str(source),
        )

    if phi_ds.PatientID not in patient_id_lookup:
        return get_next_anon_pt_id(), (
            str(phi_ds.PatientName),
            str(phi_ds.PatientID),
            [
                study_tuple_from_dataset(phi_ds),
            ],
        )
    else:  # more than one study for this patient
        anon_pt_id = patient_id_lookup[phi_ds.PatientID]
        patient_name, patient_id, study_tuples = phi_lookup[anon_pt_id]
        study_tuples.append(study_tuple_from_dataset(phi_ds))
        return anon_pt_id, (
            patient_name,
            patient_id,
            study_tuples,
        )


def anonymize_element(dataset, data_element):
    global uid_seq_no, acc_no_seq_no
    trans = str.maketrans("", "", "() ,")
    tag = str(data_element.tag).translate(trans).upper()
    # Remove data_element if not in _tag_keep:
    if tag not in _tag_keep:
        del dataset[tag]
        return
    operation = _tag_keep[tag]
    value = data_element.value
    # Keep data_element if no operation:
    if operation == "":
        return
    # Anonymize operations:
    if "@empty" in operation:  # data_element.value:
        dataset[tag].value = ""
    elif "uid" in operation:
        if not value in uid_lookup:
            next_uid_ndx = len(uid_lookup) + 1
            uid_lookup[value] = f"{UIDROOT}.{SITEID}.{next_uid_ndx}"
        dataset[tag].value = uid_lookup[value]
        return
    elif "ptid" in operation:
        if dataset.PatientID not in patient_id_lookup:
            new_anon_pt_id = get_next_anon_pt_id()
            patient_id_lookup[dataset.PatientID] = new_anon_pt_id
        dataset[tag].value = patient_id_lookup[dataset.PatientID]
    elif "acc" in operation:
        if dataset.AccessionNumber not in acc_no_lookup:
            next_acc_no_ndx = len(acc_no_lookup) + 1
            acc_no_lookup[dataset.AccessionNumber] = str(next_acc_no_ndx)
        dataset[tag].value = acc_no_lookup[dataset.AccessionNumber]
    elif "hashdate" in operation:
        dataset[tag].value = _hash_date(data_element.value, dataset.PatientID)
    return


def anonymize_dataset_and_store(source: DICOMNode | str, ds: Dataset, dir: str) -> None:
    _anon_Q.put((source, ds, dir))
    return


# TODO: Error handling & reporting
def _anonymize_worker(ds_Q: Queue) -> None:
    while True:
        while not ds_Q.empty():
            batch = []
            for _ in range(_anonymize_batch_size):  # Process a batch of items at a time
                if not ds_Q.empty():
                    batch.append(ds_Q.get())

            for item in batch:
                source, ds, dir = item  # ds_Q.get()

                # Capture PHI and store for new studies:
                if ds.StudyInstanceUID not in uid_lookup:
                    anon_pt_id, phi_update = phi_from_dataset(ds, source)
                    phi_lookup[anon_pt_id] = phi_update

                # Anonymize dataset (overwrite phi dataset) (prevents dataset copy)
                ds.remove_private_tags()  # TODO: provide a switch for this? how does java anon handle this? see <r> tag
                ds.walk(anonymize_element)

                # Handle Global Tags:
                ds.PatientIdentityRemoved = "YES"  # CS: (0012, 0062)
                ds.DeidentificationMethod = deidentification_method  # LO: (0012,0063)
                de_ident_seq = Sequence()  # SQ: (0012,0064)

                for code, descr in deidentification_methods:
                    item = Dataset()
                    item.CodeValue = code
                    item.CodingSchemeDesignator = "DCM"
                    item.CodeMeaning = descr
                    de_ident_seq.append(item)

                ds.DeidentificationMethodCodeSequence = de_ident_seq
                block = ds.private_block(0x0013, private_block_name, create=True)
                block.add_new(0x1, "SH", PROJECTNAME)
                block.add_new(0x2, "SH", TRIALNAME)
                block.add_new(0x3, "SH", SITEID)

                logger.debug(f"ANON:\n{ds}")

                # Save anonymized dataset to dicom file in local storage:
                filename = local_storage_path(dir, SITEID, ds)
                logger.debug(
                    f"C-STORE [{ds.file_meta.TransferSyntaxUID}]: {source} => {filename}"
                )
                try:
                    ds.save_as(filename, write_like_original=False)
                except Exception as exception:
                    logger.error("Failed writing instance to storage directory")
                    logger.exception(exception)

            update_lookups()

        time.sleep(
            _anonymize_time_slice_interval
        )  # timeslice for UX during intense receive activity

    return


if not init():
    msg = _("Failed to initialise anonymizer module")
    logger.error(msg)
    raise DICOMRuntimeError(msg)

threading.Thread(
    target=_anonymize_worker,
    args=(_anon_Q,),
    daemon=True,
).start()
