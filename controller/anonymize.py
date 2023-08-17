# Description: Anonymization functions for DICOM datasets
# See https://mircwiki.rsna.org/index.php?title=The_CTP_DICOM_Anonymizer for legacy anonymizer documentation

import logging
from pprint import pformat
from model.project import UIDROOT, SITEID, PROJECTNAME, TRIALNAME
from pydicom import Dataset, Sequence
import utils.config as config
from utils.translate import _
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Default values:
anonymizer_script_filename = "assets/scripts/default-anonymizer.script"
deidentification_method = _(
    "RSNA DICOM ANONYMIZER"
)  # TODO: link to app title & version
patient_id_lookup = {}
uid_lookup = {}
acc_no_seq_no = 1

# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)

_tag_keep = {}


def clear_lookups():
    global patient_id_lookup, uid_lookup, acc_no_seq_no
    patient_id_lookup.clear()
    uid_lookup.clear()
    acc_no_seq_no = 1


# Patient Mapping Function:
def get_anon_patient(name: str, id: str) -> tuple:
    # Create/Manage lookup table per project for mapping Actual to Anonymized Patient
    # TODO: patient index store
    return ("ANON_NAME", "ANON_ID")


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
            tag = e.attrib.get("t")
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
            next_patient_ndx = len(patient_id_lookup) + 1
            patient_id_lookup[dataset.PatientID] = f"{SITEID}-{next_patient_ndx:06}"
        dataset[tag].value = patient_id_lookup[dataset.PatientID]
    elif "acc" in operation:
        dataset[tag].value = f"{acc_no_seq_no}"
        acc_no_seq_no += 1
    elif "hashdate" in operation:
        dataset[tag].value = _hash_date(data_element.value, dataset.PatientID)
    return


def anonymize_dataset(ds: Dataset) -> Dataset:
    if not _tag_keep:
        if not init():
            logger.error("Failed to initialise anonymizer module")
            return ds
    # To create an anonymized dataset:
    #   Get Anon_PatientName and Anon_PatientID for this patient from get_anon_patient()
    #   Iterate through each tag in _tag_keep and copy ds[tag] to the new dataset
    ds.remove_private_tags()  # TODO: provide a switch for this? how does java anon handle this? see <r> tag
    ds.walk(anonymize_element)
    # Handle Global Tags:
    ds.PatientIdentityRemoved = "YES"  # CS: (0012, 0062)
    ds.DeidentificationMethod = deidentification_method  # LO: (0012,0063)
    de_ident_seq = Sequence()  # SQ: (0012,0064)
    methods = [
        ("113100", _("Basic Application Confidentiality Profile")),
        ("113107", _("Retain Longitudinal Temporal Information Modified Dates Option")),
        ("113108", _("Retain Patient Characteristics Option")),
    ]
    for code, descr in methods:
        item = Dataset()
        item.CodeValue = code
        item.CodingSchemeDesignator = "DCM"
        item.CodeMeaning = descr
        de_ident_seq.append(item)
    ds.DeidentificationMethodCodeSequence = de_ident_seq
    block = ds.private_block(0x0013, _("RSNA"), create=True)
    block.add_new(0x1, "SH", PROJECTNAME)
    block.add_new(0x2, "SH", TRIALNAME)
    block.add_new(0x3, "SH", SITEID)
    config.save(__name__, "patient_id_lookup", patient_id_lookup)
    config.save(__name__, "uid_lookup", uid_lookup)
    config.save(__name__, "acc_no_seq_no", acc_no_seq_no)
    return ds
